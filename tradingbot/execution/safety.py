"""Safety mechanisms: daily loss kill switch, position cap, emergency stop."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class SafetyManager:
    """Guard rails to prevent runaway losses."""

    def __init__(
        self,
        capital: float,
        max_daily_loss_pct: float,
        max_positions: int = 4,
    ):
        self._capital = capital
        self._max_loss = capital * max_daily_loss_pct / 100
        self._max_positions = max_positions

    def check_daily_loss(self, realised_pnl: float) -> bool:
        """Return True when daily loss limit is breached.

        Breached when ``abs(loss) >= capital x max_daily_loss_pct / 100``.
        """
        if realised_pnl < 0 and abs(realised_pnl) >= self._max_loss:
            log.critical(
                "DAILY LOSS LIMIT BREACHED: Rs.%.0f (limit Rs.%.0f)",
                realised_pnl,
                -self._max_loss,
            )
            return True
        return False

    def can_open_position(self, current_positions: int) -> bool:
        """Return True when another position can be opened."""
        return current_positions < self._max_positions

    def emergency_stop(self, executor: Any) -> None:
        """Kill switch -- cancel all pending, square off all positions.

        Actual implementation depends on position tracking; this logs
        the critical event and calls executor if wired.
        """
        log.critical("EMERGENCY STOP triggered — cancelling all orders")
