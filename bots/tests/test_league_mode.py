"""League mode (AudaceFi devnet league) rail. No network, no wallet, no keys.
Run: pytest bots/tests/test_league_mode.py   (or python bots/tests/test_league_mode.py)"""
import asyncio, json, re, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import league_mode as L   # noqa: E402

SRC = (ROOT / "meme_sniper.py").read_text(encoding="utf-8")
DEV = "https://api.devnet.solana.com"


def cfg(**o):
    c = L.load_config({"LEAGUE_RPC_URL": DEV, "LEAGUE_WALLET_ADDRESS": "LeagueAddr111",
                       "LEAGUE_WALLET_PRIVATE_KEY": "league-key", "LEAGUE_USDC_MINT": "USDCdev"})
    c.update(o)
    return c


def test_off_by_default():
    assert not L.enabled({}) and not L.enabled({"LEAGUE_MODE": "false"}) and L.enabled({"LEAGUE_MODE": "true"})


def test_boot_ok_on_clean_devnet_setup():
    assert L.boot_problems(cfg(), main_addr="MainAddr", main_private="main-key", genesis_hash=L.DEVNET_GENESIS) == []


def test_boot_refuses_mainnet_rpc_and_genesis():
    p = L.boot_problems(cfg(rpc_url="https://mainnet.helius-rpc.com/?api-key=x"))
    assert any("devnet" in x for x in p) and any("mainnet" in x for x in p)
    p = L.boot_problems(cfg(rpc_url="https://my-devnet.example"), genesis_hash=L.MAINNET_GENESIS)
    assert any("genesis" in x and "mainnet" in x for x in p)


def test_boot_refuses_main_wallet_address_or_key():
    assert any("main hot wallet" in x for x in L.boot_problems(cfg(), main_addr="LeagueAddr111"))
    assert any("mainnet keys" in x for x in L.boot_problems(cfg(), main_private="league-key"))
    assert any("owner/ledger" in x for x in L.boot_problems(cfg(), other_addrs=("LeagueAddr111",)))
    assert any("key missing" in x for x in L.boot_problems(cfg(wallet_private="")))


def test_keypair_path_loads_without_env_key():
    f = Path(tempfile.mkdtemp()) / "league.json"; f.write_text("[1,2,3]")
    c = L.load_config({"LEAGUE_WALLET_KEYPAIR_PATH": str(f)})
    assert c["wallet_private"] == "[1,2,3]"


def test_allowlist_formats_and_missing_file():
    d = Path(tempfile.mkdtemp())
    for name, body in [("a.json", ["M1", "M2"]), ("b.json", {"mints": ["M1"]}), ("c.json", {"degen": [{"mint": "M1"}]})]:
        (d / name).write_text(json.dumps(body))
        assert "M1" in L.load_allowlist(str(d / name))
    assert L.load_allowlist(str(d / "nope.json")) == set() and L.load_allowlist("") == set()


def test_standard_season_window_and_phases():
    wed = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
    s, e = L.season_window(cfg(), wed)
    assert (s.isoformat(), e.isoformat()) == ("2026-10-26T00:00:00+00:00", "2026-10-31T00:00:00+00:00")
    assert L.phase(cfg(), wed)["phase"] == "trading"
    assert L.phase(cfg(), datetime(2026, 10, 30, 22, 30, tzinfo=timezone.utc))["phase"] == "flatten"   # Fri 18:30 ET
    assert L.phase(cfg(), datetime(2026, 10, 31, 12, tzinfo=timezone.utc))["phase"] == "closed"        # Saturday
    assert L.phase(cfg(), datetime(2026, 11, 1, 23, tzinfo=timezone.utc))["phase"] == "flatten"        # before next start


def test_explicit_season_dates_win():
    c = cfg(season_start="2026-11-02T00:00:00Z", season_end="2026-11-07T00:00:00Z")
    assert L.phase(c, datetime(2026, 11, 3, tzinfo=timezone.utc))["season_end"] == "2026-11-07T00:00:00+00:00"


def test_buy_gate():
    wed = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
    assert L.buy_gate(cfg(), "M1", {"M1"}, now=wed) is None
    assert L.buy_gate(cfg(), "M9", {"M1"}, now=wed)[0] == "league_not_allowlisted"
    assert L.buy_gate(cfg(), "M1", set(), now=wed)[0] == "league_allowlist_missing"
    assert L.buy_gate(cfg(), "M1", {"M1"}, now=datetime(2026, 10, 30, 23, tzinfo=timezone.utc))[0] == "league_window"
    assert L.buy_size_usdc(cfg(), 500) == 100 and L.buy_size_usdc(cfg(), None) == 25


def test_executor_missing_refuses_and_never_jupiter():
    r = asyncio.run(L.execute_buy(cfg(), "M1", 10))
    assert not r["success"] and "league_executor_not_configured" in r["error"]
    assert asyncio.run(L.price(cfg(), "M1")) is None


def test_executor_plugin_used():
    class Ex:
        async def buy(self, m, u): return {"success": True, "token_amount": 5, "buy_price_usd": u / 5}
        async def sell(self, m, a): return {"success": True}
        async def price(self, m): return {"priceUsd": "2"}
    ex = Ex()
    assert asyncio.run(L.execute_buy(cfg(), "M1", 10, executor=ex))["buy_price_usd"] == 2
    assert asyncio.run(L.price(cfg(), "M1", executor=ex))["priceUsd"] == "2"


def test_flatten_orders():
    pos = {"_meta": {}, "A": {"token_amount": 10}, "B": {"token_amount": 0}, "C": {"token_amount": 3}}
    o = L.flatten_orders(pos, inflight=lambda m: m == "C", now_tag="1")
    assert [x["mint"] for x in o] == ["A"] and o[0]["amount_pct"] == 100.0


def test_sniper_hooks_are_all_behind_the_switch():
    assert 'LEAGUE_MODE = _league.enabled()' in SRC and "raise SystemExit(2)" in SRC
    for fn in ("fetch_token_data", "jupiter_quote_fresh", "jupiter_swap_execute", "jupiter_swap_buy",
               "jupiter_swap_sell", "jupiter_swap_sell_panic", "execute_ledger_sweep"):
        i = SRC.index(f"async def {fn}(")
        assert "if LEAGUE_MODE:" in SRC[i:i + 2500], fn
    assert 'SupervisedTask("league_flatten", league_flatten_loop)' in SRC
    # boot overrides happen before any keypair load
    assert SRC.index("HOT_WALLET_PRIVATE = LEAGUE_CFG") < SRC.index("def _load_keypair(")
    # every new league line in the buy path is conditional
    b = SRC[SRC.index("async def execute_buy_signal("):SRC.index("async def execute_dex_recon_signal(")]
    assert "(True, 0.0) if LEAGUE_MODE else await is_wallet_above_floor()" in b
    assert "amount_sol if LEAGUE_MODE else await get_current_max_entry_sol()" in b


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); print("ok", k); n += 1
    print(f"ALL {n} PASSED")
