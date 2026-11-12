"""agent_memo.py - close the loop: every action an agent sends to the Sniper bots gets a
confirmation or failure memo in the agent inbox (inbox/).

Memo file: inbox/"<source> - <confirm|failed>_<kind>_<id8>_<ts>.json"
  {"type": "action_result", "kind", "ok", "status", "summary" (one line), "reason" (on failure),
   "request_id", "source", "detail", "at", "actions_taken": []}

Kill switches (env): AGENT_MEMOS=0 turns every memo off; AGENT_MEMO_<KIND>=0 turns one kind off
(e.g. AGENT_MEMO_SIGNAL=0, AGENT_MEMO_LAUNCH=0). AGENT_MEMO_SUCCESS=0 keeps failures only.
Never raises: a memo failure must never break the bot that called it.
"""
import json
import os
import re
import time
from datetime import datetime

def _root() -> str:
    """WORKSPACE_DIR wins; else the folder that holds bots/ (works from bots/ and bots/sub-bots/)."""
    v = (os.environ.get("WORKSPACE_DIR") or "").strip()
    if v:
        return os.path.abspath(os.path.expanduser(v))
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(4):
        if os.path.basename(d).lower() == "bots":
            return os.path.dirname(d)
        d = os.path.dirname(d)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SEEN: dict = {}
_OFF = ("0", "false", "off", "no")


def _on(key: str, default: str = "1") -> bool:
    return str(os.environ.get(key, default) or default).strip().lower() not in _OFF


def enabled(kind: str, ok: bool = True) -> bool:
    if not _on("AGENT_MEMOS"):
        return False
    if ok and not _on("AGENT_MEMO_SUCCESS"):
        return False
    return _on("AGENT_MEMO_" + re.sub(r"[^A-Z0-9]", "_", str(kind).upper()))


def _safe(s, n=24) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(s or "na"))[:n].strip("_") or "na"


def write(kind: str, ok: bool, summary: str, *, request_id=None, reason: str = "", source: str = "meme_sniper",
          status: str = "", detail: dict = None, inbox_dir=None, dedupe: bool = True):
    """Write one memo. Returns the Path, or None (switched off, duplicate or error)."""
    try:
        if not enabled(kind, ok):
            return None
        key = f"{source}|{kind}|{request_id}|{status or ok}"
        if dedupe and request_id and key in _SEEN:
            return None
        _SEEN[key] = time.time()
        if len(_SEEN) > 2000:
            for k in list(_SEEN)[:500]:
                _SEEN.pop(k, None)
        d = inbox_dir or os.path.join(_root(), "inbox")
        os.makedirs(d, exist_ok=True)
        now = datetime.now()
        line = " ".join(str(summary or "").split())[:240]
        pkt = {"type": "action_result", "kind": kind, "ok": bool(ok),
               "status": status or ("confirmed" if ok else "failed"),
               "summary": line, "reason": ("" if ok else (" ".join(str(reason or line).split())[:400])),
               "request_id": request_id, "source": source, "detail": detail or {},
               "at": now.isoformat(timespec="seconds"), "actions_taken": []}
        name = f"{source} - {'confirm' if ok else 'failed'}_{_safe(kind, 20)}_{_safe(request_id, 16)}_{now.strftime('%Y%m%d_%H%M%S')}_{os.urandom(2).hex()}.json"
        p = os.path.join(d, name)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(pkt, f, indent=2, default=str)
        os.replace(tmp, p)
        return p
    except Exception:
        return None
