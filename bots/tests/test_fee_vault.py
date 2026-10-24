"""v1.0.3 fee-wallet vault exception. KIMCHI replay uses public figures
(trenchbook / Bitquery, 2026-10-20), shortened wallet ids, no RPC."""
import os
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fee_vault as fv  # noqa: E402

CREATE = 1761001215          # 23:00:15 UTC launch (illustrative epoch)
CREATOR, VAULT, BUYER = "EFSr...56oF", "Gs5F...GYeX", "Snpr...0001"


def kimchi_facts(**over):
    f = {
        "creator": CREATOR, "fee_recipients": [VAULT],
        "creator_transfers": [
            {"to": VAULT, "pct": 75.0, "kind": "transfer", "ts": CREATE + 57},
            {"to": BUYER, "pct": 0.4, "kind": "swap", "ts": CREATE + 65},
        ],
        "receiver_outgoing_sigs": {VAULT: 0},
        "creator_balance_pct": 0.0, "creator_last_sell_ts": CREATE + 101,
        "creator_first_ts": CREATE,
    }
    f.update(over)
    return f


def test_kimchi_is_vault():
    r = fv.evaluate_vault(kimchi_facts(), now_ts=CREATE + 120)
    assert r["vault"] and r["vault_wallet"] == VAULT and r["vault_pct"] == 75.0


def test_creator_still_selling_waits():
    r = fv.evaluate_vault(kimchi_facts(creator_balance_pct=6.0), now_ts=CREATE + 110)
    assert r["vault"] is False and r["checks"]["creator_done"] is False
    r = fv.evaluate_vault(kimchi_facts(creator_balance_pct=6.0), now_ts=CREATE + 170)
    assert r["vault"]                       # 60s quiet after last sell


def test_real_bundle_not_vault():
    f = kimchi_facts(creator_transfers=[{"to": f"w{i}", "pct": 5, "kind": "swap", "ts": CREATE}
                                        for i in range(6)])
    assert fv.evaluate_vault(f, now_ts=CREATE + 300)["vault"] is False


def test_receiver_not_fee_recipient():
    r = fv.evaluate_vault(kimchi_facts(fee_recipients=["other"]), now_ts=CREATE + 300)
    assert not r["vault"] and r["checks"]["is_fee_recipient"] is False


def test_receiver_has_signed():
    r = fv.evaluate_vault(kimchi_facts(receiver_outgoing_sigs={VAULT: 1}), now_ts=CREATE + 300)
    assert not r["vault"]


def test_unknown_outgoing_is_fail():
    r = fv.evaluate_vault(kimchi_facts(receiver_outgoing_sigs={}), now_ts=CREATE + 300)
    assert not r["vault"]


def test_off_switch(monkeypatch):
    monkeypatch.setenv("VAULT_EXCEPTION", "false")
    assert fv.evaluate_vault(kimchi_facts(), now_ts=CREATE + 300)["vault"] is False


def test_float_top10_excludes_vault():
    rows = [{"owner": VAULT, "amount": 750 * 10**12}] + \
           [{"owner": f"h{i}", "amount": 4 * 10**12} for i in range(12)]
    assert fv.float_top10_pct(rows, VAULT, fv.TOTAL_SUPPLY_RAW_DEFAULT) == 4.0


def test_exit_params_and_size(monkeypatch):
    p = fv.exit_params({"x": 1})
    assert p["stop_loss_pct"] == 25 and p["partial_take_at_pct"] == 200
    assert p["partial_take_pct"] == 50 and p["trail_drop_pct"] == 35 and p["x"] == 1
    assert fv.entry_size_sol() == 0.1
    monkeypatch.setenv("VAULT_ENTRY_SOL", "0.05")
    assert fv.entry_size_sol() == 0.1      # never under the 0.1 floor


def test_vault_moved_trigger():
    pos = {"params": {"fee_vault": {"wallet": VAULT, "outgoing_at_entry": 0}}}
    assert fv.vault_exit_trigger(pos, 0) is None
    assert fv.vault_exit_trigger(pos, None) is None
    assert fv.vault_exit_trigger(pos, 1)["type"] == "vault_moved"


def test_parse_transfer_vs_swap():
    mint = "CSoc...pump"
    def tx(prog):
        return {"blockTime": CREATE + 57,
                "transaction": {"message": {"instructions": [{"programId": prog}]}},
                "meta": {"preTokenBalances": [{"owner": CREATOR, "mint": mint, "uiTokenAmount": {"amount": str(793 * 10**12)}}],
                         "postTokenBalances": [{"owner": CREATOR, "mint": mint, "uiTokenAmount": {"amount": str(43 * 10**12)}},
                                               {"owner": VAULT, "mint": mint, "uiTokenAmount": {"amount": str(750 * 10**12)}}]}}
    t = fv._parse_creator_tx(tx("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"), mint, CREATOR, fv.TOTAL_SUPPLY_RAW_DEFAULT)
    assert t[0]["kind"] == "transfer" and round(t[0]["pct"]) == 75
    s = fv._parse_creator_tx(tx("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"), mint, CREATOR, fv.TOTAL_SUPPLY_RAW_DEFAULT)
    assert s[0]["kind"] == "swap"


def test_rpc_failure_means_no_exception():
    async def bad(*a, **k):
        raise RuntimeError("rpc down")
    assert asyncio.run(fv.gather_vault_facts("m", CREATOR, [VAULT], bad)) is None
