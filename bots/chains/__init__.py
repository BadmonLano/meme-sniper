"""Chain plug-in point (public drop).

Solana is the only chain that trades today. This package is a documented
interface plus a reference Solana adapter; the engine (meme_sniper.py) is NOT
wired through it, so importing or selecting adapters changes no trading
behaviour.

Selection:
  CHAIN_ADAPTERS=solana            (default) comma list of adapter names
  CHAIN_<NAME>_ENABLED=1           required for every non-Solana chain; off by default

See SETUP.md "Adding a chain".
"""
from __future__ import annotations

import importlib
import os

from .base import ChainAdapter

DEFAULT_CHAIN_ADAPTERS = "solana"

# name -> "module:Class". Add new chains here (and give them their own switch).
REGISTRY: dict[str, str] = {
    "solana": "chains.solana:SolanaAdapter",
}


def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def requested_chains(env: dict | None = None) -> list[str]:
    env = os.environ if env is None else env
    raw = env.get("CHAIN_ADAPTERS", DEFAULT_CHAIN_ADAPTERS) or DEFAULT_CHAIN_ADAPTERS
    return [n.strip().lower() for n in raw.split(",") if n.strip()]


def chain_enabled(name: str, env: dict | None = None) -> bool:
    """Solana is on when listed. Any other chain also needs CHAIN_<NAME>_ENABLED=1."""
    env = os.environ if env is None else env
    if name == "solana":
        return True
    return _truthy(env.get(f"CHAIN_{name.upper()}_ENABLED", "0"))


def load_adapters(env: dict | None = None, engine=None) -> dict[str, ChainAdapter]:
    """Return {name: adapter} for requested AND enabled chains. Unknown or
    switched-off chains are skipped (never raise). Does not import the engine."""
    out: dict[str, ChainAdapter] = {}
    for name in requested_chains(env):
        spec = REGISTRY.get(name)
        if not spec or not chain_enabled(name, env):
            continue
        mod_name, cls_name = spec.split(":")
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            mod = importlib.import_module("." + mod_name.split(".", 1)[1], __name__)
        out[name] = getattr(mod, cls_name)(engine=engine)
    return out
