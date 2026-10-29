"""Agent autonomy gate (v1.0.15, cursor.directory human-in-the-loop).

AGENT_MODE (bots/.env, asked FIRST in setup):
  suggest (default) the agent proposes trades; buy / sell signals are held until the
                    owner approves them (/approve <id> or `python bots/approve.py <id>`).
  auto              signals execute as soon as they pass the normal gates (old behaviour).

Held signals live in json_relay/pending_owner_approval.json and get an owner_inbox card.
Owner answers go to bot_logs/owner_trade_approvals.jsonl. An approved signal is put back
on agent_signals.json with a fresh timestamp and runs through every normal gate.
Bot-internal protective exits (armed SL/TP, stuck-bag watchdog) are not agent signals and
are not held: they protect the owner's money in both modes.
"""
import json
import os
import time
from pathlib import Path

GATED_ACTIONS = frozenset({"buy", "sell", "sell_holding", "harvest_holding", "panic_sell"})
MODES = ("suggest", "auto")


def mode(env=None) -> str:
    v = str((env if env is not None else os.environ).get("AGENT_MODE", "") or "").strip().lower()
    return v if v in MODES else "suggest"


def ttl_s() -> float:
    try:
        return max(60.0, float(os.environ.get("AGENT_MODE_APPROVAL_TTL_MIN", "60")) * 60)
    except ValueError:
        return 3600.0


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8") or "null") or default
    except Exception:
        return default


def _write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(p)


def pending_path(relay: Path) -> Path:
    return Path(relay) / "pending_owner_approval.json"


def approvals_path(logs: Path) -> Path:
    return Path(os.environ.get("OWNER_TRADE_APPROVALS_FILE") or Path(logs) / "owner_trade_approvals.jsonl")


def needs_owner_ok(action: str, sig: dict, env=None) -> bool:
    if mode(env) != "suggest" or action not in GATED_ACTIONS:
        return False
    return not (sig or {}).get("_owner_approved_id")


def hold(sig: dict, sig_id: str, action: str, relay: Path, owner_inbox: Path) -> dict:
    """Park a trade signal and write the owner card. Returns the pending record."""
    pend = _read_json(pending_path(relay), {"pending": {}})
    rec = {"id": sig_id, "action": action, "mint": sig.get("mint"), "ticker": sig.get("ticker"),
           "amount_sol": sig.get("amount_sol"), "reason": sig.get("reasoning") or sig.get("reason"),
           "held_at_ts": time.time(), "signal": sig}
    pend.setdefault("pending", {})[sig_id] = rec
    _write_json(pending_path(relay), pend)
    try:
        owner_inbox = Path(owner_inbox)
        owner_inbox.mkdir(parents=True, exist_ok=True)
        tick = str(sig.get("ticker") or "?").replace("/", "_")[:20]
        size = f" {sig.get('amount_sol')} SOL" if sig.get("amount_sol") else ""
        (owner_inbox / f"agent - approve_{action}_{tick}_{int(time.time())}.md").write_text(
            f"# Trade suggestion: {action.upper()} {tick}{size}\n\n"
            f"- signal id: `{sig_id}`\n- mint: `{sig.get('mint')}`\n"
            f"- why: {rec['reason'] or '(no reason given)'}\n\n"
            f"AGENT_MODE=suggest: nothing happens until you approve.\n"
            f"Approve: `/approve {sig_id}` (owner commands) or `python bots/approve.py {sig_id}`\n"
            f"Reject: `/reject {sig_id}` or `python bots/approve.py --reject {sig_id}`\n"
            f"Expires unanswered after {int(ttl_s() // 60)} min.\n", encoding="utf-8")
    except Exception:
        pass
    return rec


def record_answer(sig_id: str, approve: bool, logs: Path, source: str = "owner") -> dict:
    row = {"ts": time.time(), "id": str(sig_id).strip(), "decision": "approve" if approve else "reject",
           "source": source}
    p = approvals_path(logs)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row


def _answers(logs: Path) -> dict:
    out = {}
    p = approvals_path(logs)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            out[str(r["id"])] = r
        except Exception:
            continue
    return out


def list_pending(relay: Path) -> list:
    return list((_read_json(pending_path(relay), {"pending": {}}).get("pending") or {}).values())


def release(relay: Path, logs: Path, signals_file: Path, now: float = None) -> dict:
    """Move approved signals back onto the bus, drop rejected and expired ones."""
    now = now or time.time()
    pend = _read_json(pending_path(relay), {"pending": {}})
    items = pend.get("pending") or {}
    if not items:
        return {"approved": [], "rejected": [], "expired": []}
    ans = _answers(logs)
    done = {"approved": [], "rejected": [], "expired": []}
    for sid, rec in list(items.items()):
        a = ans.get(sid)
        if a and a.get("ts", 0) >= rec.get("held_at_ts", 0) - 1:
            if a.get("decision") == "approve":
                sig = dict(rec.get("signal") or {})
                sig["_owner_approved_id"] = sid
                sig["requested_at_ts"] = now
                sig.pop("requested_at", None)
                sig["signal_id"] = f"{sid}_ok"
                _append_signal(Path(signals_file), sig)
                done["approved"].append(sid)
            else:
                done["rejected"].append(sid)
            items.pop(sid)
        elif now - rec.get("held_at_ts", now) > ttl_s():
            done["expired"].append(sid)
            items.pop(sid)
    pend["pending"] = items
    _write_json(pending_path(relay), pend)
    if any(done.values()):
        try:
            with open(Path(logs) / "agent_mode.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": now, **done}) + "\n")
        except Exception:
            pass
    return done


def _append_signal(p: Path, sig: dict) -> None:
    data = _read_json(p, {"signals": []})
    if isinstance(data, list):
        data.append(sig)
    else:
        data.setdefault("signals", []).append(sig)
    _write_json(p, data)
