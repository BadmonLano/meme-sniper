"""
fee_vault.py — the "fee-wallet vault" exception (v1.0.3).

Some pump.fun launches look like a bundle but are not: the creator buys most of the
supply in the create tx, then SPL-transfers (not buys) a big slice to ONE wallet that
is also the coin's permanent creator-fee recipient. That wallet has never signed a tx.
The creator then sells its small remainder and goes quiet. Example: KIMCHI
(CSocnzcRpgSCr1naKcNTieWZUxb6rABe45j844m7pump, 2026-10-20): creator bought 79.3%,
moved 75% to the fee wallet 57s later, sold 4.31% within a minute, ran to ~$40M.

When ALL four checks pass the token is a "vault" launch:
  1. creator made an SPL transfer (not a swap) of >= VAULT_MIN_TRANSFER_PCT to one wallet
  2. that wallet == the pump.fun creator-fee recipient
  3. that wallet has zero outgoing (self-signed) transactions
  4. creator is done selling: holds < VAULT_CREATOR_DONE_PCT, or no sell for VAULT_CREATOR_QUIET_S

Effects (only when VAULT_EXCEPTION is on and the verdict is "vault"):
  - the vault wallet is dropped from the top-10 math (float view)
  - launch_spike's $100k-in-10m kill is skipped
  - hard caps still apply: SIZE_CAP, 0.1 SOL floor, drawdown, liquidity floor, rug authorities
  - entry size is fixed at VAULT_ENTRY_SOL (default 0.1)
  - exits: instant exit if the vault sends ANY tx, -25% stop, 50% off at 3x, 35% trail

Env knobs (all optional):
  VAULT_EXCEPTION            true|false   default true  (master off-switch)
  VAULT_MIN_TRANSFER_PCT     default 20   % of supply moved creator -> vault
  VAULT_CREATOR_DONE_PCT     default 5    creator balance % that counts as done
  VAULT_CREATOR_QUIET_S      default 60   seconds with no creator sell that counts as done
  VAULT_ENTRY_SOL            default 0.1
  VAULT_STOP_PCT             default 25
  VAULT_PARTIAL_AT_X         default 3    (3x = +200%)
  VAULT_PARTIAL_PCT          default 50
  VAULT_TRAIL_PCT            default 35

Pure logic lives in evaluate_vault() so it is testable without RPC.
gather_vault_facts() is the one async RPC reader; failures return None -> no exception.
"""
from __future__ import annotations

import os
import time
from typing import Callable, Optional

TOTAL_SUPPLY_RAW_DEFAULT = 1_000_000_000 * 10**6   # pump.fun: 1B tokens, 6 decimals


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
    return _on("VAULT_EXCEPTION", "true")


# ── pure verdict ────────────────────────────────────────────────────────────
def evaluate_vault(facts: Optional[dict], now_ts: Optional[float] = None) -> dict:
    """facts = {
        creator, fee_recipients: [addr],
        creator_transfers: [{to, pct, kind: "transfer"|"swap", ts}],
        receiver_outgoing_sigs: {addr: int},
        creator_balance_pct: float, creator_last_sell_ts: float|None, creator_first_ts: float|None
    }
    Returns {vault: bool, vault_wallet, vault_pct, checks: {...}, reason}."""
    out = {"vault": False, "vault_wallet": None, "vault_pct": None, "checks": {}, "reason": ""}
    if not enabled():
        out["reason"] = "VAULT_EXCEPTION off"
        return out
    if not facts:
        out["reason"] = "no facts"
        return out
    now_ts = time.time() if now_ts is None else now_ts
    min_pct = _f("VAULT_MIN_TRANSFER_PCT", 20)
    fees = {a for a in (facts.get("fee_recipients") or []) if a}
    creator = facts.get("creator")

    # 1. a plain SPL transfer (not a swap) of a big slice to one wallet
    big = [t for t in (facts.get("creator_transfers") or [])
           if t.get("kind") == "transfer" and float(t.get("pct") or 0) >= min_pct
           and t.get("to") and t.get("to") != creator]
    c1 = bool(big)
    out["checks"]["creator_transfer"] = c1
    if not c1:
        out["reason"] = f"no creator SPL transfer >= {min_pct:.0f}% to one wallet"
        return out
    t = max(big, key=lambda x: float(x.get("pct") or 0))
    wallet = t["to"]
    out["vault_wallet"], out["vault_pct"] = wallet, round(float(t["pct"]), 2)

    # 2. receiver is the creator-fee recipient
    c2 = wallet in fees
    out["checks"]["is_fee_recipient"] = c2
    # 3. receiver never signed anything
    outgoing = (facts.get("receiver_outgoing_sigs") or {}).get(wallet)
    c3 = outgoing == 0
    out["checks"]["receiver_never_signed"] = c3
    # 4. creator done selling
    bal = facts.get("creator_balance_pct")
    last_sell = facts.get("creator_last_sell_ts") or facts.get("creator_first_ts")
    quiet = _f("VAULT_CREATOR_QUIET_S", 60)
    c4 = (bal is not None and float(bal) < _f("VAULT_CREATOR_DONE_PCT", 5)) or \
         (last_sell is not None and now_ts - float(last_sell) >= quiet)
    out["checks"]["creator_done"] = c4

    fails = [k for k, v in out["checks"].items() if not v]
    out["vault"] = not fails
    out["reason"] = "fee-wallet vault" if not fails else "failed: " + ",".join(fails)
    return out


