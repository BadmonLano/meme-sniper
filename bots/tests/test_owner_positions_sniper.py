"""Offline tests for the sniper owner-position flow. No network, no wallet.
Extracts the OWNER POSITIONS block from meme_sniper.py and runs it on stubs.
Run: python test_owner_positions_sniper.py <path to meme_sniper.py>"""
import asyncio, json, os, sys, tempfile, time
from pathlib import Path
src = open(sys.argv[1], encoding="utf-8").read()
a = src.index("# ── OWNER POSITIONS (2026-10-15)")
b = src.index("async def execute_promote_holding(sig: dict) -> None:")
tmp = Path(tempfile.mkdtemp())
OPEN, HOLD, NOTES, PKTS, RESP = set(), {}, [], [], []
async def send_telegram(m, **k): NOTES.append(m)
POS, RPC, RPC_CALLS = {}, {"value": []}, []
async def execute_promote_holding(sig): OPEN.add(sig["mint"]); POS[sig["mint"]] = {"mint": sig["mint"]}
async def helius_rpc(method, params): RPC_CALLS.append((method, params[1]["programId"])); return RPC
async def fetch_token_data(m): return {"priceUsd": "0.5", "baseToken": {"symbol": "LITE"}}
def _save_holdings(d): d = dict(d); HOLD.clear(); HOLD.update(d)
async def write_signal_response(sid, status, **k): RESP.append((sid, status, k))
def _save_json_atomic(p, d): open(p, "w").write(json.dumps(d))
ns = {"os": os, "json": json, "asyncio": asyncio, "Path": Path, "_BOT_LOGS": tmp,
      "_save_json_atomic": _save_json_atomic, "_log": lambda *a, **k: None,
      "_now_iso": lambda: time.strftime("%Y-%m-%dT%H:%M:%S"), "_now_ts": time.time,
      "EXEC_LEDGER_FILE": tmp / "execution_ledger.jsonl", "_STABLECOIN_MINTS": {"USDCmint": "USDC"},
      "write_inbox_packet_generic": lambda pkt, **k: PKTS.append(pkt), "send_telegram": send_telegram,
      "execute_promote_holding": execute_promote_holding, "_read_open_position_mints": lambda: OPEN,
      "_load_holdings": lambda: HOLD, "write_signal_response": write_signal_response,
      "load_positions": lambda: POS, "upsert_position": lambda m, p: POS.__setitem__(m, p),
      "_save_holdings": _save_holdings, "helius_rpc": helius_rpc, "fetch_token_data": fetch_token_data,
      "_safe_num": lambda v: float(v) if v not in (None, "") else None, "_WSOL_MINT": "WSOLmint",
      "HOT_WALLET_ADDR": "WALLET"}
import os as _os; ns.setdefault("os", _os); _h = src.index("def _envv("); exec(src[_h:src.index("\n\n", _h)], ns)  # blank-as-unset helper used by the extracted code
exec(src[a:b], ns)
with open(tmp / "execution_ledger.jsonl", "w") as f:
    f.write(json.dumps({"event": "buy", "mint": "BOTMINT111"}) + "\n")
