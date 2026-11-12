"""
celeb_post.py — celebrity-post rule (v1.0.4).

Trigger: a verified or large-follower X account posts a pump.fun CA.
Enter only once the creator has fully sold (< CELEB_CREATOR_MAX_PCT, default 1%).
Veto when the creator looks like part of a launch cluster:
  - creator was funded BEFORE launch by a wallet that paid several wallets in one tx
    (a "fan-out" funder, >= CELEB_FANOUT_MIN recipients), or
  - the creator (or a wallet it funded / was funded by) launched another coin
    within CELEB_CLUSTER_WINDOW_H hours.
Exits: half at 3x, rest on a 35% trail, -25% stop. Entry fixed CELEB_ENTRY_SOL (0.1).

Missing data = fail safe: any unknown fact -> no entry (reason says which).

Signal shape (from X Intel or any agent): sig["celeb_post"] = {
    "handle": str, "followers": int, "verified": bool, "post_id": str, "posted_ts": float }

Env: CELEB_POST_RULE (true|false, default true), CELEB_MIN_FOLLOWERS (250000),
CELEB_REQUIRE_VERIFIED (true), CELEB_CREATOR_MAX_PCT (1), CELEB_FANOUT_MIN (3),
CELEB_CLUSTER_WINDOW_H (24), CELEB_ENTRY_SOL (0.1), CELEB_STOP_PCT (25),
CELEB_PARTIAL_AT_X (3), CELEB_PARTIAL_PCT (50), CELEB_TRAIL_PCT (35),
CELEB_MAX_POST_AGE_MIN (240).
"""
from __future__ import annotations

import os
import time
from typing import Callable, Optional

TOTAL_SUPPLY_RAW = 1_000_000_000 * 10**6
PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"


def _e(k, d=""):
    v = os.environ.get(k)
    return d if v is None or not str(v).strip() else str(v).strip()


def _on(k, d="true"):
    return _e(k, d).lower() in ("1", "true", "yes", "on")


def _f(k, d):
    try:
        return float(_e(k, str(d)))
    except ValueError:
        return float(d)


def enabled() -> bool:
    return _on("CELEB_POST_RULE", "true")


def is_celeb(post: Optional[dict]) -> bool:
    if not post:
        return False
    try:
        big = int(post.get("followers") or 0) >= _f("CELEB_MIN_FOLLOWERS", 250000)
    except (TypeError, ValueError):
        big = False
    ver = bool(post.get("verified"))
    return (big and ver) if _on("CELEB_REQUIRE_VERIFIED", "true") else (big or ver)


def evaluate(post: Optional[dict], facts: Optional[dict], now_ts: Optional[float] = None) -> dict:
    """facts = {creator, creator_balance_pct, funders: [{wallet, recipients_in_tx, ts}],
                launch_ts, cluster_launches: [{mint, ts, by}] }   (cluster excludes this mint)
    Returns {enter: bool, veto: bool, wait: bool, reason, checks}."""
    out = {"enter": False, "veto": False, "wait": False, "reason": "", "checks": {}}
    if not enabled():
        out["reason"] = "CELEB_POST_RULE off"
        return out
    if not is_celeb(post):
        out["reason"] = "not a verified/large account"
        return out
    now_ts = time.time() if now_ts is None else now_ts
    pts = (post or {}).get("posted_ts")
    if pts and (now_ts - float(pts)) / 60 > _f("CELEB_MAX_POST_AGE_MIN", 240):
        out["reason"] = "post too old"
        return out
    if not facts:
        out["reason"] = "fail-safe: no on-chain facts"
        return out

    funders = facts.get("funders")
    launch_ts = facts.get("launch_ts")
    if funders is None or launch_ts is None:
        out["reason"] = "fail-safe: funding history unknown"
        return out
    fan = [f for f in funders
           if f.get("ts") is not None and float(f["ts"]) <= float(launch_ts)
           and int(f.get("recipients_in_tx") or 0) >= int(_f("CELEB_FANOUT_MIN", 3))]
    out["checks"]["fanout_funder"] = bool(fan)
    if fan:
        out["veto"] = True
        out["reason"] = (f"veto: creator funded pre-launch by fan-out wallet "
                         f"{str(fan[0].get('wallet'))[:6]}… ({fan[0].get('recipients_in_tx')} wallets in one tx)")
        return out

    cl = facts.get("cluster_launches")
    if cl is None:
        out["reason"] = "fail-safe: cluster launches unknown"
        return out
    win = _f("CELEB_CLUSTER_WINDOW_H", 24) * 3600
    near = [c for c in cl if c.get("ts") is not None and abs(float(c["ts"]) - float(launch_ts)) <= win]
    out["checks"]["cluster_second_coin"] = bool(near)
    if near:
        out["veto"] = True
        out["reason"] = f"veto: same cluster launched {str(near[0].get('mint'))[:6]}… too"
        return out

    bal = facts.get("creator_balance_pct")
    if bal is None:
        out["reason"] = "fail-safe: creator balance unknown"
        return out
    done = float(bal) < _f("CELEB_CREATOR_MAX_PCT", 1)
    out["checks"]["creator_sold"] = done
    if not done:
        out["wait"] = True
        out["reason"] = f"wait: creator still holds {float(bal):.2f}%"
        return out
    out["enter"] = True
    out["reason"] = f"celeb post by @{post.get('handle')} and creator fully sold"
    return out