def float_top10_pct(top_holders: list, vault_owner: str, total_raw: int) -> Optional[float]:
    """Top-10 % recomputed without the vault wallet. top_holders rows carry
    {owner|address, amount}. Returns None if nothing usable."""
    if not top_holders or not total_raw:
        return None
    rows = [r for r in top_holders
            if (r.get("owner") or r.get("address")) != vault_owner]
    amt = sum(int(float(r.get("amount") or 0)) for r in rows[:10])
    return round(amt / total_raw * 100, 1)


def entry_size_sol() -> float:
    return max(0.1, _f("VAULT_ENTRY_SOL", 0.1))   # never under the 0.1 SOL floor


def exit_params(base: Optional[dict] = None) -> dict:
    """Position params for a vault entry (the monitor's existing fields)."""
    p = dict(base or {})
    x = _f("VAULT_PARTIAL_AT_X", 3)
    p.update({
        "stop_loss_pct": _f("VAULT_STOP_PCT", 25),
        "partial_take_at_pct": (x - 1) * 100,          # 3x == +200%
        "partial_take_pct": _f("VAULT_PARTIAL_PCT", 50),
        "trail_activate_pct": (x - 1) * 100,
        "trail_drop_pct": _f("VAULT_TRAIL_PCT", 35),
        "tp_targets_pct": [],                           # trail runs the rest
    })
    return p


def vault_exit_trigger(position: dict, outgoing_now: Optional[int]) -> Optional[dict]:
    """Instant exit if the vault wallet has sent ANY tx since entry."""
    v = position.get("fee_vault") or (position.get("params") or {}).get("fee_vault") or {}
    if not v.get("wallet") or outgoing_now is None:
        return None
    if int(outgoing_now) > int(v.get("outgoing_at_entry") or 0):
        return {"type": "vault_moved", "severity": "critical",
                "details": f"fee vault {v['wallet'][:6]}… signed a tx (transfer/sell). exit all."}
    return None


# ── RPC reader ──────────────────────────────────────────────────────────────
async def count_outgoing(wallet: str, rpc: Callable, limit: int = 1000) -> Optional[int]:
    """Number of txs the wallet itself signed (fee payer / first signer)."""
    try:
        sigs = await rpc("getSignaturesForAddress", [wallet, {"limit": limit}])
        rows = sigs if isinstance(sigs, list) else (sigs or {}).get("result") or []
        n = 0
        for s in rows[:50]:                        # check the newest 50 for signer
            tx = await rpc("getTransaction", [s["signature"], {"encoding": "jsonParsed",
                                                                "maxSupportedTransactionVersion": 0}])
            keys = (((tx or {}).get("transaction") or {}).get("message") or {}).get("accountKeys") or []
            if any((k.get("pubkey") == wallet and k.get("signer")) for k in keys if isinstance(k, dict)):
                n += 1
        return n
    except Exception:
        return None


def _parse_creator_tx(tx: dict, mint: str, creator: str, total_raw: int) -> list:
    """Classify the creator's token moves in one parsed tx as transfer vs swap."""
    out = []
    meta = (tx or {}).get("meta") or {}
    msg = ((tx or {}).get("transaction") or {}).get("message") or {}
    ts = (tx or {}).get("blockTime")
    progs = {i.get("programId") for i in msg.get("instructions") or [] if isinstance(i, dict)}
    pump = {"6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P", "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"}
    is_swap = bool(progs & pump)
    pre = {(b.get("owner"), b.get("mint")): int(b["uiTokenAmount"]["amount"])
           for b in meta.get("preTokenBalances") or [] if b.get("mint") == mint}
    post = {(b.get("owner"), b.get("mint")): int(b["uiTokenAmount"]["amount"])
            for b in meta.get("postTokenBalances") or [] if b.get("mint") == mint}
    cdelta = post.get((creator, mint), 0) - pre.get((creator, mint), 0)
    if cdelta >= 0:
        return out
    for (owner, _), amt in post.items():
        gain = amt - pre.get((owner, mint), 0)
        if owner != creator and gain > 0:
            out.append({"to": owner, "pct": gain / total_raw * 100, "ts": ts,
                        "kind": "swap" if is_swap else "transfer"})
    return out


