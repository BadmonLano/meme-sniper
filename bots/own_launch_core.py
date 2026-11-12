"""own_launch_core: pure helpers for own-launch tracking (no I/O, no network).

Used by meme_sniper.py (own-launch loop) and test_own_launch.py.
Amounts are RAW token units (ints). Percentages are 0-100.
"""
from __future__ import annotations

import os
from typing import Optional

DEFAULT_LADDER = "2x:25,5x:25,10x:25"


def _f(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def settings_from_env(env: Optional[dict] = None) -> dict:
    e = os.environ if env is None else env
    mode = (e.get("OWN_LAUNCH_MODE") or "hold").strip().lower()
    if mode not in ("hold", "flip"):
        mode = "hold"
    sl_raw = (e.get("OWN_LAUNCH_SL_PCT") or "off").strip().lower()
    sl = None if sl_raw in ("", "off", "none", "0") else _f(sl_raw)
    lock = (e.get("OWN_LAUNCH_LOCK_MODE") or "off").strip().lower()
    if lock not in ("off", "burn"):
        lock = "off"     # "lock" (vesting) is not supported yet
    return {
        "mode": mode,
        "ladder": parse_ladder(e.get("OWN_LAUNCH_TP_LADDER") or DEFAULT_LADDER),
        "ladder_raw": e.get("OWN_LAUNCH_TP_LADDER") or DEFAULT_LADDER,
        "sl_pct": sl,
        "treasury_pct": max(0.0, min(100.0, _f(e.get("OWN_LAUNCH_TREASURY_PCT"), 0.0))),
        "lock_mode": lock,
        "burn_pct": max(0.0, min(100.0, _f(e.get("OWN_LAUNCH_BURN_PCT"), 0.0))),
        "fee_claim_h": max(1.0, _f(e.get("OWN_LAUNCH_FEE_CLAIM_H"), 24.0)),
        "check_s": max(30.0, _f(e.get("OWN_LAUNCH_CHECK_S"), 120.0)),
        "card_inbox_h": max(0.5, _f(e.get("OWN_LAUNCH_CARD_INBOX_H"), 6.0)),
    }


def parse_ladder(s: str) -> list:
    """'2x:25,5x:25,10x:25' -> [(2.0, 25.0), (5.0, 25.0), (10.0, 25.0)].
    Multiples must be > 1 and rising; percents are of the sellable portion and are
    clipped so the running total never passes 100. Bad items are skipped."""
    out, total = [], 0.0
    for part in (s or "").split(","):
        part = part.strip().lower()
        if ":" not in part:
            continue
        m, p = part.split(":", 1)
        mult, pct = _f(m.strip().rstrip("x")), _f(p.strip().rstrip("%"))
        if mult is None or pct is None or mult <= 1 or pct <= 0:
            continue
        if out and mult <= out[-1][0]:
            continue
        pct = min(pct, 100.0 - total)
        if pct <= 0:
            break
        out.append((mult, pct)); total += pct
    return out


def split_amounts(total_raw: int, mode: str, treasury_pct: float) -> tuple:
    """(sellable_raw, kept_raw). flip = nothing kept back."""
    total_raw = max(0, int(total_raw))
    keep = 0 if mode == "flip" else int(total_raw * max(0.0, min(100.0, treasury_pct)) / 100)
    return total_raw - keep, keep


def burn_amount(total_raw: int, lock_mode: str, burn_pct: float) -> int:
    if lock_mode != "burn" or burn_pct <= 0:
        return 0
    return int(max(0, int(total_raw)) * min(100.0, burn_pct) / 100)


def rung_protection(ladder: list, idx: int, sellable_orig: int, current_raw: int) -> Optional[dict]:
    """Protection for rung `idx`: TP at (mult-1)*100 %, selling enough of the CURRENT
    position to land at the ladder's cumulative target. None when the ladder is done."""
    if idx >= len(ladder) or sellable_orig <= 0 or current_raw <= 0:
        return None
    mult, _ = ladder[idx]
    cum = sum(p for _, p in ladder[: idx + 1])
    target_after = sellable_orig * (1 - cum / 100.0)
    sell_pct = (current_raw - target_after) / current_raw * 100.0
    sell_pct = max(1.0, min(100.0, round(sell_pct, 2)))
    return {"take_profit_pct": round((mult - 1) * 100.0, 2), "tp_sell_pct": sell_pct, "rung": idx}


def new_live_launches(results: dict, known: dict) -> list:
    """Rows from launch_results.json that went LIVE with a mint and are not tracked yet."""
    rows = (results or {}).get("results") or {}
    out = []
    for rid, r in rows.items():
        if not isinstance(r, dict):
            continue
        mint = r.get("mint")
        if r.get("mode") == "LIVE" and mint and r.get("signature") and mint not in (known or {}):
            out.append({**r, "id": r.get("id") or rid})
    return out
