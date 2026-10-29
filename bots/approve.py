"""Owner-only: approve or reject a trade the agent suggested (AGENT_MODE=suggest).

  python bots/approve.py                 list pending suggestions
  python bots/approve.py <signal_id>     approve (the bot runs it through every normal gate)
  python bots/approve.py --reject <id>   reject
Agents: never run this yourself. Approval is the owner's call.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import agent_mode  # noqa: E402


def _root() -> Path:
    import os
    ws = os.environ.get("WORKSPACE_DIR")
    return Path(ws) if ws else HERE.parent


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = _root()
    relay, logs = root / "json_relay", root / "bot_logs"
    if not argv:
        pend = agent_mode.list_pending(relay)
        if not pend:
            print("No pending trade suggestions.")
        for r in pend:
            print(f"{r['id']}: {r['action']} {r.get('ticker')} {r.get('amount_sol') or ''} - {r.get('reason') or ''}")
        return 0
    reject = argv[0] in ("--reject", "-r")
    ids = argv[1:] if reject else argv
    for sid in ids:
        agent_mode.record_answer(sid, not reject, logs, source="approve.py")
        print(("Rejected " if reject else "Approved ") + sid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
