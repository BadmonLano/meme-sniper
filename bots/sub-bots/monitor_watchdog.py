"""
monitor_watchdog.py — alert the owner when Sniper's position monitor goes stale
while positions are open (v1.0.4).

Runs two ways:
  - in-process: meme_sniper starts watchdog_loop() as its own supervised task
    (catches a dead/hung monitor task);
  - standalone: `python bots/sub-bots/monitor_watchdog.py` (catches a dead process).
Alerts go through alerts.send_sync (Telegram/Discord/ntfy/email, whatever is set).
Re-alerts at most every WATCHDOG_REALERT_S. One "recovered" note when it comes back.

Env: MONITOR_WATCHDOG (true), WATCHDOG_STALE_S (300), WATCHDOG_TICK_S (60),
WATCHDOG_REALERT_S (1800).
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

COMPONENTS = ("position_monitor", "monitor")


def _f(k, d):
    try:
        return float(os.environ.get(k) or d)
    except ValueError:
        return float(d)


def enabled() -> bool:
    return (os.environ.get("MONITOR_WATCHDOG") or "true").lower() in ("1", "true", "yes", "on")


def _ts(iso: Optional[str]) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(iso)).timestamp()
    except Exception:
        return None


def check(heartbeat: Optional[dict], positions: Optional[dict], now: float,
          stale_s: Optional[float] = None) -> dict:
    """Pure: {stale: bool, age_s, open: int, reason}."""
    stale_s = _f("WATCHDOG_STALE_S", 300) if stale_s is None else stale_s
    open_n = len([k for k, v in (positions or {}).items()
                  if isinstance(v, dict) and not str(k).startswith("_")])
    comps = (heartbeat or {}).get("components") or {}
    last = [t for t in (_ts((comps.get(c) or {}).get("last_update")) for c in COMPONENTS) if t]
    age = (now - max(last)) if last else None
    if open_n == 0:
        return {"stale": False, "age_s": age, "open": 0, "reason": "no open positions"}
    if age is None:
        return {"stale": True, "age_s": None, "open": open_n,
                "reason": "no monitor heartbeat found (fail safe: alert)"}
    st = age > stale_s
    return {"stale": st, "age_s": round(age), "open": open_n,
            "reason": f"monitor last beat {age / 60:.1f} min ago" if st else "ok"}


class Watchdog:
    def __init__(self):
        self.last_alert = 0.0
        self.alerting = False

    def step(self, res: dict, now: float) -> Optional[str]:
        """Return a message to send (or None)."""
        if res.get("stale"):
            if not self.alerting or now - self.last_alert >= _f("WATCHDOG_REALERT_S", 1800):
                self.alerting, self.last_alert = True, now
                return (f"⚠️ Sniper monitor is stale with {res['open']} open position(s): "
                        f"{res['reason']}. Stops and trails are NOT being watched. Check the bot.")
            return None
        if self.alerting:
            self.alerting = False
            return f"✅ Sniper monitor recovered ({res.get('open', 0)} open)."
        return None


def _load(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _send(msg: str) -> None:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import alerts
        alerts.send_sync(msg, source="monitor_watchdog")
    except Exception as e:
        print(f"[watchdog] alert send failed: {type(e).__name__}: {msg}")


def run_once(logs: Path, wd: Watchdog, now: Optional[float] = None, send=_send) -> dict:
    now = time.time() if now is None else now
    res = check(_load(logs / "meme_sniper_heartbeat.json"), _load(logs / "positions.json"), now)
    msg = wd.step(res, now)
    if msg:
        send(msg)
    return res


async def watchdog_loop(logs: Path) -> None:
    import asyncio
    wd = Watchdog()
    while True:
        if enabled():
            try:
                await asyncio.to_thread(run_once, logs, wd)
            except Exception as e:
                print(f"[watchdog] err {type(e).__name__}")
        await asyncio.sleep(_f("WATCHDOG_TICK_S", 60))


if __name__ == "__main__":
    logs = Path(__file__).resolve().parents[2] / "bot_logs"
    wd = Watchdog()
    while True:
        if enabled():
            print(json.dumps(run_once(logs, wd)))
        time.sleep(_f("WATCHDOG_TICK_S", 60))
