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
        self._max_loss = capital * max_daily_loss_pct
        self._max_positions = max_positions

    def check_daily_loss(self, realised_pnl: float) -> bool:
        """Return True when daily loss limit is breached.

        Breached when ``abs(loss) >= capital x max_daily_loss_pct``.
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

    def emergency_stop(
        self,
        executor: Any,
        pending_orders: list[str],
        open_positions: list[dict],
    ) -> dict:
        """Kill switch -- cancel all pending orders, square off all positions.

        Args:
            executor: Object with cancel_order(order_id) and
                place_exit(symbol, exchange, direction, quantity, order_type).
            pending_orders: List of order IDs to cancel.
            open_positions: List of dicts with keys: symbol, direction,
                quantity, and optionally exchange (defaults to "NSE").

        Returns:
            Dict with counts: cancelled, squared_off, errors.
        """
        log.critical(
            "EMERGENCY STOP triggered — cancelling %d orders, squaring %d positions",
            len(pending_orders),
            len(open_positions),
        )

        cancelled = 0
        errors = 0
        for order_id in pending_orders:
            try:
                executor.cancel_order(order_id)
                cancelled += 1
            except Exception:
                log.exception("Failed to cancel order %s", order_id)
                errors += 1

        squared = 0
        for pos in open_positions:
            try:
                executor.place_exit(
                    symbol=pos["symbol"],
                    exchange=pos.get("exchange", "NSE"),
                    direction=pos["direction"],
                    quantity=pos["quantity"],
                    order_type="MARKET",
                )
                squared += 1
            except Exception:
                log.exception("Failed to square off %s", pos["symbol"])
                errors += 1

        return {"cancelled": cancelled, "squared_off": squared, "errors": errors}
