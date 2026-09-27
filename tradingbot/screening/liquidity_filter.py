"""Phase 1A: eliminate stocks that can't be traded safely with 4L capital."""

from __future__ import annotations

from typing import Any


class LiquidityFilter:
    """Filter stocks by volume, price range, market cap, and trading history."""

    def __init__(
        self,
        min_volume: int,
        min_price: float,
        max_price: float,
        min_market_cap_cr: float,
        min_trading_days: int,
    ):
        self._min_volume = min_volume
        self._min_price = min_price
        self._max_price = max_price
        self._min_cap = min_market_cap_cr
        self._min_days = min_trading_days

    def passes(self, stock: dict[str, Any]) -> bool:
        if stock["avg_volume"] < self._min_volume:
            return False
        if not (self._min_price <= stock["last_price"] <= self._max_price):
            return False
        if stock["market_cap_cr"] < self._min_cap:
            return False
        if stock.get("trading_days", 0) < self._min_days:
            return False
        return True

    def filter_all(self, stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [s for s in stocks if self.passes(s)]
