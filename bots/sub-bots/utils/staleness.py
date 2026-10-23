"""
staleness.py — Universal staleness helper for JSON consumers.

Every bot that reads JSON files written by other bots should use load_json_with_staleness
instead of raw json.load. This injects a _meta block with mtime/age/is_stale/source_path
and fires rate-limited Telegram alerts when files go stale.

Usage:
    from utils.staleness import load_json_with_staleness, is_stale
    
    data = load_json_with_staleness("bot_logs/wallet_signal.json", max_age_seconds=1800)
    if data is None or is_stale(data):
        return  # don't trust this data
    
    # Use data normally
    signal = data.get("signal")

Why:
    - Pipeline_watchdog catches dead writers but consumers still read stale data
      between watchdog ticks. Staleness sentinels block consumption mid-tick.
    - Forensic report (Apr 2026): 5 pipelines silently died between Apr 11-20,
      consumers kept reading stale data unaware. This prevents that pattern.
"""
from __future__ import annotations

import os
import time
import json
from pathlib import Path
from typing import Any, Optional


DEFAULT_MAX_AGE_RUNTIME = 1800   # 30 min for runtime files
DEFAULT_MAX_AGE_LIBRARY = 86400  # 24h for library/reference files


# Rate-limit Telegram alerts: don't re-alert the same path within 30 min
_STALE_ALERT_COOLDOWN = {}
_ALERT_COOLDOWN_SECONDS = 1800


def load_json_with_staleness(
    path: str | Path,
    max_age_seconds: int = DEFAULT_MAX_AGE_RUNTIME,
    default: Any = None,
    alert_on_stale: bool = True,
) -> Optional[dict | list]:
    """Load JSON file with staleness checking.

    Returns the loaded data with `_meta` injected (when data is dict):
    {
    ...original data...,
    "_meta": {
    "mtime": float,
    "age_seconds": float,
    "is_stale": bool,
    "max_age_seconds": int,
    "source_path": str
    }
    }

    For list data, _meta is NOT injected (lists are immutable in JSON terms).
    Use the helper functions get_age_seconds() / is_path_stale() for those.

    Args:
    path: file path
    max_age_seconds: threshold above which file is "stale"
    default: returned if file doesn't exist
    alert_on_stale: fire Telegram alert if stale (rate-limited)

    Returns:
    loaded data (dict or list) or default if missing.
    """
    p = Path(path)
    
    if not p.exists():
        return default
    
    try:
        mtime = p.stat().st_mtime
        age = time.time() - mtime
        is_stale_now = age > max_age_seconds
        
        with open(p, encoding="utf-8-sig") as f:
            data = json.load(f)
        
        if isinstance(data, dict):
            data["_meta"] = {
                "mtime": mtime,
                "age_seconds": round(age, 2),
                "is_stale": is_stale_now,
                "max_age_seconds": max_age_seconds,
                "source_path": str(p),
            }
        
        if is_stale_now and alert_on_stale:
            _alert_stale_file(str(p), age, max_age_seconds)
        
        return data
    except json.JSONDecodeError as e:
        print(f"[staleness] JSON parse error in {p}: {e}")
        return default
    except Exception as e:
        print(f"[staleness] error loading {p}: {e}")
        return default


def is_stale(data: Any) -> bool:
    """
    Check if data loaded with load_json_with_staleness is stale.
    Returns True if data is None, not a dict, missing _meta, or _meta says stale.
    """
    if data is None:
        return True
    if not isinstance(data, dict):
        # Lists / scalars don't carry _meta — caller should use is_path_stale instead
        return False
    return data.get("_meta", {}).get("is_stale", False)


def get_age_seconds(path: str | Path) -> Optional[float]:
    """Get the age in seconds of a file, or None if missing."""
    p = Path(path)
    if not p.exists():
        return None
    return time.time() - p.stat().st_mtime


def is_path_stale(path: str | Path, max_age_seconds: int = DEFAULT_MAX_AGE_RUNTIME) -> bool:
    """Check if a file is stale without loading it."""
    age = get_age_seconds(path)
    if age is None:
        return True  # missing = stale
    return age > max_age_seconds


def _alert_stale_file(path: str, age_seconds: float, max_age: int) -> None:
    """Rate-limited Telegram alert when a critical file is stale."""
    now = time.time()
    last = _STALE_ALERT_COOLDOWN.get(path, 0)
    
    if now - last < _ALERT_COOLDOWN_SECONDS:
        return
    
    _STALE_ALERT_COOLDOWN[path] = now
    age_min = age_seconds / 60
    max_age_min = max_age / 60
    msg = f"⚠️ Stale file: {os.path.basename(path)} | {age_min:.1f}min old (max {max_age_min:.0f}min)"
    
    # Defer-import to avoid circular deps with telegram alerts
    try:
        # First try the existing telegram helper if imported elsewhere
        import sys
        sniper_module = sys.modules.get("meme_sniper")
        if sniper_module and hasattr(sniper_module, "send_telegram_sync"):
            sniper_module.send_telegram_sync(msg)
            return
    except Exception:
        pass
    
    # Fallback: console only
    print(f"[staleness] {msg}")


# Convenience: standard max_age for common file types
COMMON_MAX_AGES = {
    # Runtime files (frequently written)
    "wallet_signal.json": 1800,
    "wallet_history.json": 3600,
    "decision_history.json": 3600,
    "missed_runners.json": 1800,
    "pnl.json": 3600,
    "positions.json": 1800,
    "bot_health.json": 600,
    
    # Slower-changing intel
    "narrative_boost.json": 7200,
    "volume_baseline.json": 21600,
    
    # Library files (large, slow updates)
    "pattern_outcomes.json": 86400,
    "autopsy_reports.json": 86400,
    "dynamic_thresholds.json": 86400,
    
    # Static/protected files
    "kol_list.json": None,  # never expires
    "trading_baseline.json": None,
}


def get_recommended_max_age(filename: str) -> int:
    """Look up recommended max_age_seconds for a known file."""
    base = os.path.basename(str(filename))
    return COMMON_MAX_AGES.get(base, DEFAULT_MAX_AGE_RUNTIME) or DEFAULT_MAX_AGE_RUNTIME
