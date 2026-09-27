"""Capital and margin management for live trading."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

INTRADAY_MARGIN_MULTIPLIER = 5


class CapitalManager:
    """Track available capital and validate margin before order placement."""

    def __init__(self, client: Any, deployed: float = 0):
        self._client = client
        self._deployed = deployed

    def available_capital(self) -> float:
        """Live available capital minus already-deployed amount."""
        margins = self._client.get_margins()
        available = margins.get("equity", {}).get("available", {})
        balance = available.get("live_balance", 0) + available.get(
            "intraday_payin", 0
        )
        return balance - self._deployed

    def check_margin(
        self, entry_price: float, quantity: int
    ) -> tuple[bool, str]:
        """Return (ok, reason) — ok is True when margin is sufficient."""
        required = (entry_price * quantity) / INTRADAY_MARGIN_MULTIPLIER
        available = self.available_capital()
        if required > available:
            return (
                False,
                f"Need Rs.{required:.0f} margin, only Rs.{available:.0f} available",
            )
        return True, ""

    def add_deployed(self, amount: float) -> None:
        self._deployed += amount

    def release_deployed(self, amount: float) -> None:
        self._deployed = max(0, self._deployed - amount)
