"""flip -> hold -> flip unit test for execute_convert_mode (+ moonbag guard), run against an engine
file WITHOUT importing it: the functions are lifted out with ast and run against in-memory stubs."""
import ast, asyncio, copy, sys, json

def run(path: str) -> dict:
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    want = {"execute_convert_mode", "write_moonbag_packet"}
    consts = {"FALLBACK_DEFAULTS", "FALLBACK_DEFAULTS_HOLD"}
    ns = {}
    nodes = [n for n in tree.body if (isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name in want)
             or (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in consts for t in n.targets))]
    state = {"pos": {}, "theses": {}, "resp": [], "tg": [], "moon": 0}
    import re as _re
    ns.update({
        "_re": _re, "DEFAULT_TRAIL_DROP_PCT": 12.0, "DEFAULT_TRAIL_ACTIVATE_PCT": 20.0,
        "DEFAULT_HOLD_TRAIL_DROP_PCT": 28.0, "DEFAULT_HOLD_TRAIL_ACTIVATE_PCT": 80.0, "DEFAULT_MAX_HOLD_MINUTES": 240,
        "PROTECT_SL_MIN_PCT": 1.0, "PROTECT_SL_MAX_PCT": 95.0, "PROTECT_TP_MIN_PCT": 1.0,
        "PIPE_FLOW_ENABLED": False, "TELEGRAM_ON_PARAM_REQUEST": False,
        "get_override_sync": lambda k, d: d, "_now_iso": lambda: "2026-10-14T23:00:00-04:00", "_now_ts": lambda: 0.0,
        "_short_mint": lambda m: m[:8], "_log": lambda *a, **k: None,
        "load_positions": lambda: copy.deepcopy(state["pos"]),
        "upsert_position": lambda m, p: state["pos"].__setitem__(m, copy.deepcopy(p)),
        "load_hold_theses": lambda: copy.deepcopy(state["theses"]),
        "save_hold_theses": lambda t: state.__setitem__("theses", copy.deepcopy(t)) or True,
        "get_hold_thesis": lambda m: state["theses"].get(m) or {},
        "score_to_band": lambda s: {"band": "gork-class", "raw_avg": 9.0, "rope": "max", "rescore_hours": 24,
                                     "auto_reject": False, "verdict": "ok", "load_bearing_fails": []},
        "build_market_weather": lambda: {}, "hold_doc_open": lambda *a, **k: None, "_hold_append": lambda *a, **k: None,
        "hold_timeline_add": lambda *a, **k: None, "_append_jsonl": lambda *a, **k: None, "HOLD_SCORE_LOG_FILE": "x",
        "load_gork_standard": lambda: {"criteria": []},
    })
    async def _resp(sid, status, **k): state["resp"].append((sid, status, k.get("error")))
    async def _tg(*a, **k): state["tg"].append(a[0] if a else "")
    ns["write_signal_response"], ns["send_telegram"] = _resp, _tg
    mod = ast.Module(body=nodes, type_ignores=[])
    exec(compile(mod, path, "exec"), ns)
    # write_moonbag_packet: only test its guard (stub everything after it by an exception sentinel)
    M = "MINT1"
    state["pos"][M] = {"mint": M, "ticker": "TST", "mode": "flip",
        "params": {"stop_loss_pct": 30.0, "tp_targets_pct": [100], "trail_drop_pct": 20.0, "trail_activate_pct": 20.0,
                   "partial_take_pct": 50, "partial_take_at_pct": 35, "max_hold_hours": 2, "mode": "flip"},
        "params_user_provided": ["stop_loss_pct", "tp_targets_pct", "trail_drop_pct", "max_hold_hours"],
        "armed_protection": {"sl_pct": 30.0, "tp_pct": 100.0, "tp_sell_pct": 50.0, "set_by": "agent"}}
    run_ = lambda sig: asyncio.run(ns["execute_convert_mode"](sig))
    r = {}
    run_({"signal_id": "h1", "mint": M, "new_mode": "hold", "thesis": "t", "falsifier": "f",
          "hold_score": {f"c{i}": 9 for i in range(1, 11)}})
    h = state["pos"][M]; hp = h["params"]
    r["hold_mode"] = h["mode"] == "hold"
    r["hold_keeps_agent_sl_tp"] = hp["stop_loss_pct"] == 30.0 and hp["tp_targets_pct"] == [100] and hp["max_hold_hours"] == 2
    r["hold_fills_unset"] = hp.get("partial_take_at_pct") == 100 and hp.get("trail_activate_pct") == 80.0 and "mcap_milestones_usd" in hp
    r["armed_synced_hold"] = (h["armed_protection"]["sl_pct"], h["armed_protection"]["tp_pct"]) == (30.0, 100.0)
    r["thesis_saved"] = M in state["theses"]
    run_({"signal_id": "f1", "mint": M, "new_mode": "flip", "reason": "test", "params": {"stop_loss_pct": 25}})
    f = state["pos"][M]; fp = f["params"]
    r["flip_mode"] = f["mode"] == "flip"
    r["flip_hold_rules_cleared"] = not any(k in fp for k in ("mcap_milestones_usd", "volume_decay_exit_pct", "holder_exodus_exit_pct"))
    r["flip_hold_record_cleared"] = M not in state["theses"] and "demoted_hold" in f
    r["flip_keeps_agent_levels"] = fp["tp_targets_pct"] == [100] and fp["max_hold_hours"] == 2 and fp["trail_drop_pct"] == 20.0
    r["flip_explicit_param_applied"] = fp["stop_loss_pct"] == 25 and f["params_source"].get("stop_loss_pct") not in (None, "mechanical")
    r["armed_synced_flip"] = (f["armed_protection"]["sl_pct"], f["armed_protection"]["tp_pct"]) == (25.0, 100.0)
    r["responses_executed"] = [s for _, s, _ in state["resp"]] == ["executed", "executed"]
    # moonbag guard: a demoted (flip) bag gets no moonbag packet even if a thesis lingers
    state["theses"][M] = {"band": "x"}
    try:
        asyncio.run(ns["write_moonbag_packet"](M, f, {"pnl_pct": 0.2}))
        r["no_moonbag_after_demote"] = True
    except Exception as e:      # the guard must return before touching any of the (unstubbed) folder code
        r["no_moonbag_after_demote"] = False; r["moon_err"] = str(e)[:120]
    return r

if __name__ == "__main__":
    res = run(sys.argv[1])
    print(json.dumps(res, indent=1))
    sys.exit(0 if all(v for k, v in res.items() if not k.endswith("_err")) else 1)
