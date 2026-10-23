"""Offline tests for owner_commands.py + roast_now(). No network, no wallet, no SI calls.
Run: python test_owner_commands.py   (from bots/ or bots/tests/)"""
import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import unittest

_D = os.path.dirname(os.path.abspath(__file__))
for _c in (_D, os.path.join(_D, "..", "sub-bots"), os.path.join(_D, "sub-bots")):
    if os.path.isfile(os.path.join(_c, "owner_commands.py")):
        SRC = os.path.abspath(_c)
        break
else:
    raise SystemExit("owner_commands.py not found")
sys.path.insert(0, SRC)
spec = importlib.util.spec_from_file_location("owner_commands_t", os.path.join(SRC, "owner_commands.py"))
oc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oc)
run = asyncio.run


class Parse(unittest.TestCase):
    def test_slash_commands_any_case(self):
        self.assertEqual(oc.parse_command("/roast"), ("roast", None))
        self.assertEqual(oc.parse_command("/ROAST"), ("roast", None))
        self.assertEqual(oc.parse_command("/Recap@SomeBot"), ("recap", None))
        self.assertEqual(oc.parse_command("/autopsy"), ("autopsy", "last"))
        self.assertEqual(oc.parse_command("/AUTOPSY $GORK"), ("autopsy", "GORK"))
        self.assertEqual(oc.parse_command("/autopsy last"), ("autopsy", "last"))

    def test_plain_text(self):
        self.assertEqual(oc.parse_command("Roast. Be honest."), ("roast", None))
        self.assertEqual(oc.parse_command("give me a recap"), ("recap", None))
        self.assertEqual(oc.parse_command("autopsy on $gork please"), ("autopsy", "gork"))
        self.assertEqual(oc.parse_command("Autopsy please"), ("autopsy", "last"))
        self.assertEqual(oc.parse_command("hello"), ("help", None))
        self.assertEqual(oc.parse_command("/start"), ("help", None))
        self.assertIsNone(oc.parse_command("   "))


class Config(unittest.TestCase):
    def test_default_off(self):
        self.assertEqual(oc.mode({}), "off")
        self.assertEqual(oc.mode({"OWNER_COMMANDS": "Telegram"}), "telegram")
        self.assertEqual(oc.mode({"OWNER_COMMANDS": "bogus"}), "off")

    def test_refuses_shared_token(self):
        env = {"OWNER_COMMANDS_TG_TOKEN": "A", "TELEGRAM_TOKEN": "A", "TELEGRAM_CHAT_ID": "1"}
        self.assertFalse(oc.tg_config(env)["ok"])
        env = {"OWNER_COMMANDS_TG_TOKEN": "B", "X_NOTIFY_TELEGRAM_TOKEN": "B", "TELEGRAM_CHAT_ID": "1"}
        self.assertFalse(oc.tg_config(env)["ok"])
        self.assertFalse(oc.tg_config({"TELEGRAM_CHAT_ID": "1"})["ok"])
        c = oc.tg_config({"OWNER_COMMANDS_TG_TOKEN": "C", "TELEGRAM_TOKEN": "A", "TELEGRAM_CHAT_ID": "1"})
        self.assertTrue(c["ok"]) ; self.assertEqual(c["chat_id"], "1")

    def test_status_never_prints_token(self):
        s = json.dumps(oc.status({"OWNER_COMMANDS": "telegram", "OWNER_COMMANDS_TG_TOKEN": "SECRET123",
                                  "TELEGRAM_CHAT_ID": "1"}))
        self.assertNotIn("SECRET123", s)


