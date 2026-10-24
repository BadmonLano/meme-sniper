"""
scale_in.py — smaller first buy, add later if the pool is intact (v1.0.4).

First leg SCALE_IN_FIRST_SOL (0.05). After SCALE_IN_ADD_AFTER_S (300s) the add leg
(the rest of the planned size) fires only if:
  - the position is still open and not exited/partial-taken,
  - current liquidity >= SCALE_IN_LIQ_KEEP_PCT (80%) of liquidity at entry,
  - price is not below entry by more than SCALE_IN_MAX_DRAWDOWN_PCT (15%).
Missing data = no add (fail safe). Off-switch: SCALE_IN=false.
The 0.1 SOL floor is relaxed ONLY for these two legs; the planned total stays >= floor.
Vault / celeb entries (fixed size) are never split.
"""
from __future__ import annotations

import os
from typing import Optional


def _e(k, d=""):
    v = os.environ.get(k)
    return d if v is None or not str(v).strip() else str(v).strip()


def _f(k, d):
    try:
        return float(_e(k, str(d)))
    except ValueError:
        return float(d)


def enabled() -> bool:
    return _e("SCALE_IN", "true").lower() in ("1", "true", "yes", "on")


def plan(amount_sol: float, sig: dict) -> Optional[dict]:
    """Return {first, add} or None (no split)."""
    sig = sig or {}
    if not enabled() or sig.get("_scale_in_leg"):
        return None
    params = sig.get("params") or {}
    if "fee_vault" in params or "celeb_post" in params or sig.get("celeb_post"):
        return None
    first = _f("SCALE_IN_FIRST_SOL", 0.05)
    if first <= 0 or amount_sol <= first:
        return None
    return {"first": round(first, 6), "add": round(amount_sol - first, 6)}


def add_ok(position: Optional[dict], liq_now: Optional[float], price_now: Optional[float]) -> tuple:
    """(ok, reason) for the add leg."""
    if not position:
        return False, "position closed"
    if position.get("partial_taken") or position.get("exit_reason") or position.get("vault_moved"):
        return False, "exit already started"
    si = position.get("scale_in") or {}
    liq0 = si.get("liq_at_entry")
    if liq0 in (None, 0) or liq_now is None:
        return False, "fail-safe: liquidity unknown"
    keep = _f("SCALE_IN_LIQ_KEEP_PCT", 80)
    if float(liq_now) < float(liq0) * keep / 100:
        return False, f"liquidity {float(liq_now):,.0f} < {keep:.0f}% of entry {float(liq0):,.0f}"
    ep = position.get("entry_price")
    if price_now is None or not ep:
        return False, "fail-safe: price unknown"
    dd = (float(price_now) / float(ep) - 1) * 100
    if dd < -_f("SCALE_IN_MAX_DRAWDOWN_PCT", 15):
        return False, f"price {dd:.1f}% vs entry"
    return True, "pool intact"
