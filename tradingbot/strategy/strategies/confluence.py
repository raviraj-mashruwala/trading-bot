"""Meta-strategy: count how many timeframes agree on direction."""

from __future__ import annotations

from tradingbot.core.models import Direction, IndicatorSnapshot


class ConfluenceScorer:
    """Count agreement across 5 dimensions: trend, momentum, RSI, supertrend, VWAP.

    Returns 0-5 where 5 means all dimensions align with the proposed direction.
    """

    def score(self, snapshot: IndicatorSnapshot, direction: Direction) -> int:
        count = 0
        is_long = direction is Direction.LONG

        # 1. Daily trend: price vs 50 SMA
        if is_long and snapshot.last_close > snapshot.sma_50:
            count += 1
        elif not is_long and snapshot.last_close < snapshot.sma_50:
            count += 1

        # 2. Momentum: MACD alignment
        if is_long and snapshot.macd > snapshot.macd_signal:
            count += 1
        elif not is_long and snapshot.macd < snapshot.macd_signal:
            count += 1

        # 3. RSI alignment (not extreme)
        if is_long and 40 < snapshot.rsi_14 < 70:
            count += 1
        elif not is_long and 30 < snapshot.rsi_14 < 60:
            count += 1

        # 4. Supertrend direction
        if is_long and snapshot.supertrend_direction == 1:
            count += 1
        elif not is_long and snapshot.supertrend_direction == -1:
            count += 1

        # 5. VWAP alignment
        if is_long and snapshot.last_close > snapshot.vwap:
            count += 1
        elif not is_long and snapshot.last_close < snapshot.vwap:
            count += 1

        return count
