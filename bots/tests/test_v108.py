"""v1.0.8: protective orders never fail quiet. No network, no wallet.
Extracts the protection block from meme_sniper.py and runs it on stubs.
Run: pytest bots/tests/test_v108.py   (or python bots/tests/test_v108.py)"""
import asyncio, re, sys, tempfile
from pathlib import Path
from typing import Optional

SRC_PATH = Path(__file__).resolve().parents[1] / "meme_sniper.py"
SRC = SRC_PATH.read_text(encoding="utf-8")
A = SRC.index("def _protect_parse(sig: dict, position: dict) -> dict:")
B = SRC.index("def _levels_armed(position: dict) -> bool:")


def make_ns(sell_lands=True):
    pos, pkts, resp, tg, logs, sells = {}, [], [], [], [], []
    tmp = Path(tempfile.mkdtemp())

    async def write_signal_response(sid, status, **k): resp.append((sid, status, k))
    async def send_telegram(m, **k): tg.append(m)
    async def execute_sell_signal(sig):
        sells.append(sig)
        if sell_lands:
            pos.pop(sig["mint"], None)
    ns = {"Optional": Optional, "asyncio": asyncio, "_BOT_LOGS": tmp,
          "load_positions": lambda: pos, "upsert_position": lambda m, p: pos.__setitem__(m, p),
          "write_signal_response": write_signal_response, "send_telegram": send_telegram,
          "write_inbox_packet_generic": lambda p, **k: pkts.append(p),
          "_append_jsonl": lambda path, rec: open(path, "a").write(str(rec) + "\n"),
          "_log": lambda m, **k: logs.append(m), "_now_iso": lambda: "2026-10-27T12:00:00",
          "_now_ts": lambda: 1_800_000_000.0, "has_inflight_sell": lambda m: False,
          "execute_sell_signal": execute_sell_signal, "_knob_f": lambda k: 0.0,
          "higher_cap_stop_floors": lambda mcap, mode="flip": (0.0, 0.0),
          "PROTECT_ENFORCE": True, "PROTECT_SL_MIN_PCT": 3.0, "PROTECT_SL_MAX_PCT": 95.0,
          "PROTECT_TP_MIN_PCT": 5.0, "PROTECT_MAX_RETRIES": 5, "PROTECT_DEFAULT_STOP": True}
    exec(SRC[A:B], ns)
    ns.update(POS=pos, PKTS=pkts, RESP=resp, TG=tg, LOGS=logs, SELLS=sells, TMP=tmp)
    return ns


def bag(**o):
    p = {"ticker": "TEST", "entry_price": 1.0, "token_amount": 1000.0, "mode": "flip"}
    p.update(o)
    return p


def run(c):
    return asyncio.run(c)


def test_bad_levels_on_buy_report_reason_and_levels():
    ns = make_ns()
    ns["POS"]["M1"] = bag()
    errs = []
    sig = {"signal_id": "buy1", "mint": "M1", "stop_loss_pct": 99, "take_profit_pct": 2}
    assert run(ns["execute_set_protection"](sig, respond=False, errors_out=errs)) is False
    assert not ns["RESP"]                              # respond=False still says nothing itself
    assert any("stop_loss_pct must be" in e for e in errs) and any("take_profit_pct" in e for e in errs)
    ns["write_protection_missing_packet"]("M1", sig, errs, source="buy")
    pkt = ns["PKTS"][-1]
    assert pkt["type"] == "protection_missing" and pkt["priority"] == "high"
    c = pkt["context"]
    assert c["sent_levels"] == {"stop_loss_pct": 99, "take_profit_pct": 2}
    assert "stop_loss_pct must be" in c["reason"] and c["originating_signal_id"] == "buy1"
    assert "default flip stop" in c["guard"]
    assert any("NOT armed" in l for l in ns["LOGS"])
    assert (ns["TMP"] / "protection_missing.jsonl").exists()


def test_valid_levels_arm_no_packet():
    ns = make_ns()
    ns["POS"]["M1"] = bag()
    errs = []
    ok = run(ns["execute_set_protection"]({"signal_id": "b", "mint": "M1", "stop_loss_pct": 20,
                                           "take_profit_pct": 50}, respond=False, errors_out=errs))
    assert ok and not errs and ns["POS"]["M1"]["armed_protection"]["sl_pct"] == 20


