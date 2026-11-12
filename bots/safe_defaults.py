"""Safe defaults shared by the engine, the launch rail, and setup.

Missing or blank env values stay on the safe side. Live signing, armed
auto-sells, and the owner-position timeout each need an explicit opt-in.
"""
from __future__ import annotations

import os

_OFF = ("0", "false", "no", "off")
_ON = ("1", "true", "yes", "on")


def _raw(key: str, env=None) -> str:
    src = os.environ if env is None else env
    try:
        v = src.get(key)
    except Exception:
        v = None
    if v is None:
        return ""
    return str(v).strip()


def paper_mode(env=None) -> bool:
    """Paper (no signing) unless SNIPER_PAPER_MODE is explicitly off.

    Explicit live: 0, false, no, off.
    Unset, blank, 1, true, yes, on, or any other value stays paper.
    """
    v = _raw("SNIPER_PAPER_MODE", env).lower()
    if not v:
        return True
    return v not in _OFF


def armed_stops_enabled(env=None) -> bool:
    """True only when ARMED_STOPS is explicitly on. Unset does not sell."""
    return _raw("ARMED_STOPS", env).lower() in _ON


def owner_pos_auto_timeout(env=None) -> bool:
    """True only when OWNER_POS_AUTO_TIMEOUT is explicitly on. Unset does not take over."""
    return _raw("OWNER_POS_AUTO_TIMEOUT", env).lower() in _ON
