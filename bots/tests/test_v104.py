"""v1.0.4: celeb-post rule (FLOYD replay), scale-in, exit-type resolver,
post-exit row match, monitor watchdog. No RPC, no network.
FLOYD facts from public reporting (trenchbook dispatch, 2026-10-13)."""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sub-bots"))
import celeb_post as cp      # noqa: E402
import scale_in as si        # noqa: E402
import exit_log as xl        # noqa: E402
import monitor_watchdog as mw  # noqa: E402

# 13 Oct 2026 ET -> UTC epochs (ET = UTC-4)
def et(h, m, s=0):
    return datetime(2026, 10, 13, h + 4, m, s, tzinfo=timezone.utc).timestamp()

FLOYD_POST = {"handle": "FloydMayweather", "followers": 6_800_000, "verified": True,
              "post_id": "2110070647737155629", "posted_ts": et(14, 10, 20)}
FUJB = "FuJB...3yR2"


def floyd_facts(**o):
    f = {"creator": FUJB, "launch_ts": et(13, 3, 38),
         # funded 2.499 SOL ~5 min pre-launch by a wallet paying several wallets in one tx
         "funders": [{"wallet": "busy...fund", "recipients_in_tx": 5, "ts": et(12, 58, 30)}],
         # same creator launched $MONEY at 3:50:50 PM
         "cluster_launches": [{"mint": "MONEY...pump", "ts": et(15, 50, 50), "by": FUJB}],
         "creator_balance_pct": 0.0}
    f.update(o)
    return f


def test_floyd_vetoed_fanout_funder():
    r = cp.evaluate(FLOYD_POST, floyd_facts(), now_ts=et(15, 45))
    assert r["veto"] and not r["enter"] and "fan-out" in r["reason"]


def test_floyd_vetoed_second_coin_even_without_fanout():
    r = cp.evaluate(FLOYD_POST, floyd_facts(funders=[]), now_ts=et(16, 0))
    assert r["veto"] and "cluster" in r["reason"]


def test_clean_celeb_waits_then_enters():
    clean = floyd_facts(funders=[{"wallet": "cex", "recipients_in_tx": 1, "ts": et(12, 0)}],
                        cluster_launches=[], creator_balance_pct=6.6)
    assert cp.evaluate(FLOYD_POST, clean, now_ts=et(14, 20))["wait"]
    clean["creator_balance_pct"] = 0.0
    assert cp.evaluate(FLOYD_POST, clean, now_ts=et(15, 45))["enter"]


def test_celeb_fail_safe_and_gates(monkeypatch):
    assert not cp.evaluate(FLOYD_POST, None, now_ts=et(15, 0))["enter"]
    assert not cp.evaluate(FLOYD_POST, floyd_facts(funders=None), now_ts=et(15, 0))["enter"]
    assert not cp.evaluate(FLOYD_POST, floyd_facts(funders=[], cluster_launches=None), now_ts=et(15, 0))["enter"]
    assert not cp.evaluate({**FLOYD_POST, "verified": False}, floyd_facts(), now_ts=et(15, 0))["enter"]
    assert not cp.evaluate({**FLOYD_POST, "followers": 1000}, floyd_facts(), now_ts=et(15, 0))["enter"]
    assert "too old" in cp.evaluate(FLOYD_POST, floyd_facts(), now_ts=et(19, 0))["reason"]
    monkeypatch.setenv("CELEB_POST_RULE", "false")
    assert cp.evaluate(FLOYD_POST, floyd_facts(), now_ts=et(15, 0))["reason"] == "CELEB_POST_RULE off"


def test_celeb_exits_and_size(monkeypatch):
    p = cp.exit_params()
    assert (p["stop_loss_pct"], p["partial_take_at_pct"], p["partial_take_pct"], p["trail_drop_pct"]) == (25, 200, 50, 35)
    assert cp.entry_size_sol() == 0.1
    monkeypatch.setenv("CELEB_ENTRY_SOL", "0.2")
    assert cp.entry_size_sol() == 0.2


