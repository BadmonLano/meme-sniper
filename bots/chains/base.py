"""ChainAdapter base interface. Every chain implements all six methods.

Contract (all async, never raise on network failure; return None / failure dict):
  new_token_feed()            -> awaitable that runs the chain's new-token source
  quote(input, output, amt)   -> dict | None   (amt in the chain's smallest unit)
  buy(token, amount_native)   -> dict  {success, tx_signature, token_amount, ...}
  sell(token, token_amount)   -> dict  {success, tx_signature, sol_received/native_received, ...}
  balance()                   -> float | None  (native coin balance of the hot wallet)
  safety_check(token)         -> dict  {verdict: "ok"|"caution"|"block", ...}
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

REQUIRED_METHODS = ("new_token_feed", "quote", "buy", "sell", "balance", "safety_check")


class ChainAdapter(ABC):
    name: str = "base"
    native_symbol: str = ""

    def __init__(self, engine: Any = None):
        self._engine = engine  # optional injected engine module (tests / wiring)

    @abstractmethod
    async def new_token_feed(self) -> None: ...

    @abstractmethod
    async def quote(self, input_token: str, output_token: str, amount: int, slippage_bps: int = 1000) -> Optional[dict]: ...

    @abstractmethod
    async def buy(self, token: str, amount_native: float, slippage_bps: int = 1500) -> dict: ...

    @abstractmethod
    async def sell(self, token: str, token_amount: float, slippage_bps: int = 1500, *, force: bool = False) -> dict: ...

    @abstractmethod
    async def balance(self) -> Optional[float]: ...

    @abstractmethod
    async def safety_check(self, token: str, **kw) -> dict: ...
