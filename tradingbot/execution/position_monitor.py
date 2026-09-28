"""Position monitor: partial profit booking + trailing stop loss."""
from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger(__name__)


class PositionMonitor:
    """Monitor positions, book partial profits, trail stop losses.

    Parameters
    ----------
    executor : KiteExecutor-like
        Must expose ``place_exit(symbol, exchange, direction, quantity,
        price=None, order_type="MARKET")`` and ``modify_order(order_id, price)``.
    trail_atr : float
        ATR distance for trailing stop (points).
    partial_pct : float
        Fraction of position to exit at target_1. Uses ``math.floor`` to
        avoid over-exiting odd lots.
    """

    def __init__(
        self,
        executor: Any,
        trail_atr: float = 5.0,
        partial_pct: float = 0.5,
    ) -> None:
        self._executor = executor
        self._trail_atr = trail_atr
        self._partial_pct = partial_pct
        self._positions: dict[str, dict] = {}

    # -- Position lifecycle --------------------------------------------------

    def add_position(self, pos: dict) -> None:
        """Register a position for monitoring."""
        self._positions[pos["symbol"]] = pos

    def remove_position(self, symbol: str) -> None:
        """Stop monitoring *symbol*."""
        self._positions.pop(symbol, None)

    # -- Tick handler --------------------------------------------------------

    def on_tick(self, symbol: str, ltp: float) -> list[dict]:
        """Process a price tick. Returns list of actions taken (may be empty)."""
        pos = self._positions.get(symbol)
        if pos is None:
            return []

        actions: list[dict] = []
        is_long = pos["direction"] == "long"

        # 1. Stop-loss check (highest priority — exit everything)
        if self._sl_hit(is_long, ltp, pos["current_stop"]):
            self._executor.place_exit(
                symbol=symbol,
                exchange="NSE",
                direction=pos["direction"],
                quantity=pos["quantity"],
                order_type="MARKET",
            )
            actions.append({
                "action": "stop_loss_exit",
                "price": ltp,
                "quantity": pos["quantity"],
            })
            self.remove_position(symbol)
            return actions

        # 2. Target-1 partial booking
        if not pos.get("target_1_booked", False):
            if self._target_hit(is_long, ltp, pos["target_1"]):
                partial_qty = max(1, math.floor(pos["quantity"] * self._partial_pct))
                self._executor.place_exit(
                    symbol=symbol,
                    exchange="NSE",
                    direction=pos["direction"],
                    quantity=partial_qty,
                    price=ltp,
                    order_type="LIMIT",
                )
                actions.append({
                    "action": "partial_exit",
                    "price": ltp,
                    "quantity": partial_qty,
                })
                pos["quantity"] -= partial_qty
                pos["target_1_booked"] = True

                # Move SL to breakeven
                pos["current_stop"] = pos["entry_price"]
                if pos.get("sl_order_id"):
                    self._executor.modify_order(
                        pos["sl_order_id"], pos["entry_price"],
                    )
                actions.append({
                    "action": "move_sl_to_breakeven",
                    "new_stop": pos["entry_price"],
                })

        # 3. Trailing stop (only after target_1 booked)
        if pos.get("target_1_booked", False) and self._trail_atr > 0:
            new_stop = self._compute_trail(is_long, ltp)
            if self._trail_improves(is_long, new_stop, pos["current_stop"]):
                pos["current_stop"] = new_stop
                if pos.get("sl_order_id"):
                    self._executor.modify_order(pos["sl_order_id"], new_stop)
                actions.append({"action": "trail_stop", "new_stop": new_stop})

        return actions

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _sl_hit(is_long: bool, ltp: float, stop: float) -> bool:
        return (is_long and ltp <= stop) or (not is_long and ltp >= stop)

    @staticmethod
    def _target_hit(is_long: bool, ltp: float, target: float) -> bool:
        return (is_long and ltp >= target) or (not is_long and ltp <= target)

    def _compute_trail(self, is_long: bool, ltp: float) -> float:
        if is_long:
            return ltp - self._trail_atr
        return ltp + self._trail_atr

    @staticmethod
    def _trail_improves(is_long: bool, new: float, old: float) -> bool:
        return (is_long and new > old) or (not is_long and new < old)
