"""v1.0.7: replays of the Oct 2026 six-token review (BTC, CATTLEAXE, REMUS, LTC, NIO, ETH).
No network: real numbers from the Helius/DexScreener/GeckoTerminal probe are inlined."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import v107_rules as r  # noqa: E402

BTC = "C5xph2yL6gMdxmuLGxJBkGpmuDFfyi5fqkBNhvL6pump"
CATTLE = "H7VZNCBynDK5ikBS9krDJ2Tx8CUr1wxedV19ZgkWpump"
REMUS = "CA8q2mkYWZnUNqYmf6pxyxAPZsmSe2EG9P7hHMW5pump"
LTC = "DffdPtAKvnP91k9Ct6QvZ8TwVvWbJ6CxRtGNGNh9pump"
LTC_OG = "4kTH64xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxpump"
NIO = "7SL2VnfYsChvog5oQY9Nmtqu1wceaMiQzWoqoLQpump"
ETH = "CXWNzqBE98SSmkGgHogJZd9vjsLdgaMAFpVfV22ypump"


# ── 1. fast trending lane ───────────────────────────────────────────────────
def _apps(ranks, step=900, t0=1_800_000_000):
    return [{"ts": t0 + i * step, "rank": k} for i, k in enumerate(ranks)]


def test_cattleaxe_top3_for_an_hour_is_candidate(monkeypatch):
    monkeypatch.delenv("TREND_FAST", raising=False)
    e = {"appearances": _apps([2, 1, 1, 2, 1])}          # 5 scans x 15m = 1h at #1-2
    assert r.trend_fast(e, e["appearances"][-1]["ts"])


def test_not_candidate_under_an_hour_or_outside_top3(monkeypatch):
    assert not r.trend_fast({"appearances": _apps([1, 1, 2])})            # 30 min
    assert not r.trend_fast({"appearances": _apps([1, 2, 5, 1, 2])})      # broke top 3
    assert not r.trend_fast({"appearances": _apps([1, 1, 1, 1, 1], step=3600)})  # gaps
    monkeypatch.setenv("TREND_FAST", "false")
    assert not r.trend_fast({"appearances": _apps([2, 1, 1, 2, 1])})


# ── 2. clone gate ───────────────────────────────────────────────────────────
def test_ltc_runner_passes_clone_gate(tmp_path, monkeypatch):
    monkeypatch.delenv("CLONE_RUNNER_OVERRIDE", raising=False)
    ctx = {"dex_data": {"mcap": 7_704_764}}
    br = {"canonical_mint": LTC_OG, "candidates": [{"mint": LTC_OG, "mcap": 40_000}]}
    assert r.clone_override(ctx, br, LTC).startswith("runner_mcap")
    ctx = {"dex_data": {"mcap": 120_000}}
    assert r.clone_override(ctx, br, LTC).startswith("runner_vs_original")
    mb = tmp_path / "miss_book.jsonl"
    mb.write_text(json.dumps({"mint": LTC}) + "\n")
    br2 = {"canonical_mint": LTC_OG, "candidates": [{"mint": LTC_OG, "mcap": 900_000}]}
    assert r.clone_override(ctx, br2, LTC, mb) == "on_miss_book"
    assert r.clone_override(ctx, br2, LTC, tmp_path / "none.jsonl") is None
    monkeypatch.setenv("CLONE_RUNNER_OVERRIDE", "false")
    assert r.clone_override({"dex_data": {"mcap": 9e6}}, br, LTC) is None


# ── 3. expired card fallback ────────────────────────────────────────────────
def test_expired_card_fallback(tmp_path, monkeypatch):
    for k in ("EXPIRED_CARD_FALLBACK", "EXPIRED_CARD_FALLBACK_SOL", "EXPIRED_CARD_FALLBACK_ALLOW_CAUTION"):
        monkeypatch.delenv(k, raising=False)
    pkt = {"context": {"mint": LTC, "ticker": "LTC", "rug_check": {"smart_check_verdict": "clean"}}}
    out = r.expired_fallback(pkt, 1_800_000_000)
    assert out["buy"] and out["signal"]["amount_sol"] == 0.05 and out["signal"]["_v107_small"]
    f = tmp_path / "agent_signals.json"
    r.append_signal(f, out["signal"]); r.append_signal(f, out["signal"])
    assert len(json.loads(f.read_text())["signals"]) == 2
    pkt["context"]["rug_check"]["smart_check_verdict"] = "caution"
    assert not r.expired_fallback(pkt)["buy"]
    monkeypatch.setenv("EXPIRED_CARD_FALLBACK_ALLOW_CAUTION", "true")
    assert r.expired_fallback(pkt)["buy"]
    pkt["context"]["rug_check"]["smart_check_verdict"] = "block"
    assert r.expired_fallback(pkt)["reason"] == "rug_check_not_clean:block"
    monkeypatch.setenv("EXPIRED_CARD_FALLBACK", "false")
    assert r.expired_fallback(pkt)["reason"] == "off_switch"


# ── 4. parody lane ──────────────────────────────────────────────────────────
def test_parody_lane_alerts_only(tmp_path, monkeypatch):
    monkeypatch.delenv("PARODY_LANE", raising=False)
    for m, t in ((BTC, "BTC"), (LTC, "LTC"), (ETH, "ETH"), (NIO, "NIO")):
        assert r.parody_match(t, m) == t
    assert r.parody_match("CATTLEAXE", CATTLE) is None
    f = tmp_path / "parody.json"
    assert r.parody_alert(f, ETH, "ETH", rank=2)
    assert not r.parody_alert(f, ETH, "ETH", rank=1)        # dedup
    row = json.loads(f.read_text())["alerts"][ETH]
    assert row["decision"] == "alert_only"
    monkeypatch.setenv("PARODY_LANE", "false")
    assert r.parody_match("BTC", BTC) is None


# ── 5. X profile fill ───────────────────────────────────────────────────────
def test_x_profile_fill_and_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("X_PROFILE_FILL", raising=False)
    calls = []
    def fake(h):
        calls.append(h)
        return {"data": {"public_metrics": {"followers_count": 12_345},
                         "created_at": "2020-10-25T00:00:00Z", "verified": False}}
    c = tmp_path / "xc.json"
    now = 1_792_900_000   # 2026-10
    a = r.x_profile("@SomeCoin", c, fetch=fake, now_ts=now)
    b = r.x_profile("somecoin", c, fetch=fake, now_ts=now + 60)
    assert a["followers"] == 12_345 and a["age_days"] > 2000 and a["source"] == "x_api"
    assert b["source"] == "cache" and b["followers"] == 12_345 and len(calls) == 1
    assert "Bearer" not in c.read_text()
    monkeypatch.setenv("X_PROFILE_FILL", "false")
    assert r.x_profile("x", c, fetch=fake)["followers"] is None


# ── 6. ticker mislabel ──────────────────────────────────────────────────────
def test_btc_not_labelled_ltc():
    # DexScreener /tokens/<BTC> returned the LTC/BTC pair (BTC on the quote side) first.
    pairs = [
        {"baseToken": {"address": LTC, "symbol": "LTC"}, "quoteToken": {"address": BTC, "symbol": "BTC"},
         "liquidity": {"usd": 900_000}},
        {"baseToken": {"address": BTC, "symbol": "BTC"}, "quoteToken": {"symbol": "WBTC"},
         "liquidity": {"usd": 502_805}},
    ]
    assert r.base_ticker(pairs, BTC) == "BTC"
    assert r.base_ticker(pairs[:1], BTC) == "BTC"   # only quote-side: still its own symbol
    e = {"ticker": "LTC"}
    assert r.heal_ticker(e, "BTC") and e["ticker"] == "BTC" and e["ticker_prev"] == "LTC"
    assert not r.heal_ticker(e, "?")


# ── 7. bundle check ─────────────────────────────────────────────────────────
REPLAY = {   # Helius probe, first 100 txs of each mint (Oct 25 2026)
    "BTC":       {"ok": True, "dev": "D", "dev_pct": 33.76, "bundle_wallets": 5, "bundle_pct": 40.58,
                  "bundle_sold_pct": 1.2, "wallets": ["D", "a", "b", "c", "d"]},
    "CATTLEAXE": {"ok": True, "dev": "D", "dev_pct": 0.35, "bundle_wallets": 5, "bundle_pct": 27.52,
                  "bundle_sold_pct": 0.0, "wallets": ["D", "a", "b", "c", "d"]},
    "REMUS":     {"ok": True, "dev": "D", "dev_pct": 0.0, "bundle_wallets": 6, "bundle_pct": 55.54,
                  "bundle_sold_pct": 22.1, "wallets": ["a", "b", "c", "d", "e", "f"]},
    "LTC":       {"ok": True, "dev": "D", "dev_pct": 2.18, "bundle_wallets": 1, "bundle_pct": 2.18,
                  "bundle_sold_pct": 100.0, "wallets": ["D"]},
}


def test_bundled_runners_reduce_not_block(monkeypatch):
    for k in ("BUNDLE_CHECK", "BUNDLE_REDUCE_PCT", "BUNDLE_SIZE_MULT", "BUNDLE_BLOCK_ON_DUMP"):
        monkeypatch.delenv(k, raising=False)
    for t in ("BTC", "CATTLEAXE", "REMUS"):     # all three kept running after bond
        d = r.bundle_decision(REPLAY[t])
        assert d["action"] == "reduce" and d["size_mult"] == 0.5, t
        assert d["exit_overrides"]["stop_loss_pct"] == 15 and d["flag"]
    assert r.bundle_decision(REPLAY["LTC"])["action"] == "normal"


def test_bundle_blocks_only_on_dump(monkeypatch):
    monkeypatch.delenv("BUNDLE_BLOCK_ON_DUMP", raising=False)
    d = r.bundle_decision(REPLAY["REMUS"], still_held_pct=10, price_drawdown_pct=55)
    assert d["action"] == "block"
    # sold but chart still up = profit window, not a rug
    assert r.bundle_decision(REPLAY["REMUS"], still_held_pct=10, price_drawdown_pct=5)["action"] == "reduce"
    monkeypatch.setenv("BUNDLE_BLOCK_ON_DUMP", "false")
    assert r.bundle_decision(REPLAY["REMUS"], 10, 55)["action"] == "reduce"
    monkeypatch.setenv("BUNDLE_CHECK", "false")
    assert r.bundle_decision(REPLAY["REMUS"], 10, 55)["action"] == "normal"


def _tx(slot, signer, owner_deltas, mint, bt):
    pre, post = [], []
    for i, (o, (a, b)) in enumerate(owner_deltas.items()):
        pre.append({"accountIndex": i, "mint": mint, "owner": o, "uiTokenAmount": {"uiAmount": a}})
        post.append({"accountIndex": i, "mint": mint, "owner": o, "uiTokenAmount": {"uiAmount": b}})
    return {"slot": slot, "blockTime": bt, "transaction": {"message": {"accountKeys": [{"pubkey": signer}]}},
            "meta": {"err": None, "preTokenBalances": pre, "postTokenBalances": post}}


def test_analyze_bundle_same_slot():
    m = REMUS
    txs = [_tx(100, "dev", {"dev": (0, 0)}, m, 1000),
           _tx(100, "w1", {"w1": (0, 300e6)}, m, 1000),
           _tx(101, "w2", {"w2": (0, 200e6)}, m, 1000),
           _tx(110, "late", {"late": (0, 50e6)}, m, 1004),
           _tx(111, "w1", {"w1": (300e6, 150e6)}, m, 1005),
           _tx(120, r.PUMP_MIGRATOR, {}, m, 1040)]
    a = r.analyze_bundle(txs, m)
    assert a["bundle_wallets"] == 2 and a["bundle_pct"] == 50.0
    assert a["bundle_sold_pct"] == 30.0 and a["bond_seconds"] == 40


def test_bundle_check_one_call_cached(monkeypatch):
    monkeypatch.delenv("BUNDLE_CHECK", raising=False)
    n = []
    async def rpc(method, params):
        n.append(method)
        return {"data": [_tx(5, "dev", {"dev": (0, 0)}, CATTLE, 1),
                         _tx(5, "w", {"w": (0, 280e6)}, CATTLE, 1)]}
    r._BUNDLE_CACHE.clear()
    d1 = asyncio.run(r.bundle_check(CATTLE, rpc))
    d2 = asyncio.run(r.bundle_check(CATTLE, rpc))
    assert d1["action"] == d2["action"] == "reduce" and n == ["getTransactionsForAddress"]


# ── coverage ────────────────────────────────────────────────────────────────
def test_gecko_trending_feeds_pump_mints(monkeypatch):
    monkeypatch.delenv("COVERAGE_GECKO", raising=False)
    body = {"data": [
        {"attributes": {"name": "ETH / SOL"}, "relationships": {"base_token": {"data": {"id": "solana_" + ETH}}}},
        {"attributes": {"name": "BIRB / USDC"}, "relationships": {"base_token": {"data": {"id": "solana_G7vQWuNotPump"}}}},
        {"attributes": {"name": "NIO / SOL"}, "relationships": {"base_token": {"data": {"id": "solana_" + NIO}}}},
    ]}
    out = r.gecko_trending(fetch=lambda: body)
    assert [o["tokenAddress"] for o in out] == [ETH, NIO] and out[1]["rank"] == 2
    monkeypatch.setenv("COVERAGE_GECKO", "false")
    assert r.gecko_trending(fetch=lambda: body) == []


# ── hooks present in meme_sniper.py ─────────────────────────────────────────
def test_hooks_wired():
    s = (ROOT / "meme_sniper.py").read_text(encoding="utf-8")
    for needle in ("_v107.trend_fast(", "_v107.heal_ticker(", "_v107.gecko_trending",
                   "_v107.parody_alert(", "_v107.clone_override(", "_v107.expired_fallback(",
                   "_v107.x_profile,", "_v107.bundle_check(", 'sig.get("_v107_small")',
                   'get("trail_giveback_pts")'):
        assert needle in s, needle