def ev(): return [json.loads(l)["event"] for l in open(tmp / "owner_positions.jsonl")]
async def main():
    h = lambda t, usd: {"ticker": t, "est_usd": usd, "amount_ui": 1000, "class": "watch_bag"}
    await ns["_owner_pos_scan"]({}, {"OLDMINT111": h("OLD", 500)})                  # baseline
    assert not PKTS and ns["_owner_pos_state"]()["baseline_done"]
    cur = {"OLDMINT111": h("OLD", 500), "NEWMINT111": h("PEPE", 50), "BOTMINT111": h("BOT", 50),
           "DUSTMINT11": h("DUST", 2), "USDCmint": {"ticker": "USDC", "est_usd": 99, "class": "stablecoin"}}
    HOLD.update(cur)
    await ns["_owner_pos_scan"]({"OLDMINT111": cur["OLDMINT111"]}, cur)
    assert [p["ticker"] for p in PKTS] == ["PEPE"], PKTS                          # only the owner bag
    assert "I see a $50 PEPE position I didn't open" in NOTES[-1]
    rec = ns["_owner_pos_state"]()["records"]["NEWMINT111"]
    assert rec["tag"] == "owner_position" and rec["source"] == "unknown" and rec["state"] == "pending"
    # /leave pepe (case-insensitive) via the decisions file
    with open(tmp / "owner_position_decisions.jsonl", "a") as f:
        f.write(json.dumps({"ts": time.time(), "target": "PePe", "decision": "leave"}) + "\n")
    t = asyncio.create_task(ns["owner_position_loop"]()); await asyncio.sleep(0.2); t.cancel()
    assert ns["_owner_pos_state"]()["records"]["NEWMINT111"]["state"] == "leave" and "NEWMINT111" not in OPEN
    # second bag: relay manage
    cur["WIFMINT111"] = h("WIF", 80); HOLD.update(cur)
    await ns["_owner_pos_scan"](dict(cur, WIFMINT111=None) and {k: v for k, v in cur.items() if k != "WIFMINT111"}, cur)
    rid = ns["_owner_pos_state"]()["records"]["WIFMINT111"]["id"]
    await ns["execute_owner_position_signal"]({"signal_id": "s1", "id": rid, "decision": "manage"})
    assert "WIFMINT111" in OPEN and RESP[-1][1] == "executed"
    # third bag: timeout -> auto-manage
    cur["BONKMINT11"] = h("BONK", 30); HOLD.update(cur)
    await ns["_owner_pos_scan"]({k: v for k, v in cur.items() if k != "BONKMINT11"}, cur)
    st = ns["_owner_pos_state"](); st["records"]["BONKMINT11"]["detected_ts"] -= 31 * 60; ns["_owner_pos_save"](st)
    t = asyncio.create_task(ns["owner_position_loop"]()); await asyncio.sleep(0.2); t.cancel()
    assert "BONKMINT11" in OPEN and ns["_owner_pos_state"]()["records"]["BONKMINT11"]["state"] == "managed"
    # tweak 1: taken-over positions skip the max-hold exit by default
    assert ns["OWNER_POS_TIME_EXIT"] is False
    assert POS["WIFMINT111"].get("owner_no_time_exit") and POS["BONKMINT11"].get("owner_no_time_exit")
    assert 'and not position.get("owner_no_time_exit"):' in src
    assert ns["OWNER_POS_SCAN_MIN"] == 5
    # tweak 2: light check, one RPC call per run, programs alternate
    class _A:      # instant sleep for the 60 s booking grace
        sleep = staticmethod(lambda s: asyncio.sleep(0))
    ns["asyncio"] = _A
    acct = lambda m, ui: {"account": {"data": {"parsed": {"info": {"mint": m, "tokenAmount": {"uiAmount": ui}}}}}}
    RPC["value"] = [acct("OLDMINT111", 9), acct("WSOLmint", 3), acct("BOTMINT111", 5), acct("LITEMINT11", 100),
                    acct("TINYMINT11", 1)]
    RPC_CALLS.clear()
    n = await ns["_owner_pos_light_check"]()
    assert n == 1 and len(RPC_CALLS) == 1, (n, RPC_CALLS)
    r = ns["_owner_pos_state"]()["records"]["LITEMINT11"]
    assert r["via"] == "light_check" and r["est_usd"] == 50 and r["ticker"] == "LITE"
    assert "I see a $50 LITE position I didn't open" in NOTES[-1]
    assert await ns["_owner_pos_light_check"]() == 0 and len(RPC_CALLS) == 2
    assert RPC_CALLS[0][1] != RPC_CALLS[1][1]                      # SPL then Token-2022
    # light-found bag not on the ledger yet: manage adds a holdings row, then promotes
    assert "LITEMINT11" not in HOLD
    await ns["execute_owner_position_signal"]({"signal_id": "s2", "id": r["id"], "decision": "manage"})
    assert "LITEMINT11" in HOLD and "LITEMINT11" in OPEN and POS["LITEMINT11"]["owner_no_time_exit"]
    for e in ("detected", "decision", "take_over", "timeout"):
        assert e in ev(), (e, ev())
    print("owner positions sniper: all tests passed")
asyncio.run(main())
