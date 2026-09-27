"""Pivot-point strategy: trades bounces off classic pivot support/resistance."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal

PROXIMITY_PCT = 0.3


class PivotPointStrategy(Strategy):
    name = StrategyName.PIVOT_POINT

    def generate_signal(
        self, df: pd.DataFrame, snapshot: IndicatorSnapshot
    ) -> Signal | None:
        price = snapshot.last_close
        pivot = snapshot.pivot
        if pivot <= 0:
            return None

        # Check support levels: price near support + oversold RSI => long
        for support in sorted(snapshot.support_levels, reverse=True):
            distance_pct = abs(price - support) / price * 100
            if distance_pct < PROXIMITY_PCT and snapshot.rsi_14 < 40:
                return build_signal(
                    Direction.LONG,
                    price,
                    snapshot.atr_14,
                    strength=0.6 + (40 - snapshot.rsi_14) / 100,
                )

        # Check resistance levels: price near resistance + overbought RSI => short
        for resistance in sorted(snapshot.resistance_levels):
            distance_pct = abs(price - resistance) / price * 100
            if distance_pct < PROXIMITY_PCT and snapshot.rsi_14 > 60:
                return build_signal(
                    Direction.SHORT,
                    price,
                    snapshot.atr_14,
                    strength=0.6 + (snapshot.rsi_14 - 60) / 100,
                )
        return None