def entry_size_sol() -> float:
    return max(0.1, _f("CELEB_ENTRY_SOL", 0.1))


def exit_params(base: Optional[dict] = None) -> dict:
    p = dict(base or {})
    x = _f("CELEB_PARTIAL_AT_X", 3)
    p.update({"stop_loss_pct": _f("CELEB_STOP_PCT", 25),
              "partial_take_at_pct": (x - 1) * 100, "partial_take_pct": _f("CELEB_PARTIAL_PCT", 50),
              "trail_activate_pct": (x - 1) * 100, "trail_drop_pct": _f("CELEB_TRAIL_PCT", 35),
              "tp_targets_pct": []})
    return p


# ── RPC reader (all failures -> None -> fail safe) ──────────────────────────
def _rows(r):
    return r if isinstance(r, list) else (r or {}).get("result") or [] if isinstance(r, dict) else []


async def _tx(rpc, sig):
    return await rpc("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])


def _sol_out_recipients(tx: dict, payer: str) -> int:
    """How many distinct wallets received SOL from `payer` in this tx."""
    n = set()
    for ix in (((tx or {}).get("transaction") or {}).get("message") or {}).get("instructions") or []:
        p = (ix or {}).get("parsed") if isinstance(ix, dict) else None
        if isinstance(p, dict) and p.get("type") == "transfer":
            info = p.get("info") or {}
            if info.get("source") == payer and info.get("lamports"):
                n.add(info.get("destination"))
    return len(n)


def _created_mint(tx: dict) -> Optional[str]:
    msg = ((tx or {}).get("transaction") or {}).get("message") or {}
    if not any((i or {}).get("programId") == PUMP_PROGRAM for i in msg.get("instructions") or []):
        return None
    logs = " ".join(((tx or {}).get("meta") or {}).get("logMessages") or [])
    if "Instruction: Create" not in logs:
        return None
    for b in ((tx or {}).get("meta") or {}).get("postTokenBalances") or []:
        if str(b.get("mint", "")).endswith("pump"):
            return b["mint"]
    return None


async def gather_facts(mint: str, creator: str, launch_ts: Optional[float], rpc: Callable,
                       max_tx: int = 60) -> Optional[dict]:
    if not (enabled() and mint and creator and launch_ts):
        return None
    try:
        rows = _rows(await rpc("getSignaturesForAddress", [creator, {"limit": 200}]))
        if not rows or len(rows) >= 200:
            return None                      # can't see the full history -> fail safe
        funders, launches = [], []
        for s in list(reversed(rows))[:max_tx]:
            tx = await _tx(rpc, s["signature"])
            if not tx:
                continue
            ts = tx.get("blockTime")
            m = _created_mint(tx)
            if m and m != mint:
                launches.append({"mint": m, "ts": ts, "by": creator})
            for ix in ((tx.get("transaction") or {}).get("message") or {}).get("instructions") or []:
                p = (ix or {}).get("parsed") if isinstance(ix, dict) else None
                if isinstance(p, dict) and p.get("type") == "transfer":
                    info = p.get("info") or {}
                    if info.get("destination") == creator and info.get("source") != creator:
                        funders.append({"wallet": info["source"], "ts": ts,
                                        "recipients_in_tx": _sol_out_recipients(tx, info["source"])})
                    elif info.get("source") == creator and info.get("lamports", 0) >= 10**9:
                        # creator funded another wallet: check if that wallet launched a coin
                        sub = _rows(await rpc("getSignaturesForAddress", [info["destination"], {"limit": 50}]))
                        for ss in sub[:20]:
                            stx = await _tx(rpc, ss["signature"])
                            sm = _created_mint(stx)
                            if sm and sm != mint:
                                launches.append({"mint": sm, "ts": (stx or {}).get("blockTime"),
                                                 "by": info["destination"]})
        r = await rpc("getTokenAccountsByOwner", [creator, {"mint": mint}, {"encoding": "jsonParsed"}])
        vals = (r or {}).get("value")
        if vals is None:
            return None
        raw = sum(int(v["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"]) for v in vals)
        return {"creator": creator, "launch_ts": launch_ts, "funders": funders,
                "cluster_launches": launches, "creator_balance_pct": raw / TOTAL_SUPPLY_RAW * 100}
    except Exception:
        return None
