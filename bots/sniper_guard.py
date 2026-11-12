"""sniper_guard.py - user settings + safety floors for meme_sniper (Oct 23 2026).

Every behavior has an env kill switch. Never raises into the caller.

  TRADING_HOURS          "" = always on. e.g. "09:00-23:00" (wraps past midnight ok)
  TRADING_TZ             default America/New_York
  LOSS_STREAK_PAUSE      3   losses in a row -> pause buys (0 = off)
  LOSS_STREAK_PAUSE_HOURS 2
  MAX_OPEN_POSITIONS     3   (0 = off)
  SIZE_HALVE_AFTER_LOSSES 2  (0 = off)
  RUG_FAIL_CLOSED        true  4+ rug layers erroring = block
  RUG_FAIL_CLOSED_MIN_ERRORS 4
  RECLAIM_DEV_FAIL_CLOSED true  unreadable dev holdings = no second-wind ping
  CANDIDATE_FLOOR        true
  CANDIDATE_MIN_LIQ_USD  10000
  SECOND_WIND_V2         true  true peak + base checks + plan + scoring
  SECOND_WIND_MAX_OFF_PEAK_PCT 80
  SECOND_WIND_BASE_RANGE_PCT   30
  SECOND_WIND_SCORE      true
  PEAK_SANITY            true
  PEAK_SANITY_MAX_X      1000
"""
from __future__ import annotations

import json
import os
import time
import asyncio
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

_LOGS: Optional[Path] = None
_LOG: Callable = lambda *a, **k: None


def init(bot_logs, log_fn: Callable = None) -> None:
    global _LOGS, _LOG
    _LOGS = Path(bot_logs)
    if log_fn:
        _LOG = log_fn


def _e(k, d=""):
    v = os.getenv(k)
    if v is not None:   # tolerate inline '#' comments: 'KEY=0  # note' -> '0', 'KEY=  # note' -> ''
        v = "" if str(v).lstrip().startswith("#") else str(v).split(" #")[0].split("\t#")[0]
    return d if v is None or str(v).strip() == "" else str(v).strip()


def _on(k, d="true"):
    return _e(k, d).lower() in ("1", "true", "yes", "on")


def _f(k, d):
    try:
        return float(_e(k, str(d)))
    except Exception:
        return float(d)


def _jsonl(name, rec):
    if not _LOGS:
        return
    try:
        _LOGS.mkdir(parents=True, exist_ok=True)
        with open(_LOGS / name, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass


def _num(x):
    try:
        return float(x)
    except Exception:
        return None


# ---------- 5. trading window ----------
def in_trading_window(now: Optional[datetime] = None) -> tuple:
    # v1.0.16: ACTIVE_HOURS / ACTIVE_TZ / ACTIVE_DAYS (bots/active_hours.py) is the loop's window
    # for new buys and new cards. TRADING_HOURS below still applies on top (both must allow).
    try:
        import active_hours as _ah
        _ok, _why = _ah.in_active_window(now)
        if not _ok:
            return False, _why
    except Exception:
        pass
    spec = _e("TRADING_HOURS", "")
    if not spec:
        return True, "always on"
    try:
        tz = ZoneInfo(_e("TRADING_TZ", "America/New_York")) if ZoneInfo else None
        n = now or datetime.now(tz)
        if tz and n.tzinfo is not None:
            n = n.astimezone(tz)
        a, b = [s.strip() for s in spec.split("-", 1)]
        ah, am = [int(x) for x in a.split(":")]
        bh, bm = [int(x) for x in b.split(":")]
        cur, start, end = n.hour * 60 + n.minute, ah * 60 + am, bh * 60 + bm
        ok = (start <= cur < end) if start <= end else (cur >= start or cur < end)
        return ok, f"TRADING_HOURS {spec} {_e('TRADING_TZ', 'America/New_York')}"
    except Exception:
        return True, f"TRADING_HOURS '{spec}' unreadable, ignored"


# ---------- 5. loss streak / size ----------
def loss_streak(sells: list) -> tuple:
    """Consecutive losing closes, newest first. Returns (count, last_loss_ts)."""
    rows = [r for r in (sells or []) if isinstance(r, dict) and r.get("pnl_sol") is not None]
    def _ts(r):
        for k in ("ts_unix", "ts", "timestamp"):
            v = r.get(k)
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, str):
                try:
                    return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
                except Exception:
                    pass
        return 0.0
    rows.sort(key=_ts, reverse=True)
    n, last = 0, 0.0
    for r in rows:
        if float(r.get("pnl_sol") or 0) < 0:
            n += 1
            last = last or _ts(r)
        else:
            break
    return n, last


