"""agent_status + request-id echo tests, run against an engine file WITHOUT importing it."""
import ast, json, sys, tempfile
from pathlib import Path

def run(path: str) -> dict:
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    names = {"build_agent_status", "_status_tail_jsonl"}
    consts = {"AGENT_STATUS_INTERVAL_S", "_STATUS_FAIL_PREFIX", "_WARDEN_FOLLOWS_ENGINE"}
    nodes = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in names)
             or (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in consts for t in n.targets))]
    d = Path(tempfile.mkdtemp()); logs, relay = d / "bot_logs", d / "json_relay"
    logs.mkdir(); relay.mkdir()
    (relay / "agent_signals.json").write_text(json.dumps({"signals": [{"signal_id": "s1", "action": "buy"}]}))
    (relay / "ca_research_request.json").write_text(json.dumps({"requests": [{"request_id": "r1", "status": "done"},
                                                                             {"request_id": "r2"}]}))
    (logs / "agent_acks.jsonl").write_text(json.dumps({"ts": "t", "ack_of": {"signal_id": "s0", "request_id": "s0",
                                                         "signal_type": "agent_signal"}, "stage": "applied", "result": "ok"}) + "\n")
    hist = logs / "signals_response_history.jsonl"
    hist.write_text(json.dumps({"signal_id": "bad1", "request_id": "bad1", "status": "rejected", "error": "unknown_action"}) + "\n"
                    + json.dumps({"signal_id": "ok1", "status": "executed"}) + "\n")
    (logs / "warden_config.json").write_text(json.dumps({"bounds": {"memes": {"max_buy_sol": 0.1}}}))
    ns = {"json": json, "_BOT_LOGS": logs, "_JSON_RELAY": relay, "SIGNALS_RESPONSE_HISTORY_LOG": hist,
          "_now_ts": lambda: 1.0, "_now_iso": lambda: "2026-10-14T23:30:00-04:00", "PAPER_MODE": False,
          "SIZE_CAP_BASE_SOL": 1.0, "get_override_sync": lambda k, dflt: dflt, "_base_size_cap": lambda: 1.0,
          "load_positions": lambda: {"M1": {"ticker": "TST", "mode": "hold", "amount_sol": 0.1,
                                            "armed_protection": {"sl_pct": 30.0, "tp_pct": 100.0},
                                            "params": {"stop_loss_pct": 30.0}}}}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, "exec"), ns)
    st = ns["build_agent_status"]()
    r = {}
    r["status_schema"] = st.get("schema") == "agent_status_v1" and st.get("trading") == "live"
    r["status_positions"] = st["open_positions"][0]["mode"] == "hold" and st["open_positions"][0]["armed_sl_pct"] == 30.0
    r["status_pending"] = {p["file"]: p["request_ids"] for p in st["pending_relay_requests"]} == {
        "agent_signals.json": ["s1"], "ca_research_request.json": ["r2"]}
    r["status_acks"] = st["last_acks"] and st["last_acks"][-1]["request_id"] == "s0"
    r["status_failures"] = [f["request_id"] for f in st["last_failures"]] == ["bad1"]
    r["status_bound"] = st["sizing"]["warden_meme_bound_sol"] in (1.0, 0.1) and st["sizing"]["engine_base_cap_sol"] == 1.0
    r["status_written_by_loop"] = ('SupervisedTask("agent_status", agent_status_loop)' in src
                                   and "_save_json_atomic(AGENT_STATUS_FILE" in src)
    r["echo_response_history"] = '"request_id": signal_id,          # same id echoed' in src
    r["echo_ack_packet"] = '"request_id": signal_id,      # the signal_id / id you sent' in src
    r["echo_inbox_generic"] = 'packet["request_id"] = _rid' in src
    r["echo_discovery"] = 'resp["request_id"] = q.get("request_id")' in src
    r["echo_ca_rows"] = '"request_id": req.get("request_id"),' in src
    return r

if __name__ == "__main__":
    res = run(sys.argv[1]); print(json.dumps(res, indent=1)); sys.exit(0 if all(res.values()) else 1)
