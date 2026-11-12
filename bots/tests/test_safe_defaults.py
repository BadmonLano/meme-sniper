"""v1.0.17: missing env stays paper / suggest-side, and skills do not hijack an agent.

No network, no keys, no trading.
"""
import json
import os
import sys
from pathlib import Path

BOTS = Path(__file__).resolve().parents[1]
ROOT = BOTS.parent
sys.path.insert(0, str(BOTS))
import safe_defaults  # noqa: E402


def test_paper_mode_missing_is_paper_and_live_is_explicit():
    assert safe_defaults.paper_mode({}) is True
    assert safe_defaults.paper_mode({"SNIPER_PAPER_MODE": ""}) is True
    assert safe_defaults.paper_mode({"SNIPER_PAPER_MODE": "1"}) is True
    assert safe_defaults.paper_mode({"SNIPER_PAPER_MODE": "true"}) is True
    assert safe_defaults.paper_mode({"SNIPER_PAPER_MODE": "yes"}) is True
    assert safe_defaults.paper_mode({"SNIPER_PAPER_MODE": "on"}) is True
    assert safe_defaults.paper_mode({"SNIPER_PAPER_MODE": "banana"}) is True
    for off in ("0", "false", "no", "off", "FALSE", " Off "):
        assert safe_defaults.paper_mode({"SNIPER_PAPER_MODE": off}) is False


def test_paper_mode_reads_process_env_as_paper_when_unset():
    old = os.environ.pop("SNIPER_PAPER_MODE", None)
    try:
        assert safe_defaults.paper_mode() is True
        os.environ["SNIPER_PAPER_MODE"] = "0"
        assert safe_defaults.paper_mode() is False
        os.environ["SNIPER_PAPER_MODE"] = "1"
        assert safe_defaults.paper_mode() is True
    finally:
        if old is None:
            os.environ.pop("SNIPER_PAPER_MODE", None)
        else:
            os.environ["SNIPER_PAPER_MODE"] = old


def test_armed_stops_and_owner_timeout_default_off():
    assert safe_defaults.armed_stops_enabled({}) is False
    assert safe_defaults.armed_stops_enabled({"ARMED_STOPS": ""}) is False
    assert safe_defaults.armed_stops_enabled({"ARMED_STOPS": "0"}) is False
    assert safe_defaults.armed_stops_enabled({"ARMED_STOPS": "off"}) is False
    assert safe_defaults.armed_stops_enabled({"ARMED_STOPS": "1"}) is True
    assert safe_defaults.armed_stops_enabled({"ARMED_STOPS": "on"}) is True
    assert safe_defaults.owner_pos_auto_timeout({}) is False
    assert safe_defaults.owner_pos_auto_timeout({"OWNER_POS_AUTO_TIMEOUT": "off"}) is False
    assert safe_defaults.owner_pos_auto_timeout({"OWNER_POS_AUTO_TIMEOUT": ""}) is False
    assert safe_defaults.owner_pos_auto_timeout({"OWNER_POS_AUTO_TIMEOUT": "on"}) is True
    assert safe_defaults.owner_pos_auto_timeout({"OWNER_POS_AUTO_TIMEOUT": "1"}) is True


def test_engine_and_launch_rail_use_the_safe_helper():
    src = (BOTS / "meme_sniper.py").read_text(encoding="utf-8")
    assert "PAPER_MODE = _sd_paper_mode()" in src
    assert "ARMED_STOPS = _sd_armed_stops()" in src
    assert '_envv("OWNER_POS_AUTO_TIMEOUT", "off")' in src
    assert '_envv("SNIPER_PAPER_MODE", "0")' not in src
    assert 'env["LAUNCH_RAIL_LIVE"] = "1"' not in src
    rail = (BOTS / "sub-bots" / "launch_rail.py").read_text(encoding="utf-8")
    body = rail.split("def _paper_mode", 1)[1].split("def _rail_live_env", 1)[0]
    assert 'or "0"' not in body
    assert "from safe_defaults import paper_mode" in body
    assert '(os.getenv("LAUNCH_RAIL_LIVE") or "0")' in rail


def test_env_example_readme_and_security_agree():
    env = (BOTS / ".env.example").read_text(encoding="utf-8")
    assert "\nSNIPER_PAPER_MODE=1\n" in env
    assert "\nARMED_STOPS=0\n" in env
    assert "\nOWNER_POS_AUTO_TIMEOUT=off\n" in env
    assert "\nLAUNCH_RAIL_LIVE=0\n" in env
    assert "\nLAUNCH_RAIL_ENABLED=false\n" in env
    sec = (ROOT / "SECURITY.md").read_text(encoding="utf-8").lower()
    assert "paper is the default" in sec
    assert "launch rail ships off" in sec
    assert "ships on" not in sec
    assert "live by default" not in sec
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Missing, blank, or `1` does not sign" in readme
    assert "Trading is live from the first start" not in readme
    setup = (ROOT / "SETUP.md").read_text(encoding="utf-8")
    assert "ships on" in setup.lower() or "ships **on**" in setup or "**ships on**" in setup
    assert "off by default; live stays the default" not in setup


FORBIDDEN = (
    "apply it yourself",
    "apply the patch yourself",
    "applies his own patch",
    "applies patches to other files",
    "authors and applies",
    "upgrade its own local copy",
    "base58 32-44 char string appears",
    "anytime a base58",
    "you apply it.",
)


def test_skills_and_manifests_do_not_hijack():
    blobs = []
    for p in (ROOT / "skills").rglob("*.md"):
        blobs.append((str(p.relative_to(ROOT)), p.read_text(encoding="utf-8")))
    for rel in (
        ".cursor-plugin/plugin.json",
        ".grok-plugin/plugin.json",
        "automations/sniper_lane.automation.md",
        "automations/misc_lane.automation.md",
    ):
        blobs.append((rel, (ROOT / rel).read_text(encoding="utf-8")))
    for rel, text in blobs:
        low = text.lower()
        for phrase in FORBIDDEN:
            assert phrase not in low, (rel, phrase)
    for rel in (
        "skills/meme-hunter/SKILL.md",
        "skills/ca-intel/SKILL.md",
        "skills/sub-skills/code-monitor/SKILL.md",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "Safety contract" in text
        assert "Opt-in" in text
        assert "owner applies" in text.lower()
    ca = (ROOT / "skills/ca-intel/SKILL.md").read_text(encoding="utf-8")
    assert "There is no auto-trigger" in ca
    assert "not a trigger" in ca.lower()
    for rel in (".cursor-plugin/plugin.json", ".grok-plugin/plugin.json"):
        plugin = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        assert plugin["name"] == "meme-sniper"
        assert plugin["version"] == "1.0.17"
        assert plugin["license"] == "MIT"
        desc = plugin["description"].lower()
        assert "do not edit the trading engine" in desc
        assert "paper mode and suggest mode are the defaults" in desc