def test_fanout_counter():
    tx = {"transaction": {"message": {"instructions": [
        {"parsed": {"type": "transfer", "info": {"source": "F", "destination": d, "lamports": 2_499_000_000}}}
        for d in ("a", "b", "c", "d")]}}}
    assert cp._sol_out_recipients(tx, "F") == 4


def test_scale_in_plan(monkeypatch):
    assert si.plan(0.2, {}) == {"first": 0.05, "add": 0.15}
    assert si.plan(0.04, {}) is None
    assert si.plan(0.2, {"_scale_in_leg": "add"}) is None
    assert si.plan(0.2, {"params": {"fee_vault": {"wallet": "x"}}}) is None
    assert si.plan(0.2, {"params": {"celeb_post": {}}}) is None
    monkeypatch.setenv("SCALE_IN", "false")
    assert si.plan(0.2, {}) is None


def test_scale_in_add_ok():
    pos = {"entry_price": 1.0, "scale_in": {"liq_at_entry": 10000}}
    assert si.add_ok(pos, 9000, 1.1)[0]
    assert not si.add_ok(pos, 7000, 1.1)[0]            # pool pulled
    assert not si.add_ok(pos, 9000, 0.8)[0]            # price dumped
    assert not si.add_ok(pos, None, 1.1)[0]            # fail safe
    assert not si.add_ok(None, 9000, 1.1)[0]
    assert not si.add_ok({**pos, "partial_taken": True}, 9000, 1.1)[0]


def test_exit_type_resolver_agrees():
    pos = {"last_monitor_trigger": "trail_drop"}
    assert xl.resolve_exit_type(pos, {}) == "trail_drop"
    assert xl.resolve_exit_type(pos, {}, {}) == xl.resolve_exit_type(pos, {})
    assert xl.resolve_exit_type({"exit_reason": "sl_hit", **pos}, {"trigger": "agent_sell"}) == "sl_hit"
    assert xl.resolve_exit_type({}, {"exit_trigger": {"type": "vault_moved"}}) == "vault_moved"
    assert xl.resolve_exit_type({}, {}) == "unknown_exit"


def test_post_exit_row_match():
    to_ts = lambda s: datetime.fromisoformat(s).timestamp()
    t0 = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
    rows = [{"mint": "M", "exit_at": (t0 + timedelta(hours=2)).isoformat(), "exit_tx": "T1"}]
    assert xl.pick_autopsy_row(rows, "M", t0.timestamp(), "T1", to_ts) is rows[0]
    assert xl.pick_autopsy_row(rows, "M", t0.timestamp(), None, to_ts) is rows[0]  # lone row, <6h
    assert xl.pick_autopsy_row(rows + [{"mint": "M", "exit_at": (t0 + timedelta(hours=5)).isoformat()}],
                               "M", t0.timestamp(), None, to_ts) is None


def test_watchdog():
    now = datetime(2026, 10, 24, 12, tzinfo=timezone.utc).timestamp()
    iso = lambda s: datetime.fromtimestamp(now - s, tz=timezone.utc).isoformat()
    hb = {"components": {"position_monitor": {"last_update": iso(600)}}}
    pos = {"M": {"ticker": "X"}}
    assert mw.check(hb, pos, now)["stale"]
    assert not mw.check(hb, {}, now)["stale"]
    assert not mw.check({"components": {"position_monitor": {"last_update": iso(30)}}}, pos, now)["stale"]
    assert mw.check({}, pos, now)["stale"]                 # no beat = alert
    wd, sent = mw.Watchdog(), []
    r = mw.check(hb, pos, now)
    assert wd.step(r, now) and wd.step(r, now + 60) is None       # no spam
    assert wd.step(r, now + 1900)                                  # re-alert
    assert "recovered" in wd.step({"stale": False, "open": 1}, now + 2000)
