"""league_mode.py - AudaceFi devnet trading league rail for Meme Sniper (off by default).

LEAGUE_MODE=false (default): nothing here runs and the live mainnet path is unchanged.
LEAGUE_MODE=true: the bot runs as a league bot on Solana devnet, per the AudaceFi Rulebook
(Devnet Sandbox section, https://audacefi.com/rulebook):
  - devnet RPC only (LEAGUE_RPC_URL; boot refuses a mainnet-looking URL or a non-devnet genesis hash)
  - a separate league wallet (LEAGUE_WALLET_ADDRESS + LEAGUE_WALLET_KEYPAIR_PATH or
    LEAGUE_WALLET_PRIVATE_KEY); boot refuses if it matches the main hot wallet, owner or ledger
  - only tokens on the category allowlist (LEAGUE_ALLOWLIST_FILE); missing/empty list = no buys
  - spot only; USDC only (plus a small SOL gas buffer) at the start and end snapshots:
    no buys outside the season window, and every bag is flattened to USDC
    LEAGUE_FLATTEN_BUFFER_MIN before the end snapshot (and before the next start)
  - execution only through the AudaceFi supported API (the sandbox rules say an unsupported
    external route can invalidate participation), never Jupiter. The API is not public yet, so
    the executor is a plug-in module (LEAGUE_EXECUTOR_MODULE) exposing
        async buy(mint, usdc_amount) -> {success, tx_signature, buy_price_usd, token_amount, ...}
        async sell(mint, token_amount_raw) -> {success, tx_signature, usdc_received, ...}
        async price(mint) -> {"priceUsd": .., "liquidity": {"usd": ..}, "marketCap": ..} | None
    Without it every league trade is refused with league_executor_not_configured.
Owner rules, protective SL/TP and the default flip stop run unchanged on top.
"""
import importlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

DEVNET_GENESIS = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
MAINNET_GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
# Tasks that only make sense on mainnet or that move money outside league trading.
SKIP_TASKS = {"own_launch", "own_launch_fee_claim", "sniper_launch", "holdings_treasury",
              "owner_positions", "weekly_sweep", "position_reconcile", "repo_watch"}


