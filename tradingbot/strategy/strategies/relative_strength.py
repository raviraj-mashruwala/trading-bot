"""Relative-strength strategy: long leaders outperforming the benchmark."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal


class RelativeStrengthStrategy(Strategy):
    name = StrategyName.RELATIVE_STRENGTH

    def generate_signal(
        self, df: pd.DataFrame, snapshot: IndicatorSnapshot
    ) -> Signal | None:
        if len(df) < 20:
            return None

        price = snapshot.last_close

        # Strong uptrend: price above all MAs, ADX trending, MACD confirms
        above_all_ma = price > snapshot.sma_20 > snapshot.sma_50
        adx_trending = snapshot.adx_14 > 25
        momentum_up = snapshot.macd > snapshot.macd_signal

        if above_all_ma and adx_trending and momentum_up:
            strength = min(1.0, (snapshot.adx_14 - 20) / 30)
            return build_signal(
                Direction.LONG, price, snapshot.atr_14, strength=strength
            )

        # Strong downtrend: price below all MAs, ADX trending, MACD confirms
        below_all_ma = price < snapshot.sma_20 < snapshot.sma_50
        momentum_down = snapshot.macd < snapshot.macd_signal

        if below_all_ma and adx_trending and momentum_down:
            strength = min(1.0, (snapshot.adx_14 - 20) / 30)
            return build_signal(
                Direction.SHORT, price, snapshot.atr_14, strength=strength
            )
        return None
