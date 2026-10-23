"""Skill/code path drift check: every json_relay/*, bot_logs/* and inbox-dir name a skill tells the
agent to read or write must be referenced somewhere in the code. Run: python skill_path_drift.py <root>"""
import re, sys, json
from pathlib import Path

PAT = re.compile(r"(?<![\w.])(json_relay|bot_logs|inbox_results|owner_inbox|inbox)[/\\]([A-Za-z0-9_.\-/\\]+)")
SKIP_CHARS = set("<>*{}")

# Files the AGENT owns (the skill tells the agent to read/write them; no bot code touches them).
# A path not in the code and not listed here is drift and fails the smoke.
AGENT_OWNED = {
    "bot_logs/agent_pattern_discoveries.json": "autoagent: the agent's named discoveries",
    "bot_logs/agent_training_dataset.json": "autoagent: agent-built dataset",
    "bot_logs/autopsy_skill_history.jsonl": "forensics: skill-side autopsy history",
    "bot_logs/ca_intel_coverage_gaps.json": "ca-intel: agent feed-forward gaps",
    "bot_logs/daily_thesis.json": "autoagent: agent writes the daily thesis",
    "bot_logs/ecosystem_audit_history.json": "autoagent: agent audit report",
    "bot_logs/filter_patches.json": "forensics: patch audit the agent writes",
    "bot_logs/learnings_coverage_gaps.json": "learnings-summarizer (agent-run)",
    "bot_logs/learnings_distill_cron_state.json": "learnings-summarizer (agent-run)",
    "bot_logs/learnings_summarizer_heartbeat.json": "learnings-summarizer (agent-run)",
    "bot_logs/miss_analyst_config.json": "forensics: agent-tuned config",
    "bot_logs/miss_reports.json": "forensics: agent miss reports",
    "bot_logs/pattern_library.json": "autoagent: legacy agent library",
    "bot_logs/source_accuracy.json": "autoagent: agent-maintained accuracy table",
}

def refs(root: Path) -> dict:
    out = {}
    for f in sorted((root / "skills").rglob("*.md")):
        for m in PAT.finditer(f.read_text(encoding="utf-8", errors="replace")):
            name = m.group(2).replace("\\", "/").rstrip("/.").split("/")[0]
            if not name or any(c in SKIP_CHARS for c in m.group(0)) or name.startswith("."):
                continue
            out.setdefault(f"{m.group(1)}/{name}", set()).add(str(f.relative_to(root)).replace("\\", "/"))
    return out

def code_blob(root: Path) -> str:
    parts = []
    for f in (root / "bots").rglob("*.py"):
        if "scraper_profile" in f.parts or "__pycache__" in f.parts or "tests" in f.parts:
            continue
        parts.append(f.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)

def check(root) -> dict:
    root = Path(root)
    r, blob = refs(root), code_blob(root)
    missing = {}
    for key, files in sorted(r.items()):
        name = key.split("/", 1)[1]
        stem = name.rsplit(".", 1)[0] if "." in name else name
        if key in AGENT_OWNED:
            continue
        if name not in blob and f'"{stem}"' not in blob and f"'{stem}'" not in blob:
            missing[key] = sorted(files)[:3]
    stale = sorted(k for k in AGENT_OWNED if k not in r)
    return {"checked": len(r), "agent_owned": len(AGENT_OWNED), "missing": missing, "allowlist_stale": stale}

if __name__ == "__main__":
    res = check(sys.argv[1] if len(sys.argv) > 1 else ".")
    print(json.dumps(res, indent=1))
    sys.exit(1 if (res["missing"] or res["allowlist_stale"]) else 0)