def _on(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def enabled(env=None) -> bool:
    return _on((env if env is not None else os.environ).get("LEAGUE_MODE", "false"))


def load_config(env=None) -> dict:
    e = env if env is not None else os.environ
    priv = (e.get("LEAGUE_WALLET_PRIVATE_KEY") or "").strip()
    kp = (e.get("LEAGUE_WALLET_KEYPAIR_PATH") or "").strip()
    if not priv and kp:
        try:
            priv = Path(kp).read_text(encoding="utf-8").strip()
        except OSError:
            priv = ""
    return {
        "rpc_url": (e.get("LEAGUE_RPC_URL") or "https://api.devnet.solana.com").strip(),
        "wallet_address": (e.get("LEAGUE_WALLET_ADDRESS") or "").strip(),
        "wallet_private": priv,                     # never logged
        "usdc_mint": (e.get("LEAGUE_USDC_MINT") or "").strip(),
        "category": (e.get("LEAGUE_CATEGORY") or "degen").strip().lower(),
        "allowlist_file": (e.get("LEAGUE_ALLOWLIST_FILE") or "").strip(),
        "executor_module": (e.get("LEAGUE_EXECUTOR_MODULE") or "").strip(),
        "season_start": (e.get("LEAGUE_SEASON_START") or "").strip(),
        "season_end": (e.get("LEAGUE_SEASON_END") or "").strip(),
        "flatten_buffer_min": float(e.get("LEAGUE_FLATTEN_BUFFER_MIN") or 120),
        "buy_usdc": float(e.get("LEAGUE_BUY_USDC") or 25),
        "max_buy_usdc": float(e.get("LEAGUE_MAX_BUY_USDC") or 100),
        "gas_min_sol": float(e.get("LEAGUE_GAS_MIN_SOL") or 0.02),
        "skip_genesis_check": _on(e.get("LEAGUE_SKIP_GENESIS_CHECK")),
    }


def boot_problems(cfg: dict, *, main_addr: str = "", main_private: str = "", other_addrs=(),
                  genesis_hash: Optional[str] = None) -> list:
    """Every reason the league rail must refuse to start. Empty list = safe to run."""
    p = []
    rpc = cfg.get("rpc_url") or ""
    low = rpc.lower()
    if "devnet" not in low:
        p.append("LEAGUE_RPC_URL must be a Solana devnet endpoint (url has no 'devnet')")
    if "mainnet" in low:
        p.append("LEAGUE_RPC_URL looks like mainnet")
    if genesis_hash is not None and genesis_hash != DEVNET_GENESIS:
        p.append("LEAGUE_RPC_URL genesis hash is not devnet"
                 + (" (it is mainnet)" if genesis_hash == MAINNET_GENESIS else ""))
    addr = cfg.get("wallet_address") or ""
    if not addr:
        p.append("LEAGUE_WALLET_ADDRESS is not set")
    if not cfg.get("wallet_private"):
        p.append("league wallet key missing (LEAGUE_WALLET_KEYPAIR_PATH or LEAGUE_WALLET_PRIVATE_KEY)")
    if addr and main_addr and addr == main_addr.strip():
        p.append("league wallet is the main hot wallet; use a separate devnet wallet")
    if cfg.get("wallet_private") and main_private and cfg["wallet_private"] == main_private.strip():
        p.append("league wallet key is the main hot wallet key; never use mainnet keys in the league")
    for o in other_addrs or ():
        if addr and o and addr == str(o).strip():
            p.append("league wallet matches the owner/ledger wallet; use a separate devnet wallet")
    if not cfg.get("usdc_mint"):
        p.append("LEAGUE_USDC_MINT is not set (the league's devnet USDC mint)")
    return p


def rpc_genesis(rpc_url: str, timeout: float = 10.0) -> Optional[str]:
    try:
        import httpx
        r = httpx.post(rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": "getGenesisHash"}, timeout=timeout)
        return (r.json() or {}).get("result")
    except Exception:
        return None


def load_allowlist(path: str) -> set:
    """JSON: ["mint", ...] | {"mints": [...]} | {"degen": [...], ...} | [{"mint": ..}]. Missing = empty."""
    if not path:
        return set()
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return set()
    return _mints(d)


def _mints(d, category: str = "degen") -> set:
    if isinstance(d, dict):
        for k in ("mints", "tokens", category):
            if k in d:
                return _mints(d[k], category)
        return set()
    out = set()
    for x in d or []:
        if isinstance(x, str) and x.strip():
            out.add(x.strip())
        elif isinstance(x, dict) and (x.get("mint") or x.get("address")):
            out.add(str(x.get("mint") or x.get("address")).strip())
    return out


def _parse(ts: str) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def season_window(cfg: dict, now: Optional[datetime] = None):
    """(start, end) of the current/next season. Explicit LEAGUE_SEASON_START/END win; otherwise the
    standard season Monday 00:00 UTC -> Saturday 00:00 UTC of this week."""
    now = now or datetime.now(timezone.utc)
    s, e = _parse(cfg.get("season_start") or ""), _parse(cfg.get("season_end") or "")
    if s and e:
        return s, e
    mon = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start, end = mon, mon + timedelta(days=5)
    if now >= end:                                   # weekend: next season
        start, end = mon + timedelta(days=7), mon + timedelta(days=12)
    return start, end


def phase(cfg: dict, now: Optional[datetime] = None) -> dict:
    """trading | flatten (end snapshot near) | closed (outside the season). Buys only in trading."""
    now = now or datetime.now(timezone.utc)
    start, end = season_window(cfg, now)
    buf = timedelta(minutes=float(cfg.get("flatten_buffer_min") or 120))
    if start <= now < end - buf:
        ph = "trading"
    elif end - buf <= now < end:
        ph = "flatten"
    elif start - buf <= now < start:
        ph = "flatten"                               # USDC only at the start snapshot too
    else:
        ph = "closed"
    return {"phase": ph, "season_start": start.isoformat(), "season_end": end.isoformat(),
            "flatten_at": (end - buf).isoformat(), "minutes_to_end": round((end - now).total_seconds() / 60, 1)}


def buy_gate(cfg: dict, mint: str, allowlist: set, *, usdc_amount=None, now=None, open_league_positions=0):
    """None = allowed, else (code, reason). Spot only; size in USDC."""
    ph = phase(cfg, now)
    if ph["phase"] != "trading":
        return ("league_window", f"league phase is {ph['phase']}; buys only while the season trades "
                f"(flatten at {ph['flatten_at']}, end snapshot {ph['season_end']})")
    if not allowlist:
        return ("league_allowlist_missing", "no league allowlist loaded (LEAGUE_ALLOWLIST_FILE); failing closed")
    if mint not in allowlist:
        return ("league_not_allowlisted", f"{mint} is not on the {cfg.get('category')} allowlist")
    amt = buy_size_usdc(cfg, usdc_amount)
    if amt <= 0:
        return ("league_size", "league buy size must be > 0 USDC")
    return None


def buy_size_usdc(cfg: dict, requested=None) -> float:
    try:
        a = float(requested) if requested not in (None, "") else float(cfg.get("buy_usdc") or 0)
    except (TypeError, ValueError):
        a = float(cfg.get("buy_usdc") or 0)
    return round(max(0.0, min(a, float(cfg.get("max_buy_usdc") or a))), 2)


def load_executor(cfg: dict):
    mod = cfg.get("executor_module") or ""
    if not mod:
        return None
    try:
        return importlib.import_module(mod)
    except Exception:
        return None


NOT_CONFIGURED = {"success": False, "error": "league_executor_not_configured: set LEAGUE_EXECUTOR_MODULE to an "
                  "AudaceFi supported-API executor; league trades never route through Jupiter"}


async def execute_buy(cfg: dict, mint: str, usdc_amount: float, executor=None) -> dict:
    ex = executor if executor is not None else load_executor(cfg)
    if ex is None or not hasattr(ex, "buy"):
        return dict(NOT_CONFIGURED)
    try:
        r = await ex.buy(mint, float(usdc_amount))
        return r if isinstance(r, dict) else {"success": False, "error": "league_executor_bad_result"}
    except Exception as e:
        return {"success": False, "error": f"league_executor_error: {type(e).__name__}"}


async def execute_sell(cfg: dict, mint: str, token_amount, executor=None) -> dict:
    ex = executor if executor is not None else load_executor(cfg)
    if ex is None or not hasattr(ex, "sell"):
        return dict(NOT_CONFIGURED)
    try:
        r = await ex.sell(mint, token_amount)
        return r if isinstance(r, dict) else {"success": False, "error": "league_executor_bad_result"}
    except Exception as e:
        return {"success": False, "error": f"league_executor_error: {type(e).__name__}"}


async def price(cfg: dict, mint: str, executor=None) -> Optional[dict]:
    ex = executor if executor is not None else load_executor(cfg)
    if ex is None or not hasattr(ex, "price"):
        return None
    try:
        r = await ex.price(mint)
        return r if isinstance(r, dict) and float(r.get("priceUsd") or 0) > 0 else None
    except Exception:
        return None


def flatten_orders(positions: dict, inflight=lambda m: False, now_tag: str = "") -> list:
    """Sell-100% signals for every open bag (skips meta keys and bags with a sell in flight)."""
    out = []
    for mint, p in (positions or {}).items():
        if str(mint).startswith("_") or not isinstance(p, dict) or inflight(mint):
            continue
        if float(p.get("token_amount") or 0) <= 0:
            continue
        out.append({"signal_id": f"league_flatten_{str(mint)[:8]}_{now_tag}", "mint": mint,
                    "amount_pct": 100.0, "reason": "league_flatten_before_snapshot", "_league_flatten": True})
    return out
