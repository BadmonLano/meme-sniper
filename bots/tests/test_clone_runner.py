"""Clone runner promotion rules (meme_sniper). Usage: python test_clone_runner.py [path\\to\\meme_sniper.py]"""
import json, os, sys, tempfile, asyncio
from pathlib import Path
from typing import Optional
here = Path(__file__).resolve().parent
cands = [Path(sys.argv[1])] if len(sys.argv) > 1 else [here / "meme_sniper.py", here.parent / "meme_sniper.py"]
src_path = next(p for p in cands if p.exists())
src = src_path.read_text(encoding="utf-8")
a = src.index("# ── CLONE RUNNER (2026-10-15"); b = src.index("def _clone_gate(", a)
tmp = Path(tempfile.mkdtemp())
NOW = [1_000_000.0]
ns = {"os": os, "json": json, "asyncio": asyncio, "Optional": Optional, "_BOT_LOGS": tmp,
      "_BRAND_CANON_FILE": tmp / "brand_canonical.json",
      "_now_iso": lambda: "T", "_now_ts": lambda: NOW[0], "_short_mint": lambda m: m[:4],
      "_log": lambda *a, **k: None, "fetch_token_data": None,
      "_safe_num": lambda v: float(v) if v not in (None, "") else None,
      "_save_json_atomic": lambda p, d: Path(p).write_text(json.dumps(d))}
import os as _os; ns.setdefault("os", _os); _h = src.index("def _envv("); exec(src[_h:src.index("\n\n", _h)], ns)  # blank-as-unset helper used by the extracted code
exec(src[a:b], ns)
ok = 0
def check(c, m):
    global ok
    assert c, m; ok += 1; print("PASS", m)
def pkt(vol=30000, liq=20000, v1=0, verdict="clean", vibe="bullish", canon_vol=10000, canon_liq=15000, k1=0):
    return {"context": {"brand_resolution": {"ticker": "x", "is_canonical": False, "canonical_mint": "CANON",
            "candidates": [{"mint": "CANON", "volume_24h": canon_vol, "liquidity_usd": canon_liq, "volume_1h": k1}]},
            "dex_data": {"volume_24h": vol, "liquidity_usd": liq, "volume_1h": v1, "mcap": 100000},
            "rug_check": {"smart_check_verdict": verdict}, "social_sentiment": {"overall_vibe": vibe}},
            "agent_card": {"headline": "X", "flags": []}}
E = ns["_clone_runner_eval"]; st = lambda: json.loads((tmp / "clone_runner_state.json").read_text())
check(E(pkt(), "M1") is None and "M1" in st(), "qualifying clone starts the sustain clock, no runner yet")
NOW[0] += 59 * 60; check(E(pkt(), "M1") is None, "not promoted before RUNNER_SUSTAIN_MIN")
NOW[0] += 61; r = E(pkt(), "M1")
check(r and r["vol_ratio"] == 3.0 and r["canonical_mint"] == "CANON" and r["since"], "promoted after 60m sustained")
log = (tmp / "clone_runners.jsonl").read_text().splitlines()
check(len(log) == 1 and json.loads(log[0])["event"] == "promoted", "promotion logged once")
E(pkt(), "M1"); check(len((tmp / "clone_runners.jsonl").read_text().splitlines()) == 1, "no duplicate promotion row")
NOW[0] += 2 * 86400
E(pkt(vol=29000), "M2"); check("M2" not in st(), "vol 2.9x does not qualify")
E(pkt(liq=15000), "M3"); check("M3" not in st(), "liquidity must be ABOVE canonical")
E(pkt(), "M4"); NOW[0] += 3601; E(pkt(vol=1000), "M4"); check("M4" not in st(), "sustain resets when it stops qualifying")
E(pkt(v1=3000, k1=2000, vol=100), "M5"); check("M5" not in st(), "1h ratio used when both 1h volumes exist (1.5x fails)")
E(pkt(v1=6000, k1=2000, vol=100), "M6"); check("M6" in st(), "1h ratio 3x qualifies even if 24h is low")
for m, kw, why in [("M7", {"verdict": "caution"}, "rug caution blocks"), ("M8", {"verdict": "data_unavailable"}, "rug unavailable blocks"),
                   ("M9", {"vibe": "dead"}, "dead socials block"), ("MA", {"vibe": "unknown"}, "unknown socials block")]:
    E(pkt(**kw), m); NOW[0] += 3700; check(E(pkt(**kw), m) is None, why); NOW[0] -= 3700
p = pkt(); p["context"]["brand_resolution"]["is_canonical"] = True
check(E(p, "MB") is None, "canonical itself is never a runner")
p = pkt(); ns["_clone_runner_mark"](p, r)
check(p["context"]["runner"]["canonical_mint"] == "CANON" and p["context"]["card_label"] == "Clone Running"
      and p["agent_card"]["headline"].startswith("CLONE RUNNING") and "No buy bypass" in p["agent_card"]["flags"][0], "card marked Clone Running with context.runner")
check(ns["_clone_runner_flags"]("M1", 12.0).get("clone_runner") is True and ns["_clone_runner_flags"]("M2") == {}, "autopsy flags only for promoted runners")
rv = ns["_clone_runner_review"](); check(rv["promoted"] == 1 and rv["hit_rate_pct"] is None, "review summary written")
for k in ("_score", "_brand_canon_stable"):
    check(k not in src[a:b], f"runner block does not touch {k}")
print(f"ALL {ok} PASSED")