def size_multiplier(sells: list) -> float:
    k = int(_f("SIZE_HALVE_AFTER_LOSSES", 2))
    if k <= 0:
        return 1.0
    n, _ = loss_streak(sells)
    return 0.5 if n >= k else 1.0


def extra_prebuy(open_positions: int, sells: list, is_owner_override: bool = False) -> Optional[tuple]:
    ok, why = in_trading_window()
    if not ok:
        return ("outside_trading_hours", why)
    lim = int(_f("LOSS_STREAK_PAUSE", 3))
    if lim > 0:
        n, last = loss_streak(sells)
        hrs = _f("LOSS_STREAK_PAUSE_HOURS", 2)
        if n >= lim and last and (time.time() - last) < hrs * 3600:
            left = (hrs * 3600 - (time.time() - last)) / 60
            return ("loss_streak_pause", f"{n} losses in a row, paused {left:.0f} more min (LOSS_STREAK_PAUSE {lim})")
    mx = int(_f("MAX_OPEN_POSITIONS", 3))
    if mx > 0 and open_positions >= mx:
        return ("max_open_positions", f"{open_positions} open >= MAX_OPEN_POSITIONS {mx}")
    return None


# ---------- 2. rug fail closed ----------
def rug_fail_closed(layers: dict) -> bool:
    if not _on("RUG_FAIL_CLOSED", "true"):
        return False
    errs = sum(1 for v in (layers or {}).values() if v == "error")
    return errs >= int(_f("RUG_FAIL_CLOSED_MIN_ERRORS", 4))


def reclaim_dev_fail_closed() -> bool:
    return _on("RECLAIM_DEV_FAIL_CLOSED", "true")


# ---------- 3. candidate floor ----------
def _walk(o, depth=0):
    if depth > 6:
        return
    if isinstance(o, dict):
        for k, v in o.items():
            yield k, v
            yield from _walk(v, depth + 1)
    elif isinstance(o, list):
        for v in o[:50]:
            yield from _walk(v, depth + 1)


def candidate_floor(packet: dict) -> Optional[str]:
    """Reason string to hold the card back, or None. Only for NEW cards."""
    if not _on("CANDIDATE_FLOOR", "true"):
        return None
    try:
        ctx = packet.get("context") or {}
        dex = ctx.get("dex_data") or {}
        liq = _num(dex.get("liquidity_usd"))
        floor = _f("CANDIDATE_MIN_LIQ_USD", 10000)
        if floor > 0 and (liq is None or liq < floor):
            return f"liquidity ${liq or 0:,.0f} < ${floor:,.0f}"
        v24 = _num(dex.get("volume_24h")) or 0
        if liq and _on("WASH_CHECK", "true") and v24 / liq >= _f("WASH_VOL_LIQ_RATIO", 40):
            return f"wash volume: 24h vol {v24 / liq:.0f}x liquidity"
        for k, v in _walk(packet):
            if k in ("wash", "wash_volume") and v:
                return f"wash volume flag: {str(v)[:80]}"
            if k == "bundled" and v is True:
                return "bundled launch"
            if isinstance(v, str) and (v.startswith("WASH VOLUME?") or v.startswith("BUNDLED LAUNCH")):
                return v[:100]
        rc = ctx.get("rug_check") or packet.get("rug_check") or {}
        if isinstance(rc, dict) and (_num(rc.get("bundle_score")) or 0) >= 85:
            return f"bundled launch (bundle_score {rc.get('bundle_score')})"
    except Exception:
        return None
    return None


