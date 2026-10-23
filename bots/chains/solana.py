"""Reference Solana adapter: thin delegation to meme_sniper's existing
functions. NO behaviour change - each method calls the engine function as-is.
The engine is imported lazily (first call), never at import time.

  new_token_feed -> meme_sniper.birth_listener_loop   (LAUNCH_FEED pumpportal/helius/both)
  quote          -> meme_sniper.jupiter_quote_fresh
  buy            -> meme_sniper.jupiter_swap_buy
  sell           -> meme_sniper.jupiter_swap_sell
  balance        -> meme_sniper._wallet_sol_balance
  safety_check   -> meme_sniper.smart_rug_check
"""
from __future__ import annotations

import importlib
from typing import Optional

from .base import ChainAdapter

SOL_MINT = "So11111111111111111111111111111111111111112"


class SolanaAdapter(ChainAdapter):
    name = "solana"
    native_symbol = "SOL"
    native_mint = SOL_MINT

    def _e(self):
        if self._engine is None:
            self._engine = importlib.import_module("meme_sniper")
        return self._engine

    async def new_token_feed(self) -> None:
        return await self._e().birth_listener_loop()

    async def quote(self, input_token: str, output_token: str, amount: int, slippage_bps: int = 1000) -> Optional[dict]:
        return await self._e().jupiter_quote_fresh(input_token, output_token, amount, slippage_bps)

    async def buy(self, token: str, amount_native: float, slippage_bps: int = 1500) -> dict:
        return await self._e().jupiter_swap_buy(token, amount_native, slippage_bps)

    async def sell(self, token: str, token_amount: float, slippage_bps: int = 1500, *, force: bool = False) -> dict:
        return await self._e().jupiter_swap_sell(token, token_amount, slippage_bps, force=force)

    async def balance(self) -> Optional[float]:
        return await self._e()._wallet_sol_balance()

    async def safety_check(self, token: str, **kw) -> dict:
        return await self._e().smart_rug_check(token, **kw)