def test_buy_and_touch_branches_check_the_arm_result():
    body = SRC[SRC.index("async def process_signal("):]
    body = body[:body.index("\nasync def ", 10)]
    assert body.count("write_protection_missing_packet(") == 2
    assert not re.search(r"\n\s+await execute_set_protection\(sig, respond=False\)\n", body)


def test_default_flip_stop_sells_when_no_agent_stop():
    ns = make_ns()
    ns["POS"]["M1"] = bag()
    fired = run(ns["_check_armed_protection"]("M1", ns["POS"]["M1"], -21.0, {"stop_loss_pct": 20}, 0))
    assert fired and ns["SELLS"][0]["reason"] == "default_flip_stop" and ns["SELLS"][0]["amount_pct"] == 100.0
    assert ns["PKTS"][-1]["type"] == "protective_order_fired" and ns["PKTS"][-1]["context"]["landed"]
    assert ns["TG"] and "default flip stop" in ns["TG"][-1]


def test_default_stop_quiet_above_level_and_off_cases():
    ns = make_ns()
    ns["POS"]["M1"] = bag()
    assert not run(ns["_check_armed_protection"]("M1", ns["POS"]["M1"], -19.0, {"stop_loss_pct": 20}, 0))
    ns["POS"]["M2"] = bag(mode="hold")
    assert not run(ns["_check_armed_protection"]("M2", ns["POS"]["M2"], -50.0, {"stop_loss_pct": 20}, 0))
    ns["POS"]["M3"] = bag(own_launch=True)
    assert not run(ns["_check_armed_protection"]("M3", ns["POS"]["M3"], -50.0, {"stop_loss_pct": 20}, 0))
    ns["POS"]["M4"] = bag(armed_protection={"sl_pct": 30.0, "tp_pct": 60.0})   # agent stop wins
    assert not run(ns["_check_armed_protection"]("M4", ns["POS"]["M4"], -25.0, {"stop_loss_pct": 20}, 0))
    ns["PROTECT_DEFAULT_STOP"] = False
    ns["POS"]["M5"] = bag()
    assert not run(ns["_check_armed_protection"]("M5", ns["POS"]["M5"], -50.0, {"stop_loss_pct": 20}, 0))
    assert not ns["SELLS"]


def test_default_stop_respects_higher_cap_floor():
    ns = make_ns()
    ns["higher_cap_stop_floors"] = lambda mcap, mode="flip": (30.0, 0.0)
    ns["POS"]["M1"] = bag()
    assert not run(ns["_check_armed_protection"]("M1", ns["POS"]["M1"], -25.0, {"stop_loss_pct": 20}, 5e6))
    assert run(ns["_check_armed_protection"]("M1", ns["POS"]["M1"], -31.0, {"stop_loss_pct": 20}, 5e6))


def test_retries_exhausted_alert_once_agent_and_default():
    for armed in (True, False):
        ns = make_ns(sell_lands=False)
        ns["POS"]["M1"] = bag(armed_protection={"sl_pct": 20.0, "tp_pct": 60.0}) if armed else bag()
        for _ in range(5):
            assert run(ns["_check_armed_protection"]("M1", ns["POS"]["M1"], -40.0, {"stop_loss_pct": 20}, 0))
        assert len(ns["SELLS"]) == 5
        for _ in range(3):
            assert not run(ns["_check_armed_protection"]("M1", ns["POS"]["M1"], -40.0, {"stop_loss_pct": 20}, 0))
        ex = [p for p in ns["PKTS"] if p["type"] == "protective_order_exhausted"]
        assert len(ex) == 1 and ex[0]["priority"] == "high" and ex[0]["context"]["attempts"] == 5
        assert ex[0]["context"]["source"] == ("agent_armed" if armed else "default_flip_stop")
        assert sum("PROTECTIVE SELL FAILED" in m for m in ns["TG"]) == 1


def test_agent_armed_stop_unchanged():
    ns = make_ns()
    ns["POS"]["M1"] = bag(armed_protection={"sl_pct": 15.0, "tp_pct": 60.0})
    assert run(ns["_check_armed_protection"]("M1", ns["POS"]["M1"], -16.0, {"stop_loss_pct": 20}, 0))
    assert ns["SELLS"][0]["reason"] == "agent_armed_stop" and not ns["TG"]


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
