"""Launch-spike gate.

A print that goes from dust to over $100k mcap in a handful of 1m candles
is a coordinated pump or a smart bundle. Those rug. This is a buy veto,
not a sell sensor.

The clock is the birth, pre-bond. A 100k tag after a clean curve, or after
we already bought, is the token pumping. That is not this veto.

Missing candles do not veto. A slow grind through 100k does not veto.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

MCAP_KILL_USD = 100_000.0
BASE_MCAP_USD = 25_000.0
MAX_MINUTES = 10.0
MAX_AGE_MINUTES = 180.0

_DEX = "https://api.dexscreener.com/latest/dex/tokens/"
_GECKO = "https://api.geckoterminal.com/api/v2/networks/solana/pools/"
_UA = "meme-sniper-launch-spike/1.0"


def _get(url: str, timeout: float = 12.0) -> dict | list | None:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            time.sleep(1.5)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8", errors="replace"))
            except Exception:
                return None
        return None
    except Exception:
        return None


def _pair(mint: str) -> dict | None:
    data = _get(_DEX + mint)
    pairs = (data or {}).get("pairs") if isinstance(data, dict) else None
    if not pairs:
        return None
    sol = [p for p in pairs if (p.get("chainId") or "") == "solana"] or list(pairs)

    def liq(p):
        try:
            return float((p.get("liquidity") or {}).get("usd") or 0)
        except (TypeError, ValueError):
            return 0.0

    return max(sol, key=liq)


def _supply(pair: dict) -> float | None:
    try:
        price = float(pair.get("priceUsd") or 0)
        fdv = float(pair.get("fdv") or pair.get("marketCap") or 0)
    except (TypeError, ValueError):
        return None
    if price <= 0 or fdv <= 0:
        return None
    return fdv / price


def _candles(pool: str) -> list[dict]:
    url = f"{_GECKO}{pool}/ohlcv/minute?aggregate=1&limit=180&currency=usd"
    data = _get(url)
    rows = (((data or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    out = []
    for row in rows:
        if not row or len(row) < 5:
            continue
        try:
            out.append({
                "t": int(row[0]),
                "o": float(row[1] or 0),
                "h": float(row[2] or 0),
                "l": float(row[3] or 0),
                "c": float(row[4] or 0),
            })
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda c: c["t"])
    return out


def check_launch_spike(mint: str, pair: dict | None = None) -> dict:
    """Return a verdict dict. block=True means do not buy."""
    out = {
        "ok": False,
        "block": False,
        "reason": "unchecked",
        "minutes_to_100k": None,
        "peak_mcap": None,
        "candles": 0,
        "age_minutes": None,
    }
    if not mint:
        out["reason"] = "no_mint"
        return out
    pair = pair or _pair(mint)
    if not pair:
        out["reason"] = "no_pair"
        return out
    pool = pair.get("pairAddress")
    supply = _supply(pair)
    if not pool or not supply:
        out["reason"] = "no_pool_or_supply"
        return out
    created_ms = pair.get("pairCreatedAt") or 0
    try:
        created_s = float(created_ms) / 1000.0 if float(created_ms) > 1e12 else float(created_ms or 0)
    except (TypeError, ValueError):
        created_s = 0.0
    age_min = ((time.time() - created_s) / 60.0) if created_s else None
    out["age_minutes"] = round(age_min, 1) if age_min is not None else None
    if age_min is not None and age_min > MAX_AGE_MINUTES:
        out["ok"] = True
        out["reason"] = "too_old_for_launch_spike"
        return out

    candles = _candles(pool)
    out["candles"] = len(candles)
    if len(candles) < 2:
        out["reason"] = "no_1m_candles"
        return out

    def mcap(price: float) -> float:
        return price * supply

    peak = max(mcap(c["h"]) for c in candles)
    out["peak_mcap"] = round(peak, 0)
    cross = next((c for c in candles if mcap(c["h"]) >= MCAP_KILL_USD), None)
    if cross is None:
        out["ok"] = True
        out["reason"] = "never_crossed_100k"
        return out

    base = None
    for c in candles:
        if c["t"] > cross["t"]:
            break
        if mcap(c["h"]) < BASE_MCAP_USD:
            base = c
    # first visible candle already over 100k is a missing birth, not a 1-minute spike.
    # post-bond charts often start there. missing candles do not veto.
    if base is None:
        out["ok"] = True
        out["reason"] = "no_base_under_25k"
        out["minutes_to_100k"] = None
        return out
    t0 = base["t"]
    minutes = max(0.0, (cross["t"] - t0) / 60.0)
    # a single candle that opens under the base and tags 100k is 1 minute, not 0
    if minutes < 1.0 and mcap(cross["o"]) < BASE_MCAP_USD and mcap(cross["h"]) >= MCAP_KILL_USD:
        minutes = 1.0
    out["minutes_to_100k"] = round(minutes, 1)
    out["ok"] = True
    if minutes <= MAX_MINUTES:
        out["block"] = True
        out["reason"] = (
            f"launch_spike: ${MCAP_KILL_USD/1000:.0f}k in {minutes:.0f}m "
            f"(cap {MAX_MINUTES:.0f}m). coordinated pump or smart bundle"
        )
    else:
        out["reason"] = "climb_slow_enough"
    return out


if __name__ == "__main__":
    import sys
    mint = sys.argv[1] if len(sys.argv) > 1 else ""
    print(json.dumps(check_launch_spike(mint), indent=2))