# ---------- 4. second wind ----------
def _get_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "meme-sniper/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


_OHLCV_CACHE: dict = {}


async def fetch_hourly(pool: str) -> list:
    """Free GeckoTerminal hourly candles [ts,o,h,l,c,v] oldest first. [] on failure."""
    if not pool:
        return []
    c = _OHLCV_CACHE.get(pool)
    if c and time.time() - c[0] < 900:
        return c[1]
    try:
        url = f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool}/ohlcv/hour?aggregate=1&limit=168"
        d = await asyncio.to_thread(_get_json, url)
        rows = (((d or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        rows = sorted([r for r in rows if isinstance(r, list) and len(r) >= 6], key=lambda r: r[0])
    except Exception:
        rows = []
    _OHLCV_CACHE[pool] = (time.time(), rows)
    if len(_OHLCV_CACHE) > 500:
        _OHLCV_CACHE.clear()
    return rows


def second_wind_check(candles: list, price_now: float, seen_peak_price: float = 0) -> dict:
    """True peak from history, base 1-3h inside range with volume dry-up then return.
    Returns {ok, why, peak_price, base_low, base_high, off_peak_pct}."""
    out = {"ok": False, "why": "", "peak_price": None, "base_low": None, "base_high": None, "off_peak_pct": None}
    if not candles or len(candles) < 6 or not price_now:
        out["why"] = "no price history"
        return out
    highs = [float(r[2]) for r in candles]
    peak = max(max(highs), float(seen_peak_price or 0))
    out["peak_price"] = peak
    off = (1 - price_now / peak) * 100 if peak else 0
    out["off_peak_pct"] = round(off, 1)
    if off > _f("SECOND_WIND_MAX_OFF_PEAK_PCT", 80):
        out["why"] = f"{off:.0f}% off true peak (> {_f('SECOND_WIND_MAX_OFF_PEAK_PCT', 80):.0f}%)"
        return out
    rng = _f("SECOND_WIND_BASE_RANGE_PCT", 30) / 100
    last = candles[-1]
    prior = candles[:-1]
    best = None
    for n in (3, 2, 1):
        if len(prior) < n + 3:
            continue
        base = prior[-n:]
        lo, hi = min(float(r[3]) for r in base), max(float(r[2]) for r in base)
        if lo <= 0 or (hi - lo) / lo > rng:
            continue
        pre = prior[-(n + 6):-n] or prior[:-n]
        pre_v = sum(float(r[5]) for r in pre) / max(1, len(pre))
        base_v = sum(float(r[5]) for r in base) / n
        if pre_v <= 0 or base_v > pre_v * 0.6:
            continue
        if float(last[5]) < base_v * 1.5:
            continue
        best = (lo, hi, n)
        break
    if not best:
        out["why"] = "no 1-3h base with volume dry-up then return"
        return out
    out.update(ok=True, why=f"{best[2]}h base, vol dried then returned", base_low=best[0], base_high=best[1])
    return out


def trade_plan(base_low: float, base_high: float, peak: float, price_now: float, mcap_now: float) -> dict:
    """Entry zone, stop under base low, target old peak. Prices + mcap equivalents."""
    if not (base_low and base_high and price_now and mcap_now):
        return {}
    k = mcap_now / price_now
    stop = base_low * 0.95
    return {
        "entry_zone_mcap": [round(base_low * k), round(base_high * 1.05 * k)],
        "stop_mcap": round(stop * k),
        "target_mcap": round(peak * k) if peak else None,
        "reward_risk": round((peak - price_now) / max(1e-12, price_now - stop), 2) if peak and price_now > stop else None,
        "note": "watch plan, not a buy order",
    }


def community_from_candles(candles: list) -> dict:
    """Uses COMMUNITY_FORMATION_PRICE_RANGE_PCT / MIN_CANDLES_AT_BOTTOM settings."""
    rng = _f("COMMUNITY_FORMATION_PRICE_RANGE_PCT", 0.30)
    need = int(_f("COMMUNITY_FORMATION_MIN_CANDLES_AT_BOTTOM", 6))
    if not candles or len(candles) < need:
        return {"bottom_candles": 0, "sideways": False}
    tail = candles[-need:]
    lo, hi = min(float(r[3]) for r in tail), max(float(r[2]) for r in tail)
    side = lo > 0 and (hi - lo) / lo <= rng
    return {"bottom_candles": need if side else 0, "sideways": side, "range_pct": round((hi - lo) / lo * 100, 1) if lo else None}


# ---------- 6. ping scoring ----------
_PING_STATE = "second_wind_ping_state.json"


def record_ping(mint: str, ticker: str, mcap: float, plan: dict) -> None:
    if not (_LOGS and _on("SECOND_WIND_SCORE", "true")):
        return
    rec = {"mint": mint, "ticker": ticker, "ping_ts": time.time(), "ping_mcap": mcap, "plan": plan, "scored": {}}
    _jsonl("second_wind_pings.jsonl", rec)
    try:
        p = _LOGS / _PING_STATE
        st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        st[f"{mint}:{int(rec['ping_ts'])}"] = rec
        p.write_text(json.dumps(st, indent=1), encoding="utf-8")
    except Exception:
        pass


async def score_due(fetch_mcap) -> int:
    """fetch_mcap(mint) -> async float|None. Scores pings at +1h/+6h/+24h."""
    if not (_LOGS and _on("SECOND_WIND_SCORE", "true")):
        return 0
    p = _LOGS / _PING_STATE
    try:
        st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return 0
    done, now = 0, time.time()
    for key, rec in list(st.items()):
        for label, sec in (("1h", 3600), ("6h", 21600), ("24h", 86400)):
            if label in rec["scored"] or now - rec["ping_ts"] < sec:
                continue
            try:
                m = await fetch_mcap(rec["mint"])
            except Exception:
                m = None
            if not m:
                continue
            plan = rec.get("plan") or {}
            ret = (m / rec["ping_mcap"] - 1) * 100 if rec.get("ping_mcap") else None
            hit_t = bool(plan.get("target_mcap") and m >= plan["target_mcap"])
            hit_s = bool(plan.get("stop_mcap") and m <= plan["stop_mcap"])
            rec["scored"][label] = {"mcap": m, "ret_pct": round(ret, 1) if ret is not None else None,
                                    "hit_target": hit_t, "hit_stop": hit_s}
            _jsonl("second_wind_scores.jsonl", {"mint": rec["mint"], "ticker": rec["ticker"], "horizon": label,
                                                "ping_mcap": rec["ping_mcap"], **rec["scored"][label],
                                                "ts": now})
            done += 1
        if len(rec["scored"]) >= 3 or now - rec["ping_ts"] > 3 * 86400:
            st.pop(key, None)
    try:
        p.write_text(json.dumps(st, indent=1), encoding="utf-8")
    except Exception:
        pass
    return done


# ---------- 4. peak sanity ----------
def peak_sane(row: dict) -> bool:
    if not _on("PEAK_SANITY", "true") or not isinstance(row, dict):
        return True
    pm = _num(row.get("peak_multiple"))
    if pm is not None and pm > _f("PEAK_SANITY_MAX_X", 1000):
        return False
    pk = _num(row.get("peak_mcap"))
    if pk is not None and pk > _f("PEAK_SANITY_MAX_MCAP", 5e9):
        return False
    return True
