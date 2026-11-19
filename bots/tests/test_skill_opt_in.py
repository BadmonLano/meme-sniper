"""v1.0.18: skills are opt-in and suggest-only.

Fails if skill text (and the playbooks and docs that point at it) still
contains an always-on marker or an auto-trade / self-patch instruction.
No network, no keys, no trading.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAX_SKILL_BYTES = 40_000

# Bad instructions. Negations in the safety contract are written so they do
# not contain these substrings.
FORBIDDEN = (
    "always loaded",
    "always-loaded",
    "always-on",
    "core, always",
    "alwaysapply: true",
    '"alwaysapply": true',
    "1-2 buys",
    "at least 1-2",
    "not firing at least",
    "buy logic is too strict",
    "loop meant to run continuously",
    "continuous trading loop",
    "keep a continuous",
    "buy bypass",
    "bypassing a gate",
    "bypass gates",
    "bypass the gate",
    "loosen filters",
    "loosen the filter",
    "loosening",
    "applies the wire",
    "apply it yourself",
    "apply the patch yourself",
    "the agent applies",
    "auto-execute",
    "execute the trade",
    "sign the transaction",
    "launch the token",
    "you apply it",
    "keep your lane automations",
    "tier 1 always",
    "filters too tight",
    "fix and resend",
)


def _texts():
    out = []
    for folder in ("skills", "automations", "rules", "templates", "learnings"):
        for path in sorted((ROOT / folder).rglob("*.md")):
            out.append((str(path.relative_to(ROOT)), path.read_text(encoding="utf-8")))
    for rel in (
        "README.md",
        "SETUP.md",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "docs/LAUNCH_RAIL.md",
        "docs/DEPENDENCY_MAP.md",
        ".cursor-plugin/plugin.json",
        ".grok-plugin/plugin.json",
    ):
        out.append((rel, (ROOT / rel).read_text(encoding="utf-8")))
    return out


def test_skill_tree_is_well_under_40kb():
    total = 0
    for path in (ROOT / "skills").rglob("*.md"):
        total += len(path.read_bytes())
    assert total < MAX_SKILL_BYTES, total
    assert total > 0


def test_no_forbidden_autotrade_or_always_on_phrases():
    for rel, text in _texts():
        low = text.lower()
        for phrase in FORBIDDEN:
            assert phrase not in low, (rel, phrase)


def test_every_skill_is_explicit_opt_in():
    skills = sorted((ROOT / "skills").rglob("SKILL.md"))
    assert len(skills) >= 11
    for path in skills:
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(ROOT))
        assert "disable-model-invocation: true" in text, rel
        assert "alwaysApply: false" in text, rel
        assert "alwaysApply: true" not in text, rel
        low = text.lower()
        assert "opt-in" in low, rel
        assert "suggest-only" in low, rel
        assert "owner_inbox" in low, rel
        assert "never edit" in low, rel
        assert "fresh owner approval" in low, rel
    readme = (ROOT / "skills" / "README.md").read_text(encoding="utf-8").lower()
    assert "no skill is core" in readme
    assert "explicitly" in readme
    for rel in (".cursor-plugin/plugin.json", ".grok-plugin/plugin.json"):
        plugin = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        assert plugin["alwaysApply"] is False
        assert "explicitly invokes" in plugin["description"].lower()
