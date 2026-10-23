"""Shared path layout for the sniper agent tools (lane_run).

Same root rule as meme_sniper.py: WORKSPACE_DIR (environment, then bots/.env or .env)
wins, otherwise the folder above bots/. Inbox, inbox_results, bot_logs and json_relay
live under that root.
"""
import os

TOOLS = os.path.dirname(os.path.abspath(__file__))
BOTS = os.path.dirname(TOOLS)


def _root():
    v = (os.environ.get("WORKSPACE_DIR") or "").strip()
    if not v:
        base = os.path.dirname(BOTS)
        for envf in (os.path.join(BOTS, ".env"), os.path.join(base, ".env")):
            try:
                with open(envf, encoding="utf-8-sig") as fh:
                    for ln in fh:
                        if ln.strip().startswith("WORKSPACE_DIR="):
                            v = ln.split("=", 1)[1].strip().strip('"').strip("'")
                            break
            except OSError:
                pass
            if v:
                break
        v = v or base
    return os.path.abspath(os.path.expanduser(v))


def layout():
    root = _root()
    return {"root": root, "relay": os.path.join(root, "json_relay"),
            "logs": os.path.join(root, "bot_logs"), "inbox": os.path.join(root, "inbox"),
            "results": os.path.join(root, "inbox_results"),
            "positions": os.path.join(root, "bot_logs", "positions.json"),
            "audit": os.path.join(root, "bot_logs", "inbox_cron_audit.log")}
