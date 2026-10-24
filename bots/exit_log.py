"""
exit_log.py — one exit-type resolver for the ledger AND the autopsy (v1.0.4).

Before: the ledger used exit_reason/trigger/'manual' and the autopsy used
exit_trigger/exit_type/exit_reason/'unknown_exit', so the two disagreed and a
monitor-fired exit sold by the agent often showed as 'manual' / 'unknown_exit'.
Now both call resolve_exit_type(), which also reads the monitor's last trigger.
"""
from __future__ import annotations

from typing import Optional

FALLBACK = "unknown_exit"


def resolve_exit_type(position: Optional[dict] = None, swap_result: Optional[dict] = None,
                      item: Optional[dict] = None) -> str:
    position, swap_result, item = position or {}, swap_result or {}, item or {}
    for v in (position.get("exit_reason"),
              swap_result.get("trigger"),
              swap_result.get("exit_trigger"),
              item.get("exit_trigger"),
              item.get("exit_type"),
              position.get("last_monitor_trigger")):
        if isinstance(v, dict):
            v = v.get("type")
        if v and str(v).strip():
            return str(v).strip()
    return FALLBACK


def pick_autopsy_row(rows: list, mint: str, exit_ts: float, exit_tx: Optional[str],
                     to_ts, window_s: float = 1800) -> Optional[dict]:
    """Match a post-close watch to its autopsy row: exit tx first, then the
    nearest exit time; a lone row for the mint matches inside 6h."""
    cands = [r for r in rows or [] if isinstance(r, dict) and r.get("mint") == mint]
    if exit_tx:
        for r in cands:
            if r.get("exit_tx") == exit_tx:
                return r
    best, bd = None, 1e18
    for r in cands:
        t = r.get("exit_at") or r.get("closed_at") or r.get("timestamp")
        try:
            d = abs(to_ts(t) - float(exit_ts)) if t else 1e17
        except Exception:
            d = 1e17
        if d < bd:
            best, bd = r, d
    if best is None:
        return None
    if bd <= window_s or (len(cands) == 1 and bd <= 6 * 3600):
        return best
    return None
