"""
v107_rules.py - Meme Sniper v1.0.7 rules (from the 6-token replay, Oct 2026).

Every rule has its own env off-switch (default ON). Pure functions where possible so
tests can replay real tokens without network.

 1  TREND_FAST            trending coin holding top-3 for >= 1h -> buy candidate (was 8h only)
 2  CLONE_RUNNER_OVERRIDE a "clone" that is the one actually running passes the clone gate
 3  EXPIRED_CARD_FALLBACK expired agent card -> small buy if rug check is clean, else logged ignore
 4  PARODY_LANE           tickers copying big coins (BTC/LTC/ETH/SOL...) -> alerts only, never buys
 5  X_PROFILE_FILL        X follower count + account age via X_BEARER_TOKEN, cached
 6  TRENDING_TICKER_FIX   trending_track ticker comes from the base side of the pair, and self-heals
 7  BUNDLE_CHECK          bundle % on the card; >25% = smaller size + tighter exits; block only on dumping
    COVERAGE_GECKO        GeckoTerminal Solana trending pools feed the trending tracker (NIO/ETH gap)
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Optional


def _e(k, d=""):
    v = os.environ.get(k)
    return d if v is None or not str(v).strip() else str(v).strip()


def _f(k, d):
    try:
        return float(_e(k, str(d)))
    except ValueError:
        return float(d)


def on(k, default=True) -> bool:
    return _e(k, "true" if default else "false").lower() in ("1", "true", "yes", "on")


# ── 1. fast trending candidate ──────────────────────────────────────────────
def trend_fast(entry: dict, now_ts: Optional[float] = None) -> bool:
    """True when the mint has held rank <= TREND_FAST_TOP_N for >= TREND_FAST_HOURS
    with no scan gap > TREND_FAST_MAX_GAP_MIN inside that run."""
    if not on("TREND_FAST") or not isinstance(entry, dict):
        return False
    top_n = int(_f("TREND_FAST_TOP_N", 3))
    hours = _f("TREND_FAST_HOURS", 1.0)
    max_gap = _f("TREND_FAST_MAX_GAP_MIN", 40) * 60
    min_hits = int(_f("TREND_FAST_MIN_SCANS", 3))
    apps = [a for a in (entry.get("appearances") or []) if isinstance(a, dict) and a.get("ts")]
    if not apps:
        return False
    apps = sorted(apps, key=lambda a: a["ts"])
    run = []
    for a in reversed(apps):          # walk back from latest while still top-N + continuous
        r = a.get("rank")
        if r is None or int(r) > top_n:
            break
        if run and run[-1]["ts"] - a["ts"] > max_gap:
            break
        run.append(a)
    if len(run) < min_hits:
        return False
    if now_ts is not None and now_ts - run[0]["ts"] > max_gap:
        return False                  # latest top-N sighting is stale
    return (run[0]["ts"] - run[-1]["ts"]) / 3600.0 >= hours


# ── 2. clone gate runner override ───────────────────────────────────────────
def miss_book_has(mint: str, path, tail: int = 3000) -> bool:
    try:
        p = Path(path)
        if not p.exists():
            return False
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()[-tail:]
        return any(mint in ln for ln in lines)
    except Exception:
        return False


def clone_override(ctx: dict, br: dict, mint: str, miss_book_path=None) -> Optional[str]:
    """Return a reason string if this 'clone' is actually the runner, else None."""
    if not on("CLONE_RUNNER_OVERRIDE"):
        return None
    ctx, br = ctx or {}, br or {}
    dd = ctx.get("dex_data") or {}
    try:
        mc = float(dd.get("mcap") or ctx.get("mcap") or 0)
    except (TypeError, ValueError):
        mc = 0.0
    floor = _f("CLONE_OVERRIDE_MCAP_USD", 500_000)
    mult = _f("CLONE_OVERRIDE_X_ORIGINAL", 2.0)
    if mc >= floor:
        return f"runner_mcap {int(mc)} >= {int(floor)}"
    canon = br.get("canonical_mint")
    omc = None
    for c in br.get("candidates") or []:
        if isinstance(c, dict) and canon and c.get("mint") == canon:
            try:
                omc = float(c.get("mcap") or 0)
            except (TypeError, ValueError):
                omc = None
    if mc > 0 and omc and mc >= mult * omc:
        return f"runner_vs_original {mc / omc:.1f}x >= {mult}x"
    if miss_book_path and miss_book_has(mint, miss_book_path):
        return "on_miss_book"
    return None


# ── 3. expired agent card fallback ──────────────────────────────────────────
def expired_fallback(packet: dict, now_ts: Optional[float] = None) -> dict:
    """{'buy': bool, 'reason': str, 'signal': dict|None}. Rug check must pass."""
    if not on("EXPIRED_CARD_FALLBACK"):
        return {"buy": False, "reason": "off_switch", "signal": None}
    ctx = (packet or {}).get("context") or {}
    mint = ctx.get("mint")
    if not mint:
        return {"buy": False, "reason": "no_mint", "signal": None}
    rug = (ctx.get("rug_check") or {}).get("smart_check_verdict")
    ok = {"clean"} | ({"caution"} if on("EXPIRED_CARD_FALLBACK_ALLOW_CAUTION", False) else set())
    if rug not in ok:
        return {"buy": False, "reason": f"rug_check_not_clean:{rug}", "signal": None}
    if (ctx.get("bundle_check") or {}).get("action") == "block":
        return {"buy": False, "reason": "bundle_dumping", "signal": None}
    now_ts = now_ts or time.time()
    sol = _f("EXPIRED_CARD_FALLBACK_SOL", 0.05)
    sig = {"signal_id": f"v107_ttl_fallback_{mint[:8]}_{int(now_ts)}", "action": "buy",
           "mint": mint, "ticker": ctx.get("ticker") or "?", "amount_sol": sol,
           "requested_at_ts": now_ts, "_scale_in_leg": "first_only",
           "source": "v107_expired_card_fallback", "params": {}, "_v107_small": True,
           "reasoning": f"agent card expired with no decision; rug check {rug}; small fallback buy"}
    return {"buy": True, "reason": f"rug_{rug}", "signal": sig}


def append_signal(signals_file, sig: dict) -> None:
    """read-append-write onto agent_signals.json ({'signals': [...]} or list)."""
    p = Path(signals_file)
    data = {"signals": []}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8") or "{}") or {"signals": []}
        except Exception:
            data = {"signals": []}
    if isinstance(data, list):
        data.append(sig)
    else:
        data.setdefault("signals", []).append(sig)
    tmp = p.with_suffix(".v107tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, p)


# ── 4. parody-ticker lane ───────────────────────────────────────────────────
MAJORS = {"BTC", "ETH", "SOL", "LTC", "XRP", "DOGE", "BNB", "ADA", "TRX", "DOT", "AVAX",
          "LINK", "SHIB", "PEPE", "SUI", "TON", "XLM", "BCH", "HYPE", "USDT", "USDC", "WIF",
          "BONK", "NIO", "TSLA", "NVDA", "AAPL", "SPX", "SPY"}


def parody_match(ticker: str, mint: str = "") -> Optional[str]:
    if not on("PARODY_LANE") or not ticker:
        return None
    extra = {t.strip().upper() for t in _e("PARODY_EXTRA_TICKERS", "").split(",") if t.strip()}
    t = ticker.strip().lstrip("$").upper()
    if t in (MAJORS | extra) and (not mint or mint.endswith("pump") or len(mint) > 30):
        return t
    return None


def parody_alert(alerts_file, mint: str, ticker: str, rank=None, mcap=None, source="") -> bool:
    """Alert only (never a buy). Dedup per mint per PARODY_DEDUP_H hours."""
    m = parody_match(ticker, mint)
    if not m:
        return False
    p = Path(alerts_file)
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        data = {}
    rows = data.setdefault("alerts", {})
    now = time.time()
    prev = rows.get(mint) or {}
    if now - float(prev.get("ts") or 0) < _f("PARODY_DEDUP_H", 6) * 3600:
        return False
    rows[mint] = {"ts": now, "ticker": ticker, "copies": m, "rank": rank, "mcap": mcap,
                  "source": source, "decision": "alert_only"}
    data["_doctrine"] = ("Parody tickers riding a big coin's name (5 of 6 Oct replay runners). "
                         "Alert lane only - Sniper never buys from here.")
    data["updated_at"] = now
    tmp = p.with_suffix(".v107tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return True


# ── 5. X profile fill ───────────────────────────────────────────────────────
def _bearer() -> str:
    for k in ("X_BEARER_TOKEN", "X_Bearer_Token", "TWITTER_BEARER_TOKEN"):
        v = os.environ.get(k)
        if v:
            return v.strip()
    return ""


def x_profile(handle: Optional[str], cache_file, fetch=None, now_ts: Optional[float] = None) -> dict:
    """{'followers': int|None, 'age_days': int|None, 'verified': bool|None, 'source': str}.
    Cache hit 24h (miss 6h). Hourly cap X_PROFILE_MAX_PER_HOUR. Never logs the token."""
    out = {"followers": None, "age_days": None, "verified": None, "source": "none"}
    if not on("X_PROFILE_FILL") or not handle:
        return out
    h = handle.strip().lstrip("@").lower()
    if not h or h in ("i", "home", "search") or len(h) > 15:
        return out
    now_ts = now_ts or time.time()
    p = Path(cache_file)
    try:
        cache = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        cache = {}
    row = (cache.get("users") or {}).get(h)
    if row:
        ttl = 86400 if row.get("followers") is not None else 6 * 3600
        if now_ts - float(row.get("ts") or 0) < ttl:
            r = dict(row); r["source"] = "cache"
            r["age_days"] = int((now_ts - row["created_ts"]) / 86400) if row.get("created_ts") else None
            r.pop("ts", None); r.pop("created_ts", None)
            return r
    calls = [t for t in cache.get("calls", []) if now_ts - t < 3600]
    if len(calls) >= _f("X_PROFILE_MAX_PER_HOUR", 60):
        out["source"] = "budget_capped"
        return out
    tok = _bearer()
    if not tok and fetch is None:
        out["source"] = "no_bearer"
        return out
    calls.append(now_ts)
    try:
        if fetch is None:
            req = urllib.request.Request(
                f"https://api.twitter.com/2/users/by/username/{h}?user.fields=public_metrics,created_at,verified",
                headers={"Authorization": "Bearer " + tok, "User-Agent": "meme-sniper"})
            body = json.load(urllib.request.urlopen(req, timeout=10))
        else:
            body = fetch(h)
        d = (body or {}).get("data") or {}
        fol = (d.get("public_metrics") or {}).get("followers_count")
        cts = None
        if d.get("created_at"):
            from datetime import datetime
            cts = datetime.fromisoformat(d["created_at"].replace("Z", "+00:00")).timestamp()
        row = {"ts": now_ts, "followers": fol, "created_ts": cts, "verified": d.get("verified")}
        out = {"followers": fol, "age_days": int((now_ts - cts) / 86400) if cts else None,
               "verified": d.get("verified"), "source": "x_api"}
    except Exception as ex:
        row = {"ts": now_ts, "followers": None, "created_ts": None, "verified": None,
               "err": type(ex).__name__}
        out["source"] = f"error:{type(ex).__name__}"
    cache.setdefault("users", {})[h] = row
    cache["calls"] = calls
    try:
        tmp = p.with_suffix(".v107tmp")
        tmp.write_text(json.dumps(cache), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass
    return out


# ── 6. trending ticker ──────────────────────────────────────────────────────
def base_ticker(pairs: list, mint: str) -> str:
    """Symbol of `mint` from DexScreener pairs, using ONLY base-side pairs."""
    for p in sorted([p for p in pairs or [] if ((p.get("baseToken") or {}).get("address") == mint)],
                    key=lambda p: -((p.get("liquidity") or {}).get("usd") or 0)):
        s = (p.get("baseToken") or {}).get("symbol")
        if s:
            return s
    for p in pairs or []:          # mint only appears as quote: take the quote symbol
        q = p.get("quoteToken") or {}
        if q.get("address") == mint and q.get("symbol"):
            return q["symbol"]
    return "?"


def heal_ticker(entry: dict, ticker: str) -> bool:
    """Overwrite a stale/mislabelled ticker with a fresh base-side one."""
    if not on("TRENDING_TICKER_FIX") or not ticker or ticker == "?":
        return False
    if entry.get("ticker") != ticker:
        entry["ticker_prev"] = entry.get("ticker")
        entry["ticker"] = ticker
        return True
    return False


# ── 7. bundle check ─────────────────────────────────────────────────────────
SUPPLY = 1e9
PUMP_MIGRATOR = "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"


def _signer(tx):
    ak = (tx.get("transaction") or {}).get("message", {}).get("accountKeys") or []
    if not ak:
        return None
    return ak[0]["pubkey"] if isinstance(ak[0], dict) else ak[0]


def analyze_bundle(txs: list, mint: str, bundle_slots: int = 1) -> dict:
    """From the first N full txs (asc) of a mint: dev %, same/next-slot bundle %,
    how much of the bundle has already been sold, seconds to bond (if seen)."""
    if not txs:
        return {"ok": False, "reason": "no_txs"}
    t0 = txs[0]
    slot0, bt0, dev = t0.get("slot"), t0.get("blockTime"), _signer(t0)
    bought = defaultdict(float); sold = defaultdict(float); first = {}; bond_s = None
    for tx in txs:
        meta = tx.get("meta") or {}
        if meta.get("err"):
            continue
        s = _signer(tx)
        if s == PUMP_MIGRATOR and bond_s is None and bt0 and tx.get("blockTime"):
            bond_s = tx["blockTime"] - bt0
        d = defaultdict(float)
        for b in meta.get("preTokenBalances") or []:
            if b.get("mint") == mint:
                d[b.get("owner")] -= float((b.get("uiTokenAmount") or {}).get("uiAmount") or 0)
        for b in meta.get("postTokenBalances") or []:
            if b.get("mint") == mint:
                d[b.get("owner")] += float((b.get("uiTokenAmount") or {}).get("uiAmount") or 0)
        for o, v in d.items():
            if o not in (s, dev):
                continue
            if v > 0:
                bought[o] += v; first.setdefault(o, tx.get("slot"))
            elif v < 0 and o in first:
                sold[o] += -v
    bundle = [o for o, sl in first.items() if sl is not None and slot0 is not None and sl <= slot0 + bundle_slots]
    btot = sum(bought[o] for o in bundle)
    return {"ok": True, "dev": dev, "dev_pct": round(bought.get(dev, 0) / SUPPLY * 100, 2),
            "bundle_wallets": len(bundle), "bundle_pct": round(btot / SUPPLY * 100, 2),
            "bundle_sold_pct": round(sum(sold[o] for o in bundle) / btot * 100, 1) if btot else 0.0,
            "bond_seconds": bond_s, "span_s": (txs[-1].get("blockTime") or 0) - (bt0 or 0),
            "wallets": bundle[:10]}


def bundle_decision(a: dict, still_held_pct: Optional[float] = None,
                    price_drawdown_pct: Optional[float] = None) -> dict:
    """normal | reduce | block. Default never hard-blocks on bundle size alone:
    the Oct replay (BTC 41%, CATTLEAXE 28%, REMUS 56%) all kept running after bond.
    Block only on a clear rug signal: bundle wallets dumping into a falling chart."""
    out = {"action": "normal", "size_mult": 1.0, "exit_overrides": {}, "flag": None}
    if not on("BUNDLE_CHECK") or not a or not a.get("ok"):
        return out
    bp = float(a.get("bundle_pct") or 0) + (0 if a.get("dev") in (a.get("wallets") or []) else float(a.get("dev_pct") or 0))
    out["flag"] = f"bundle {bp:.0f}% (dev {a.get('dev_pct')}%, {a.get('bundle_wallets')} wallets)"
    out["bundle_pct"] = round(bp, 2)
    dump_pct = _f("BUNDLE_BLOCK_SOLD_PCT", 50)
    dump_dd = _f("BUNDLE_BLOCK_DRAWDOWN_PCT", 40)
    sold = float(a.get("bundle_sold_pct") or 0)
    if still_held_pct is not None:
        sold = max(sold, 100 - float(still_held_pct))
    if (bp >= _f("BUNDLE_REDUCE_PCT", 25) and sold >= dump_pct
            and price_drawdown_pct is not None and price_drawdown_pct >= dump_dd
            and on("BUNDLE_BLOCK_ON_DUMP")):
        out.update(action="block", size_mult=0.0,
                   reason=f"bundle wallets sold {sold:.0f}% into a {price_drawdown_pct:.0f}% drawdown")
        return out
    if bp >= _f("BUNDLE_REDUCE_PCT", 25):
        out.update(action="reduce", size_mult=_f("BUNDLE_SIZE_MULT", 0.5),
                   exit_overrides={"stop_loss_pct": _f("BUNDLE_STOP_LOSS_PCT", 15),
                                   "trail_giveback_pts": _f("BUNDLE_TRAIL_GIVEBACK_PTS", 10)},
                   reason=f"bundle {bp:.0f}% >= {_f('BUNDLE_REDUCE_PCT', 25):.0f}%: smaller size, tighter exits")
    return out


_BUNDLE_CACHE: dict = {}


async def bundle_check(mint: str, helius_rpc, price_drawdown_pct: Optional[float] = None) -> dict:
    """1 Helius call (getTransactionsForAddress asc, 100 txs) per mint, cached 6h."""
    if not on("BUNDLE_CHECK"):
        return {"action": "normal", "size_mult": 1.0, "exit_overrides": {}, "flag": None}
    c = _BUNDLE_CACHE.get(mint)
    if c and time.time() - c[0] < 6 * 3600:
        a = c[1]
    else:
        try:
            res = await helius_rpc("getTransactionsForAddress", [mint, {
                "transactionDetails": "full", "sortOrder": "asc", "limit": 100,
                "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])
            txs = (res or {}).get("data") if isinstance(res, dict) else None
            a = analyze_bundle(txs or [], mint)
        except Exception as ex:
            a = {"ok": False, "reason": f"error:{type(ex).__name__}"}
        _BUNDLE_CACHE[mint] = (time.time(), a)
    d = bundle_decision(a, None, price_drawdown_pct)
    d["analysis"] = {k: v for k, v in a.items() if k != "wallets"}
    return d


# ── coverage: GeckoTerminal trending pools ──────────────────────────────────
def gecko_trending(fetch=None) -> list:
    """[{tokenAddress, rank, symbol, _source}] for pump.fun mints in GT Solana trending."""
    if not on("COVERAGE_GECKO"):
        return []
    try:
        if fetch is None:
            req = urllib.request.Request("https://api.geckoterminal.com/api/v2/networks/solana/trending_pools",
                                         headers={"Accept": "application/json", "User-Agent": "meme-sniper"})
            body = json.load(urllib.request.urlopen(req, timeout=15))
        else:
            body = fetch()
    except Exception:
        return []
    out, seen = [], set()
    for p in (body or {}).get("data") or []:
        bid = (((p.get("relationships") or {}).get("base_token") or {}).get("data") or {}).get("id") or ""
        m = bid.split("_", 1)[-1]
        if not m.endswith("pump") or m in seen:
            continue
        seen.add(m)
        name = ((p.get("attributes") or {}).get("name") or "").split("/")[0].strip()
        out.append({"tokenAddress": m, "rank": len(out) + 1, "symbol": name, "_source": "gecko_trending"})
    return out[: int(_f("COVERAGE_GECKO_TOP_N", 10))]