class WithOverseer(unittest.TestCase):
    """Real roast_now() from the *_autoagent.py next to owner_commands.py, judges stubbed."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.o = oc.overseer()
        self._saved = {k: getattr(self.o, k) for k in
                       ("LOGS", "INBOX_RESULTS", "collect_inputs", "run_judgment", "notify", "OVERSEER_LOG")}
        self.o.LOGS = os.path.join(self.tmp, "bot_logs"); os.makedirs(self.o.LOGS)
        self.o.OVERSEER_LOG = os.path.join(self.tmp, "overseer_test.log")   # never the real log
        self.o.INBOX_RESULTS = os.path.join(self.tmp, "inbox_results")
        self.sent, self.judged = [], []
        self.o.collect_inputs = lambda: {"meme": {}}

        async def judge(inputs, top):
            self.judged.append(1)
            return {"verdict": {"headline": "Held <too> long", "score_0_to_10": 6,
                                "what_was_weak": ["chased a top"], "what_was_strong": ["sat out rugs"],
                                "improvements_for_tomorrow": ["size down"]},
                    "meta": {"judge": "stub"}}

        async def notify(msg):
            self.sent.append(msg)
        self.o.run_judgment, self.o.notify = judge, notify
        os.environ["OWNER_COMMANDS_DIR"] = os.path.join(self.tmp, "owner_commands")

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(self.o, k, v)
        os.environ.pop("OWNER_COMMANDS_DIR", None)

    def test_overseer_file_untouched(self):
        with open(self.o.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("roast_now", src)              # the Overseer is reused, never edited

    def test_roast_then_cooldown(self):
        r = run(oc.roast_now("roast"))
        self.assertTrue(r["ok"]); self.assertIn("Roast", r["text"]); self.assertIn("&lt;too&gt;", r["text"])
        self.assertTrue(os.path.isfile(r["reply_path"])); self.assertEqual(len(self.sent), 1)
        r2 = run(oc.roast_now("recap"))
        self.assertFalse(r2["ok"]); self.assertEqual(r2["reason"], "cooldown")
        self.assertEqual(len(self.judged), 1)          # no second SI call inside the cooldown

    def test_nightly_files_untouched(self):
        run(oc.roast_now("recap", send=False))
        self.assertEqual(self.sent, [])
        names = os.listdir(self.o.LOGS)
        self.assertEqual(sorted(n for n in names if n != "owner_commands.log"), ["owner_roast_last.json"])   # no summary / history / packet

    def test_autopsy_last_and_ticker(self):
        with open(os.path.join(self.o.LOGS, "autopsy_reports.json"), "w") as f:
            json.dump([{"mint": "AAA", "position": {"ticker": "gork"}, "pnl_pct": 24.0, "exit_trigger": "tp",
                        "max_x_vs_exit": 1.42, "sold_too_early_final": True},
                       {"mint": "BBB", "position": {"ticker": "FLOW"}, "pnl_pct": -8.5}], f)
        r = run(oc.roast_now("autopsy", "last", send=False))
        self.assertIn("FLOW", r["text"])
        r = run(oc.roast_now("autopsy", "GORK", send=False))
        self.assertIn("gork", r["text"]); self.assertIn("sold_too_early=True", r["text"])
        r = run(oc.roast_now("autopsy", "nope", send=False))
        self.assertIn("No closed trade", r["text"])
        self.assertEqual(self.judged, [])             # autopsy never calls the judges

    def test_file_source(self):
        d = os.environ["OWNER_COMMANDS_DIR"]; os.makedirs(d)
        with open(os.path.join(d, "a.txt"), "w") as f:
            f.write("ROAST me\n")
        with open(os.path.join(d, "b.json"), "w") as f:
            json.dump({"text": "hello"}, f)
        self.assertEqual(run(oc.file_once()), 2)
        self.assertEqual(os.listdir(d), [])
        self.assertEqual(len(os.listdir(os.path.join(self.o.INBOX_RESULTS, "owner_commands", "done"))), 2)
        self.assertEqual(len(self.sent), 2)            # roast + help, via alert channels

    def test_telegram_owner_chat_only_and_409(self):
        calls = []
        updates = [{"update_id": 10, "message": {"chat": {"id": 999}, "text": "/roast", "message_id": 1}},
                   {"update_id": 11, "message": {"chat": {"id": 1}, "text": "/Autopsy", "message_id": 2}}]

        async def fake(tok, method, params, timeout=0):
            calls.append(method)
            if method == "getWebhookInfo":
                return {"ok": True, "result": {"url": ""}}
            if method == "getUpdates" and params.get("offset") == -1:
                return {"ok": True, "result": []}
            if method == "getUpdates":
                if calls.count("getUpdates") == 2:
                    return {"ok": True, "result": updates}
                raise oc.TgConflict("getUpdates")
            if method == "sendMessage":
                self.assertEqual(params["chat_id"], "1")
                return {"ok": True}
        why = run(oc.telegram_loop({"token": "T", "chat_id": "1"}, call=fake, max_polls=5))
        self.assertEqual(why, "conflict")              # stops on 409, never fights
        self.assertEqual(calls.count("sendMessage"), 1)  # stranger's chat ignored
        self.assertEqual(self.judged, [])              # the stranger's /roast never ran

    def test_webhook_means_no_polling(self):
        async def fake(tok, method, params, timeout=0):
            if method == "getWebhookInfo":
                return {"ok": True, "result": {"url": "https://example.invalid/hook"}}
            raise AssertionError("must not poll")
        self.assertEqual(run(oc.telegram_loop({"token": "T", "chat_id": "1"}, call=fake)), "webhook")


class OwnerPositions(unittest.TestCase):
    """/manage and /leave write a decision the bots pick up. No overseer needed."""
    def setUp(self):
        self.logs = tempfile.mkdtemp()
        os.environ.pop("OWNER_POS_DECISIONS_FILE", None)

    def _pending(self):
        with open(os.path.join(self.logs, "owner_positions_sniper.json"), "w") as f:
            json.dump({"records": {"MINT1": {"id": "op_PEPE_1", "ticker": "PEPE", "state": "pending"}}}, f)
        with open(os.path.join(self.logs, "owner_positions_perps.json"), "w") as f:
            json.dump({"records": {"SOL-PERP": {"id": "op_sol_1", "state": "pending", "market": "SOL-PERP"}}}, f)

    def _rows(self):
        p = os.path.join(self.logs, "owner_position_decisions.jsonl")
        return [json.loads(l) for l in open(p)] if os.path.exists(p) else []

    def test_parse_any_case(self):
        self.assertEqual(oc.parse_command("/MANAGE $Pepe"), ("manage", "Pepe"))
        self.assertEqual(oc.parse_command("/leave sol"), ("leave", "sol"))
        self.assertEqual(oc.parse_command("/Leave@Bot SOL"), ("leave", "SOL"))
        self.assertEqual(oc.parse_command("/manage"), ("manage", None))

    def test_manage_and_leave_write_decisions(self):
        self._pending()
        r = oc.owner_position_decision("manage", "pepe", logs=self.logs)
        self.assertTrue(r["ok"]); self.assertIn("PEPE", r["text"])
        r = oc.owner_position_decision("leave", "SOL", logs=self.logs)
        self.assertTrue(r["ok"])
        rows = self._rows()
        self.assertEqual([(x["target"], x["decision"]) for x in rows], [("pepe", "manage"), ("sol", "leave")])
        self.assertTrue(all(isinstance(x["ts"], float) for x in rows))

    def test_no_match_writes_nothing(self):
        self._pending()
        r = oc.owner_position_decision("manage", "wif", logs=self.logs)
        self.assertFalse(r["ok"]); self.assertIn("PEPE", r["text"])
        self.assertEqual(self._rows(), [])

    def test_missing_target_lists_pending(self):
        self._pending()
        r = oc.owner_position_decision("leave", None, logs=self.logs)
        self.assertFalse(r["ok"]); self.assertIn("Usage", r["text"])



class RoastTarget(WithOverseer):
    """v1.0.2: the roast goes to whoever opened the positions. Dummy books only."""
    def setUp(self):
        super().setUp()
        self.grok = []
        self._cg = getattr(self.o, "call_grok", None)

        async def cg(system, user):
            self.grok.append(user)
            return {"ok": True, "verdict": {"headline": "you held it into the floor", "score_0_to_10": 3,
                                            "what_was_weak": ["held past your own stop"]}, "source": "stub_owner"}
        self.o.call_grok = cg
        self.seen_inputs = []
        base = self.o.run_judgment

        async def judge(inputs, top):
            self.seen_inputs.append(json.loads(json.dumps(inputs, default=str)))
            return await base(inputs, top)
        self.o.run_judgment = judge
        os.environ.pop("OWNER_ROAST_TARGETING", None)

    def tearDown(self):
        if self._cg is not None:
            self.o.call_grok = self._cg
        os.environ.pop("OWNER_ROAST_TARGETING", None)
        super().tearDown()

    def book(self, positions=None, autopsies=None, owner_recs=None):
        L = self.o.LOGS
        for name, data in (("positions.json", positions or {}), ("autopsy_reports.json", autopsies or []),
                           ("owner_positions_sniper.json", {"records": owner_recs or {}})):
            with open(os.path.join(L, name), "w") as f:
                json.dump(data, f)

    AGENT = {"AG1": {"mint": "AG1", "ticker": "gork", "originating_signal_id": "sig_123", "last_pnl_pct": -12.0}}
    OWNER = {"OW1": {"mint": "OW1", "ticker": "FLOW", "originating_signal_id": "op_FLOW_OW1xxx_1_manage",
                     "last_pnl_pct": -41.0, "peak_pnl_pct": 30.0, "params": {"stop_loss_pct": 25}}}

    def test_opener_fields(self):
        f = oc.position_opener
        self.assertEqual(f({"originating_signal_id": "sig_9"}), "agent")
        self.assertEqual(f({"originating_signal_id": "op_X_1_manage"}), "owner")
        self.assertEqual(f({"source": "owner_position"}), "owner")
        self.assertEqual(f({"opened_by": "manual"}), "owner")
        self.assertEqual(f({"position": {"source": "owner"}}), "owner")
        self.assertEqual(f({"promoted_from_holding": True, "reasoning_at_buy": "promoted from treasury"}), "agent")
        self.assertEqual(f({"exit_trigger": "manual"}), "agent")      # who CLOSED it does not matter

    def test_agent_only_book_self_roast(self):
        self.book(positions=self.AGENT)
        r = run(oc.roast_now("roast", send=False))
        self.assertEqual(r["roast_target"], "agent"); self.assertEqual(self.grok, [])
        self.assertIn("the agent, on its own calls", r["text"]); self.assertEqual(len(self.judged), 1)

    def test_owner_only_book_roasts_owner(self):
        self.book(positions=self.OWNER, owner_recs={"OW2": {"ticker": "PUMP", "state": "leave", "detected_ts": 0}})
        r = run(oc.roast_now("roast", send=False))
        self.assertEqual(r["roast_target"], "owner"); self.assertEqual(self.judged, [])   # no agent roast
        self.assertIn("you, on the trades you made", r["text"]); self.assertEqual(r["owner_positions"], 2)
        self.assertIn("still holding past your -25% stop", self.grok[0]); self.assertIn("gave back 71 pts", self.grok[0])
        self.assertIn("PUMP", self.grok[0])

    def test_mixed_book_split(self):
        self.book(positions={**self.AGENT, **self.OWNER})
        self.o.collect_inputs = lambda: {"meme": {"positions_open": {**self.AGENT, **self.OWNER}}}
        r = run(oc.roast_now("roast", send=False))
        self.assertEqual(r["roast_target"], "split")
        self.assertIn("the agent, on its own calls", r["text"]); self.assertIn("you, on the trades you made", r["text"])
        self.assertEqual(list(self.seen_inputs[0]["meme"]["positions_open"]), ["AG1"])    # agent graded on its own calls
        self.assertNotIn("gork", self.grok[0])                                         # owner graded on theirs

    def test_owner_roast_falls_back_local(self):
        async def boom(s, u): raise RuntimeError("no key")
        self.o.call_grok = boom
        self.book(positions=self.OWNER)
        r = run(oc.roast_now("roast", send=False))
        self.assertEqual(r["judge"], "local"); self.assertIn("FLOW", r["text"])

    def test_forced_agent_and_kill_switch(self):
        self.book(positions=self.OWNER)
        self.assertEqual(oc.parse_command("/roast agent"), ("roast", "agent"))
        self.assertEqual(oc.parse_command("roast yourself"), ("roast", "agent"))
        self.assertEqual(oc.parse_command("roast me"), ("roast", None))
        r = run(oc.roast_now("roast", "agent", send=False))
        self.assertEqual(r["roast_target"], "agent")
        os.environ["OWNER_ROAST_TARGETING"] = "off"
        self.o.save_json_atomic(oc._roast_state_path(), {"last_ts": 0})
        r = run(oc.roast_now("roast", send=False))
        self.assertEqual(r["roast_target"], "agent"); self.assertEqual(self.grok, [])
        self.assertIn("🔥 <b>Roast</b> |", r["text"])                                 # legacy header, untouched

if __name__ == "__main__":
    unittest.main(verbosity=2)
