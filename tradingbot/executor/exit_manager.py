"""Exit rules. Deterministic, ordered, and independent of any model."""

from __future__ import annotations

from datetime import datetime, time
from enum import Enum

from tradingbot.core.models import Direction


class ExitDecision(str, Enum):
    HOLD = "hold"
    BOOK_TARGET_1 = "book_target_1"
    BOOK_TARGET_2 = "book_target_2"
    STOP_HIT = "stop_hit"
    SQUARE_OFF = "square_off"


class ExitManager:
    """Decides what to do with a filled leg at the current price and time."""

    def __init__(self, square_off_time: time) -> None:
        self.square_off_time = square_off_time

    def decide(self, state, price: float, now: datetime) -> ExitDecision:
        """Square-off beats everything; then the stop; then targets."""
        if state.filled_quantity <= 0:
            return ExitDecision.HOLD

        if now.timetz().replace(tzinfo=None) >= self.square_off_time:
            return ExitDecision.SQUARE_OFF

        leg = state.leg
        stop = state.current_stop

        if leg.direction is Direction.LONG:
            if price <= stop:
                return ExitDecision.STOP_HIT
            if state.target_1_booked:
                if leg.target_2 > 0 and price >= leg.target_2:
                    return ExitDecision.BOOK_TARGET_2
            elif price >= leg.target_1:
                return ExitDecision.BOOK_TARGET_1
        else:
            if price >= stop:
                return ExitDecision.STOP_HIT
            if state.target_1_booked:
                if leg.target_2 > 0 and price <= leg.target_2:
                    return ExitDecision.BOOK_TARGET_2
            elif price <= leg.target_1:
                return ExitDecision.BOOK_TARGET_1

        return ExitDecision.HOLD

    def trail_stop(self, state) -> float:
        """Ratchet the stop to breakeven. It may tighten, never loosen."""
        breakeven = state.entry_fill_price
        if state.leg.direction is Direction.LONG:
            return max(state.current_stop, breakeven)
        return min(state.current_stop, breakeven)