async def gather_vault_facts(mint: str, creator: str, fee_recipients: list, rpc: Callable,
                             total_raw: int = TOTAL_SUPPLY_RAW_DEFAULT, max_tx: int = 40) -> Optional[dict]:
    """Read the creator's earliest txs for this mint. None on any failure."""
    if not (enabled() and mint and creator):
        return None
    try:
        sigs = await rpc("getSignaturesForAddress", [creator, {"limit": 200}])
        rows = sigs if isinstance(sigs, list) else (sigs or {}).get("result") or []
        transfers, last_sell, first_ts = [], None, None
        for s in list(reversed(rows))[-max_tx:]:
            tx = await rpc("getTransaction", [s["signature"], {"encoding": "jsonParsed",
                                                                "maxSupportedTransactionVersion": 0}])
            moves = _parse_creator_tx(tx, mint, creator, total_raw)
            for m in moves:
                transfers.append(m)
                if m["kind"] == "swap":
                    last_sell = max(last_sell or 0, m["ts"] or 0)
            if moves and first_ts is None:
                first_ts = moves[0]["ts"]
        bal_pct = None
        try:
            r = await rpc("getTokenAccountsByOwner", [creator, {"mint": mint}, {"encoding": "jsonParsed"}])
            vals = (r or {}).get("value") or []
            raw = sum(int(v["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"]) for v in vals)
            bal_pct = raw / total_raw * 100
        except Exception:
            pass
        recv = {t["to"] for t in transfers if t["kind"] == "transfer"}
        outgoing = {w: await count_outgoing(w, rpc) for w in recv}
        return {"creator": creator, "fee_recipients": list(fee_recipients or []),
                "creator_transfers": transfers, "receiver_outgoing_sigs": outgoing,
                "creator_balance_pct": bal_pct, "creator_last_sell_ts": last_sell,
                "creator_first_ts": first_ts}
    except Exception:
        return None


# ── pump.fun fee recipient + one-call verdict (cached) ─────────────────────
_CACHE: dict = {}


def fetch_fee_recipients(mint: str, timeout: float = 6.0) -> list:
    """Best effort: pump.fun's public coin API. Reads creator / fee-recipient /
    fee-sharing fields when present. Empty list on failure -> check 2 fails -> no exception."""
    import json
    import urllib.request
    out = []
    for url in (f"https://frontend-api-v3.pump.fun/coins/{mint}",):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                       "User-Agent": "meme-sniper/1.0.3"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode("utf-8"))
        except Exception:
            continue
        for k in ("fee_recipient", "creator_fee_recipient", "creator"):
            v = d.get(k) if isinstance(d, dict) else None
            if isinstance(v, str) and v:
                out.append(v)
        for sh in (d.get("fee_sharing") or d.get("shareholders") or []) if isinstance(d, dict) else []:
            a = sh.get("address") if isinstance(sh, dict) else None
            if a:
                out.append(a)
    return list(dict.fromkeys(out))


async def check_mint(mint: str, creator: Optional[str], rpc: Callable,
                     age_minutes: Optional[float] = None) -> dict:
    """Full verdict for a young mint. Cached per mint once it resolves."""
    if not enabled():
        return {"vault": False, "reason": "VAULT_EXCEPTION off"}
    if mint in _CACHE:
        return _CACHE[mint]
    if age_minutes is not None and age_minutes > _f("VAULT_MAX_AGE_MIN", 90):
        return {"vault": False, "reason": "too old for vault check"}
    if not creator:
        return {"vault": False, "reason": "creator unknown"}
    import asyncio
    fees = await asyncio.to_thread(fetch_fee_recipients, mint)
    facts = await gather_vault_facts(mint, creator, fees, rpc)
    res = evaluate_vault(facts)
    res["creator"] = creator
    if res.get("vault_wallet"):
        res["outgoing_at_entry"] = (facts or {}).get("receiver_outgoing_sigs", {}).get(res["vault_wallet"])
    if facts is not None:
        _CACHE[mint] = res
        if len(_CACHE) > 2000:
            for k in list(_CACHE)[:1000]:
                _CACHE.pop(k, None)
    return res
