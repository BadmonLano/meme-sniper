"""v1.0.15: AGENT_MODE=suggest holds agent trades for the owner's OK (offline)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BOTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BOTS))
import agent_mode  # noqa: E402


class AgentMode(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.relay, self.logs, self.inbox = self.tmp / "json_relay", self.tmp / "bot_logs", self.tmp / "owner_inbox"
        self.sigs = self.relay / "agent_signals.json"
        os.environ.pop("OWNER_TRADE_APPROVALS_FILE", None)

    def test_default_is_suggest(self):
        self.assertEqual(agent_mode.mode({}), "suggest")
        self.assertEqual(agent_mode.mode({"AGENT_MODE": "bogus"}), "suggest")
        self.assertEqual(agent_mode.mode({"AGENT_MODE": "auto"}), "auto")

    def test_gate(self):
        s = {"action": "buy", "mint": "M"}
        self.assertTrue(agent_mode.needs_owner_ok("buy", s, {}))
        self.assertTrue(agent_mode.needs_owner_ok("sell", s, {"AGENT_MODE": "suggest"}))
        self.assertFalse(agent_mode.needs_owner_ok("buy", s, {"AGENT_MODE": "auto"}))
        self.assertFalse(agent_mode.needs_owner_ok("set_protection", s, {}))
        self.assertFalse(agent_mode.needs_owner_ok("buy", {**s, "_owner_approved_id": "x"}, {}))

    def test_hold_approve_release(self):
        sig = {"signal_id": "s1", "action": "buy", "mint": "M", "ticker": "T", "amount_sol": 0.1}
        agent_mode.hold(sig, "s1", "buy", self.relay, self.inbox)
        self.assertEqual(len(list(self.inbox.glob("*.md"))), 1)
        self.assertEqual(agent_mode.release(self.relay, self.logs, self.sigs)["approved"], [])
        agent_mode.record_answer("s1", True, self.logs)
        out = agent_mode.release(self.relay, self.logs, self.sigs)
        self.assertEqual(out["approved"], ["s1"])
        bus = json.loads(self.sigs.read_text())["signals"]
        self.assertEqual(bus[0]["_owner_approved_id"], "s1")
        self.assertFalse(agent_mode.needs_owner_ok("buy", bus[0], {}))
        self.assertEqual(agent_mode.list_pending(self.relay), [])

    def test_reject_and_expire(self):
        agent_mode.hold({"action": "sell", "mint": "A"}, "a", "sell", self.relay, self.inbox)
        agent_mode.hold({"action": "buy", "mint": "B"}, "b", "buy", self.relay, self.inbox)
        agent_mode.record_answer("a", False, self.logs)
        out = agent_mode.release(self.relay, self.logs, self.sigs, now=10**11)
        self.assertEqual(out["rejected"], ["a"])
        self.assertEqual(out["expired"], ["b"])
        self.assertFalse(self.sigs.exists())


if __name__ == "__main__":
    unittest.main()
