"""Offline tests for sniper_upgrades (no network, no RPC)."""
import asyncio, os, sys, tempfile
from pathlib import Path
HERE = Path(__file__).resolve().parent
for p in (HERE, HERE.parent):
    sys.path.insert(0, str(p))
os.environ["XSTOCKS_CHECK"] = "false"
import sniper_upgrades as u
u.init(tempfile.mkdtemp())
SOL, USDC = u.SOL_MINT, u.USDC_MINT

def pair(**kw):
    p = {"baseToken": {"address": "Abcpump", "symbol": "ABC", "name": "abc"},
         "quoteToken": {"address": SOL, "symbol": "SOL"}, "dexId": "pumpswap",
         "liquidity": {"usd": 50000, "base": 1e8, "quote": 200}, "priceUsd": "0.0001",
         "volume": {"h24": 100000, "h1": 5000}, "txns": {"h1": {"buys": 50, "sells": 40}},
         "priceChange": {"m5": 2, "h1": 5}}
    p.update(kw); return p

def test_sol_pair_clean():
    s = u.pre_gate(pair(), "m1")
    assert not s.get("skip_reason") and not s["quote"]["custom_pair"], s
    assert s["token_type"] == "pump.fun meme"

def test_custom_pair_flag():
    s = u.pre_gate(pair(quoteToken={"address": "Fartpump", "symbol": "FART"}), "m2")
    assert s["quote"]["custom_pair"] and s["quote"]["kind"] == "pump_coin"
    assert any("CUSTOM PAIR" in f for f in s["flags"]) and not s.get("skip_reason")

def test_negative_reserves_skip_recheck():
    s = u.pre_gate(pair(liquidity={"usd": 5000, "base": -3, "quote": 10}), "m3")
    assert s["skip_reason"] == "invalid_reserves_pending_recheck" and s["recheck"]

def test_reserve_guard_off():
    os.environ["RESERVE_GUARD"] = "off"
    try:
        assert not u.pre_gate(pair(liquidity={"usd": 5000, "base": -3, "quote": 10}), "m3b").get("skip_reason")
    finally:
        del os.environ["RESERVE_GUARD"]

def test_meteora_drain():
    u.pre_gate(pair(dexId="meteora", liquidity={"usd": 100000, "base": 1e8, "quote": 400}), "m4")
    s = u.pre_gate(pair(dexId="meteora", liquidity={"usd": 20000, "base": 1e8, "quote": 80}), "m4")
    assert s["skip_reason"] == "meteora_drain_guard", s

def test_drain_ignores_other_venues():
    u.pre_gate(pair(liquidity={"usd": 100000, "base": 1, "quote": 1}), "m5")
    assert not u.pre_gate(pair(liquidity={"usd": 20000, "base": 1, "quote": 1}), "m5").get("skip_reason")

def test_wash_flag():
    s = u.pre_gate(pair(volume={"h24": 5_000_000, "h1": 200000}, liquidity={"usd": 20000, "base": 1, "quote": 1}), "m6")
    assert s.get("wash") and not s.get("skip_reason")

def test_fee_sweep():
    assert u.classify_swap_error("Error Code: CreatorFeesNotSwept") == "fee_sweep_pending"
    assert u.classify_swap_error("tx_failed_onchain: {'InstructionError': [2, {'Custom': 6095}]}") is None
    os.environ["FEE_SWEEP_NUMERIC_CODES"] = "true"
    try:
        assert u.classify_swap_error("{'InstructionError': [2, {'Custom': 6095}]}") == "fee_sweep_pending"
    finally:
        del os.environ["FEE_SWEEP_NUMERIC_CODES"]
    u.note_fee_sweep("m7", "CreatorFeesNotSwept")
    assert u.pre_gate(pair(), "m7")["skip_reason"] == "fee_sweep_pending_recheck"

def test_bundle():
    async def rpc(m, p):
        return [{"slot": 100, "signature": f"s{i}"} for i in range(5)] + [{"slot": 101, "signature": "x"}]
    r = asyncio.run(u.launch_signals("m8", rpc, 10))
    assert r["bundled"] and r["launch_slot_txs"] == 5
    assert asyncio.run(u.launch_signals("m9", rpc, 500)) is None   # too old, no RPC
    assert any("BUNDLED" in f for f in u.card_flags({"bundle": r}))

def test_swap_v1_default_and_fee_sweep_tag():
    calls = []
    async def v1(q, **kw):
        calls.append(q); return {"success": False, "error": "CreatorFeesNotSwept"}
    r = asyncio.run(u.swap_execute(v1, {"inputMint": SOL, "outputMint": "m10"}, {}, client_fn=None, api_key="k",
                                   wallet="w", load_keypair=None, tx_cls=None, paper=False, log=lambda t: None))
    assert calls and r["error_class"] == "fee_sweep_pending"

def test_xstock_fake():
    os.environ["XSTOCKS_CHECK"] = "true"
    u._XSTOCKS.update(at=9e18, mints={"REALx": {"symbol": "TSLAx", "underlying": "TSLA"}}, symbols={"TSLAX": "REALx"})
    try:
        s = u.pre_gate(pair(baseToken={"address": "FAKE", "symbol": "TSLAx", "name": "Tesla"}), "FAKE")
        assert any("FAKE XSTOCK" in f for f in s["flags"])
        s = u.pre_gate(pair(quoteToken={"address": "REALx", "symbol": "TSLAx"}), "m11")
        assert s["token_type"].startswith("stock-meme") and s.get("stock_meme")
    finally:
        os.environ["XSTOCKS_CHECK"] = "false"

if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("PASS", k)
    print(f"{n} passed")
