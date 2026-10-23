"""
sniper_upgrades.py - Meme Sniper market-structure upgrades (Oct 2026).

Pure helpers the engine calls from three places. Nothing here sizes, buys, sells,
moves stops or touches caps. Every gate only ever says "skip" or "flag".

  pre_gate(pair, mint)          sync, no RPC. Runs right after the DexScreener pair
                                is fetched. Custom-pair quote, reserve sanity,
                                Meteora DAMM v2 / DBC drain guard, xStock check,
                                wash-volume check, token type.
  launch_signals(mint, ...)     async, ONE RPC call, cached per mint. Bundle signal:
                                how many txs landed in the launch slot.
  card_flags(sig) / card_fields(sig)   what the candidate card shows.
  classify_swap_error(err)      fee-sweep (CreatorFeesNotSwept) recognition.
  swap_execute(...)             optional Jupiter Swap API V2 (/order + /execute)
                                with the existing v1 path as fallback.

Env (blank = default):
  CUSTOM_PAIR_ACTION        flag | skip | off     default flag
  RESERVE_GUARD             skip | flag | off     default skip   (skip + recheck)
  METEORA_DRAIN_GUARD       skip | flag | off     default skip
  METEORA_DRAIN_LIQ_DROP_PCT                      default 50
  METEORA_DRAIN_DUMP_PCT                          default 60   (5m price drop)
  METEORA_DRAIN_ALL_VENUES  true | false          default false
  XSTOCKS_CHECK             true | false          default true (official xStocks API, cached 24h)
  FAKE_XSTOCK_ACTION        flag | skip           default flag
  WASH_CHECK                true | false          default true (flag only)
  WASH_VOL_LIQ_RATIO                              default 40   (24h volume / liquidity)
  WASH_AVG_TRADE_USD                              default 1500 (1h avg trade with thin liq)
  BUNDLE_CHECK              true | false          default true (card field, 1 RPC per young mint)
  BUNDLE_CHECK_MAX_AGE_MIN                        default 90
  BUNDLE_FLAG_MIN_TX                              default 4
  FEE_SWEEP_NUMERIC_CODES   true | false          default false (codes are from 3rd-party SDK docs)
  FEE_SWEEP_RECHECK_MIN                           default 30
  JUPITER_SWAP_V2           true | false          default false
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional


def _e(k: str, d: str = "") -> str:
    v = os.environ.get(k)
    return d if v is None or not str(v).strip() else str(v).strip()


def _on(k: str, d: str) -> bool:
    return _e(k, d).lower() in ("1", "true", "yes", "on")


def _f(k: str, d: float) -> float:
    try:
        return float(_e(k, str(d)))
    except ValueError:
        return d


def _mode(k: str, d: str, allowed: tuple) -> str:
    v = _e(k, d).lower()
    return v if v in allowed else d


SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
# Verified on docs.meteora.ag (developer guides, Oct 2026)
METEORA_DAMM_V2_PROGRAM = "cpamdpZCGKUy5JxQXB4dcpGPiikHawvSWAd6mEn1sGG"
METEORA_DBC_PROGRAM = "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN"
XSTOCKS_API = "https://api.xstocks.fi/api/v2/public/assets"

_BOT_LOGS = Path(os.environ.get("WS_BOT_LOGS") or Path(__file__).resolve().parent.parent / "bot_logs")
_LOCK = threading.Lock()
_LIQ_PEAK: dict = {}          # mint -> {"peak": usd, "at": ts}
_BUNDLE_CACHE: dict = {}      # mint -> result
_FEE_SWEEP: dict = {}         # mint -> until_ts
_XSTOCKS = {"at": 0.0, "mints": {}, "symbols": {}, "err": None}


def init(bot_logs) -> None:
    global _BOT_LOGS
    try:
        _BOT_LOGS = Path(bot_logs)
        _BOT_LOGS.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    _xstocks_load_cache()


def _jsonl(name: str, rec: dict) -> None:
    try:
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec}
        with _LOCK, open(_BOT_LOGS / name, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass


def _num(x) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


# ── xStocks allowlist (official Backed/xStocks public API) ───────────────────
def _xstocks_load_cache() -> None:
    try:
        d = json.loads((_BOT_LOGS / "xstocks_allowlist.json").read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("mints"), dict):
            _XSTOCKS.update(at=float(d.get("at") or 0), mints=d["mints"], symbols=d.get("symbols") or {})
    except Exception:
        pass


def refresh_xstocks(force: bool = False, timeout: float = 8.0) -> int:
    """Pull every Solana xStock mint from the official API. Cached 24h on disk.
    Sync (urllib) and called at most once a day, so it never blocks a scan for long."""
    if not _on("XSTOCKS_CHECK", "true"):
        return 0
    if not force and _XSTOCKS["mints"] and time.time() - _XSTOCKS["at"] < 86400:
        return len(_XSTOCKS["mints"])
    if not force and _XSTOCKS.get("err_at") and time.time() - _XSTOCKS["err_at"] < 1800:
        return len(_XSTOCKS["mints"])
    import urllib.request
    mints, syms, page = {}, {}, 0
    try:
        while page < 20:
            url = f"{XSTOCKS_API}?network=Solana&pageSize=100&page={page}"
            req = urllib.request.Request(url, headers={"User-Agent": "meme-sniper/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode("utf-8"))
            for n in d.get("nodes") or []:
                for dep in n.get("deployments") or []:
                    if dep.get("network") == "Solana" and dep.get("address"):
                        mints[dep["address"]] = {"symbol": n.get("symbol"), "name": n.get("name"),
                                                 "underlying": (n.get("underlying") or {}).get("symbol")
                                                 or n.get("underlyingSymbol")}
                        if n.get("symbol"):
                            syms[str(n["symbol"]).upper()] = dep["address"]
            if not (d.get("page") or {}).get("hasNextPage"):
                break
            page += 1
        if mints:
            _XSTOCKS.update(at=time.time(), mints=mints, symbols=syms, err=None)
            (_BOT_LOGS / "xstocks_allowlist.json").write_text(
                json.dumps({"at": time.time(), "source": XSTOCKS_API, "mints": mints, "symbols": syms}, indent=1),
                encoding="utf-8")
    except Exception as ex:
        _XSTOCKS["err"] = type(ex).__name__
        _XSTOCKS["err_at"] = time.time()
    return len(_XSTOCKS["mints"])


_XS_THREAD = {"t": None}


def _xstocks_refresh_bg() -> None:
    """Never block the scan loop on the network: refresh in a daemon thread when stale."""
    if not _on("XSTOCKS_CHECK", "true"):
        return
    if _XSTOCKS["mints"] and time.time() - _XSTOCKS["at"] < 86400:
        return
    t = _XS_THREAD["t"]
    if t is not None and t.is_alive():
        return
    _XS_THREAD["t"] = threading.Thread(target=refresh_xstocks, daemon=True, name="xstocks_refresh")
    _XS_THREAD["t"].start()


def xstock_info(mint: Optional[str]) -> Optional[dict]:
    return _XSTOCKS["mints"].get(mint or "") if mint else None


_XSTOCK_NAME = re.compile(r"\bx\s*stocks?\b|xstock", re.I)


def _looks_like_xstock(sym: str, name: str) -> bool:
    s = (sym or "").strip()
    if _XSTOCK_NAME.search(name or ""):
        return True
    return bool(s) and s.upper() in _XSTOCKS["symbols"]


# ── quote / pair classification ───────────────────────────────────────────────
def quote_info(pair: dict) -> dict:
    q = pair.get("quoteToken") or {}
    qm, qs = q.get("address") or "", q.get("symbol") or "?"
    if qm == SOL_MINT or qs.upper() in ("SOL", "WSOL") and not qm:
        kind = "sol"
    elif qm in (USDC_MINT, USDT_MINT):
        kind = "stable"
    elif xstock_info(qm):
        kind = "xstock"
    elif qm.endswith("pump"):
        kind = "pump_coin"
    else:
        kind = "other"
    return {"mint": qm, "symbol": qs, "kind": kind, "custom_pair": kind not in ("sol", "stable")}


def token_type(pair: dict, qi: dict) -> str:
    base = pair.get("baseToken") or {}
    bm = base.get("address") or ""
    dex = (pair.get("dexId") or "").lower()
    labels = [str(x).upper() for x in (pair.get("labels") or [])]
    if xstock_info(bm):
        return "xstock (verified)"
    if qi["kind"] == "xstock":
        return f"stock-meme pair ({qi['symbol']})"
    if qi["custom_pair"]:
        return f"custom pair meme (quote {qi['symbol']})"
    if "moonshot" in dex or "moonit" in dex:
        return "moonshot meme"
    if "meteora" in dex:
        return "meteora " + ("dbc" if "DBC" in labels else "damm v2" if "DYN2" in labels else "pool")
    if bm.endswith("pump") or dex.startswith("pump"):
        return "pump.fun meme"
    if bm.endswith("bonk"):
        return "bonk.fun meme"
    return "meme"


# ── guards ────────────────────────────────────────────────────────────────────
def _reserves(pair: dict) -> Optional[str]:
    liq = pair.get("liquidity") or {}
    if not isinstance(liq, dict):
        return None
    for k in ("usd", "base", "quote"):
        v = liq.get(k)
        if v is None:
            continue
        n = _num(v)
        if n is None:
            return f"liquidity.{k} unreadable ({str(v)[:20]})"
        if n < 0:
            return f"liquidity.{k} negative ({n:,.2f})"
    b, q = _num(liq.get("base")), _num(liq.get("quote"))
    if b is not None and q is not None and (_num(liq.get("usd")) or 0) > 0 and (b == 0 or q == 0):
        return f"one-sided reserves (base {b:,.0f}, quote {q:,.4f})"
    px = _num(pair.get("priceUsd"))
    if pair.get("priceUsd") is not None and (px is None or px <= 0):
        return "priceUsd zero or negative"
    return None


def _drain(mint: str, pair: dict) -> Optional[str]:
    dex = (pair.get("dexId") or "").lower()
    if "meteora" not in dex and not _on("METEORA_DRAIN_ALL_VENUES", "false"):
        return None
    liq = _num((pair.get("liquidity") or {}).get("usd")) or 0
    now = time.time()
    rec = _LIQ_PEAK.get(mint)
    if not rec or now - rec["at"] > 6 * 3600 or liq >= rec["peak"]:
        _LIQ_PEAK[mint] = rec = {"peak": liq, "at": now}
    drop = (1 - liq / rec["peak"]) * 100 if rec["peak"] > 0 else 0
    m5 = _num((pair.get("priceChange") or {}).get("m5")) or 0
    h1 = _num((pair.get("priceChange") or {}).get("h1")) or 0
    if drop >= _f("METEORA_DRAIN_LIQ_DROP_PCT", 50):
        return f"LP pulled: liquidity -{drop:.0f}% vs 6h peak ${rec['peak']:,.0f}"
    if m5 <= -_f("METEORA_DRAIN_DUMP_PCT", 60) or (h1 <= -80 and drop >= 30):
        return f"creator-style dump: 5m {m5:.0f}%, 1h {h1:.0f}%, liq -{drop:.0f}%"
    return None


def _wash(pair: dict) -> Optional[str]:
    if not _on("WASH_CHECK", "true"):
        return None
    liq = _num((pair.get("liquidity") or {}).get("usd")) or 0
    vol = pair.get("volume") or {}
    tx = (pair.get("txns") or {}).get("h1") or {}
    v24, v1 = _num(vol.get("h24")) or 0, _num(vol.get("h1")) or 0
    n1 = (_num(tx.get("buys")) or 0) + (_num(tx.get("sells")) or 0)
    out = []
    if liq > 0 and v24 / liq >= _f("WASH_VOL_LIQ_RATIO", 40):
        out.append(f"24h vol {v24 / liq:.0f}x liquidity")
    if n1 >= 10 and liq < 60_000 and v1 / n1 >= _f("WASH_AVG_TRADE_USD", 1500):
        out.append(f"avg 1h trade ${v1 / n1:,.0f} on ${liq:,.0f} liq")
    b, s = _num(tx.get("buys")) or 0, _num(tx.get("sells")) or 0
    if n1 >= 200 and min(b, s) / max(b, s, 1) >= 0.97:
        out.append(f"buys/sells mirror ({b:.0f}/{s:.0f})")
    return "; ".join(out) or None


def pre_gate(pair: dict, mint: str) -> dict:
    """Returns {quote, token_type, flags[], skip_reason?, recheck?, detail?}. Never raises."""
    sig: dict = {"flags": []}
    try:
        _xstocks_refresh_bg()
        qi = quote_info(pair)
        sig["quote"] = qi
        sig["token_type"] = token_type(pair, qi)
        base = pair.get("baseToken") or {}

        act = _mode("CUSTOM_PAIR_ACTION", "flag", ("flag", "skip", "off"))
        if qi["custom_pair"] and act != "off":
            sig["flags"].append(f"CUSTOM PAIR: quoted in {qi['symbol']} ({qi['kind']}) - USD price used, "
                                f"route goes SOL->{qi['symbol']}->token, flat 1.25% curve fee")
            if act == "skip":
                return _skip(sig, mint, "custom_pair_skipped", qi["symbol"], recheck=False)

        r = _reserves(pair)
        rg = _mode("RESERVE_GUARD", "skip", ("skip", "flag", "off"))
        if r and rg != "off":
            sig["flags"].append("INVALID RESERVES: " + r)
            if rg == "skip":
                return _skip(sig, mint, "invalid_reserves_pending_recheck", r, recheck=True)

        until = _FEE_SWEEP.get(mint)
        if until and time.time() < until:
            return _skip(sig, mint, "fee_sweep_pending_recheck", "CreatorFeesNotSwept seen on last swap", recheck=True)

        d = _drain(mint, pair)
        dg = _mode("METEORA_DRAIN_GUARD", "skip", ("skip", "flag", "off"))
        if d and dg != "off":
            sig["flags"].append("RUG DRAIN: " + d)
            if dg == "skip":
                return _skip(sig, mint, "meteora_drain_guard", d, recheck=False)

        if _on("XSTOCKS_CHECK", "true") and _XSTOCKS["mints"]:
            bm = base.get("address") or mint
            if xstock_info(bm):
                sig["xstock"] = xstock_info(bm)
            elif _looks_like_xstock(base.get("symbol"), base.get("name")):
                sig["flags"].append(f"FAKE XSTOCK: {base.get('symbol')} is not on the official xStocks list")
                if _mode("FAKE_XSTOCK_ACTION", "flag", ("flag", "skip")) == "skip":
                    return _skip(sig, mint, "fake_xstock", base.get("symbol") or "", recheck=False)
            if qi["kind"] == "xstock":
                sig["stock_meme"] = {"quote": qi["symbol"], "underlying": (xstock_info(qi["mint"]) or {}).get("underlying")}

        w = _wash(pair)
        if w:
            sig["flags"].append("WASH VOLUME? " + w)
            sig["wash"] = w
    except Exception as ex:
        sig["error"] = f"{type(ex).__name__}: {str(ex)[:100]}"
    return sig


def _skip(sig: dict, mint: str, reason: str, detail: str, *, recheck: bool) -> dict:
    sig.update(skip_reason=reason, detail=detail, recheck=recheck)
    _jsonl("sniper_upgrades.jsonl", {"event": "gate_skip", "mint": mint, "reason": reason, "detail": detail})
    return sig


# ── bundle signal (one RPC call per young mint, cached) ──────────────────────
async def launch_signals(mint: str, rpc: Callable, age_minutes=None) -> Optional[dict]:
    if not _on("BUNDLE_CHECK", "true") or not mint:
        return None
    if mint in _BUNDLE_CACHE:
        return _BUNDLE_CACHE[mint]
    try:
        if age_minutes is None or float(age_minutes) > _f("BUNDLE_CHECK_MAX_AGE_MIN", 90):
            return None
    except (TypeError, ValueError):
        return None
    res = None
    try:
        sigs = await rpc("getSignaturesForAddress", [mint, {"limit": 1000}])
        rows = sigs if isinstance(sigs, list) else (sigs or {}).get("result") if isinstance(sigs, dict) else None
        rows = [s for s in (rows or []) if isinstance(s, dict) and s.get("slot") is not None]
        if rows and len(rows) < 1000:          # oldest row is the launch only if we saw everything
            first = min(int(s["slot"]) for s in rows)
            launch = [s for s in rows if int(s["slot"]) == first]
            nxt = [s for s in rows if first < int(s["slot"]) <= first + 2]
            ok = [s for s in launch if not s.get("err")]
            res = {"launch_slot": first, "launch_slot_txs": len(ok), "next_2_slots_txs": len(nxt),
                   "bundled": len(ok) >= int(_f("BUNDLE_FLAG_MIN_TX", 4))}
        elif rows:
            res = {"launch_slot": None, "note": "too many txs to see launch slot"}
    except Exception as ex:
        res = {"error": type(ex).__name__}
    _BUNDLE_CACHE[mint] = res
    if len(_BUNDLE_CACHE) > 5000:
        for k in list(_BUNDLE_CACHE)[:2500]:
            _BUNDLE_CACHE.pop(k, None)
    return res


def card_flags(sig: Optional[dict]) -> list:
    if not isinstance(sig, dict):
        return []
    out = [f for f in (sig.get("flags") or []) if f]
    b = sig.get("bundle") or {}
    if b.get("bundled"):
        out.append(f"BUNDLED LAUNCH: {b['launch_slot_txs']} txs in the launch slot (+{b.get('next_2_slots_txs', 0)} next 2 slots)")
    return out


def card_fields(sig: Optional[dict]) -> dict:
    if not isinstance(sig, dict):
        return {}
    q = sig.get("quote") or {}
    return {"token_type": sig.get("token_type"),
            "quote_symbol": q.get("symbol"), "custom_pair": q.get("custom_pair"),
            "bundle": sig.get("bundle"), "wash_volume": sig.get("wash"),
            "xstock": sig.get("xstock"), "stock_meme": sig.get("stock_meme")}


# ── fee sweep ─────────────────────────────────────────────────────────────────
_FEE_SWEEP_RE = re.compile(r"CreatorFeesNotSwept|creator.?fees?.?not.?swept", re.I)
# 6095 pump curve, 6081 pump-amm pool, 6033 pump-fees: from pump-fun SDK docs, not the official
# program README, so they only count when FEE_SWEEP_NUMERIC_CODES=true.
_FEE_SWEEP_CODES = (6095, 6081, 6033)


def classify_swap_error(err) -> Optional[str]:
    t = str(err or "")
    if _FEE_SWEEP_RE.search(t):
        return "fee_sweep_pending"
    if _on("FEE_SWEEP_NUMERIC_CODES", "false"):
        for c in _FEE_SWEEP_CODES:
            if re.search(rf"['\"]?Custom['\"]?\s*:\s*{c}\b|0x{c:x}\b", t):
                return "fee_sweep_pending"
    return None


def note_fee_sweep(mint: str, err) -> None:
    _FEE_SWEEP[mint] = time.time() + _f("FEE_SWEEP_RECHECK_MIN", 30) * 60
    _jsonl("sniper_upgrades.jsonl", {"event": "fee_sweep_pending", "mint": mint, "error": str(err)[:160]})


# ── Jupiter Swap API V2 (flag, default off) with v1 fallback ─────────────────
async def swap_execute(v1: Callable, quote: dict, kw: dict, *, client_fn: Callable, api_key: str,
                       wallet: str, load_keypair: Callable, tx_cls, paper: bool, log: Callable) -> dict:
    res = None
    if _on("JUPITER_SWAP_V2", "false") and not paper and api_key and wallet:
        try:
            res = await _swap_v2(quote, client_fn=client_fn, api_key=api_key, wallet=wallet,
                                 load_keypair=load_keypair, tx_cls=tx_cls, log=log)
        except Exception as ex:
            log(f"swap v2 error, falling back to v1: {type(ex).__name__}: {str(ex)[:120]}")
            res = None
    if isinstance(res, dict) and res.get("no_fallback"):
        pass   # v2 /execute was already called: never re-send through v1 (no double fills)
    elif not res or not res.get("success"):
        if res is not None:
            log(f"swap v2 failed ({str(res.get('error'))[:120]}), falling back to v1")
        res = await v1(quote, **kw)
    try:
        if isinstance(res, dict) and not res.get("success") and classify_swap_error(res.get("error")):
            q = quote or {}
            mint = q.get("outputMint") if q.get("inputMint") == SOL_MINT else q.get("inputMint")
            if mint:
                note_fee_sweep(mint, res.get("error"))
            res["error_class"] = "fee_sweep_pending"
            log(f"fee sweep pending on {str(mint)[:8]}: not a rug, not frozen - recheck in "
                f"{_f('FEE_SWEEP_RECHECK_MIN', 30):.0f}m")
    except Exception:
        pass
    return res


async def _swap_v2(quote: dict, *, client_fn, api_key, wallet, load_keypair, tx_cls, log) -> Optional[dict]:
    import base64
    q = quote or {}
    if not (q.get("inputMint") and q.get("outputMint") and q.get("inAmount")):
        return None
    hdr = {"x-api-key": api_key}
    client = await client_fn()
    r = await client.get("https://api.jup.ag/swap/v2/order", headers=hdr,
                         params={"inputMint": q["inputMint"], "outputMint": q["outputMint"],
                                 "amount": str(q["inAmount"]), "taker": wallet})
    if r.status_code != 200:
        return {"success": False, "error": f"v2_order_{r.status_code}: {r.text[:160]}"}
    o = r.json() or {}
    if not o.get("transaction"):
        return {"success": False, "error": f"v2_order_no_tx: {o.get('errorCode') or o.get('error') or ''}"}
    kp = load_keypair()
    if kp is None:
        return {"success": False, "error": "keypair_load_failed"}
    tx = tx_cls.from_bytes(base64.b64decode(o["transaction"]))
    signed = base64.b64encode(bytes(tx_cls(tx.message, [kp]))).decode("ascii")
    try:
        r2 = await client.post("https://api.jup.ag/swap/v2/execute", headers={**hdr, "Content-Type": "application/json"},
                               json={"signedTransaction": signed, "requestId": o.get("requestId")})
        d = r2.json() if r2.status_code == 200 else {}
    except Exception as ex:
        return {"success": False, "no_fallback": True, "error": f"v2_execute_unknown: {type(ex).__name__}"}
    if d.get("status") == "Success" and d.get("signature"):
        log(f"swap v2 landed {d['signature'][:8]}")
        return {"success": True, "tx_signature": d["signature"], "swap_data": {"v2_order": {k: o.get(k) for k in (
            "inAmount", "outAmount", "router", "priceImpactPct", "requestId")}, "v2_execute": d}, "via": "swap_v2"}
    return {"success": False, "no_fallback": True,
            "error": f"v2_execute: {d.get('status') or r2.status_code} {str(d.get('error') or '')[:120]}"}


# ── Moonshot (Moonit) listener (flag, default off) ───────────────────────────
# Program id from public IDL libraries (AllenHark, yellowstone-vixen parser, Bitquery docs).
# Moonshot's own docs do not print it, so the listener ships OFF: MOONSHOT_LISTENER=true to try it.
# Cost: 1 getSignaturesForAddress + up to MOONSHOT_MAX_TX getTransaction per poll.
# LaunchOnSF: not shipped. No official program id or docs could be verified.
MOONSHOT_PROGRAM = "MoonCVVNZFSYkqNXP6bxHLPL6QQJiMagDL3qcqUQTrG"
_MOON = {"task": None, "seen": set(), "mints": set()}


def ensure_moonshot_listener(rpc: Callable, on_mint: Callable, log: Callable) -> None:
    if not _on("MOONSHOT_LISTENER", "false") or _MOON["task"] is not None:
        return
    import asyncio
    try:
        _MOON["task"] = asyncio.get_running_loop().create_task(_moonshot_loop(rpc, on_mint, log))
        log("moonshot listener started")
    except RuntimeError:
        pass


async def _moonshot_loop(rpc, on_mint, log) -> None:
    import asyncio
    first = True
    while _on("MOONSHOT_LISTENER", "false"):
        try:
            sigs = await rpc("getSignaturesForAddress", [MOONSHOT_PROGRAM, {"limit": 25}])
            rows = [s for s in (sigs if isinstance(sigs, list) else []) if isinstance(s, dict)
                    and s.get("signature") and not s.get("err") and s["signature"] not in _MOON["seen"]]
            for s in rows:
                _MOON["seen"].add(s["signature"])
            if first:          # baseline: don't replay history on boot
                first = False
                rows = []
            for s in rows[: int(_f("MOONSHOT_MAX_TX", 5))]:
                tx = await rpc("getTransaction", [s["signature"], {"encoding": "jsonParsed",
                                                                  "maxSupportedTransactionVersion": 0}])
                meta = (tx or {}).get("meta") or {}
                pre = {b.get("mint") for b in meta.get("preTokenBalances") or []}
                for b in meta.get("postTokenBalances") or []:
                    m = b.get("mint")
                    if m and m not in pre and m not in (SOL_MINT, USDC_MINT, USDT_MINT) and m not in _MOON["mints"]:
                        _MOON["mints"].add(m)
                        _jsonl("moonshot_new.jsonl", {"mint": m, "sig": s["signature"]})
                        try:
                            on_mint(m)
                        except Exception:
                            pass
            if len(_MOON["seen"]) > 20000:
                _MOON["seen"] = set(list(_MOON["seen"])[-5000:])
        except Exception as ex:
            log(f"moonshot listener: {type(ex).__name__}")
        await asyncio.sleep(max(20.0, _f("MOONSHOT_POLL_S", 60)))
    _MOON["task"] = None
