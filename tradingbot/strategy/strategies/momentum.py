"""Trend continuation: moving averages stacked and MACD confirming, not yet extended."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal

RSI_OVERBOUGHT = 75.0
RSI_OVERSOLD = 25.0
RSI_LONG_FLOOR = 55.0
RSI_SHORT_CEILING = 45.0


class MomentumStrategy(Strategy):
    name = StrategyName.MOMENTUM

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        price = snapshot.last_close
        macd_above_signal = snapshot.macd > snapshot.macd_signal

        uptrend = price > snapshot.sma_20 > snapshot.sma_50
        if uptrend and macd_above_signal and RSI_LONG_FLOOR <= snapshot.rsi_14 < RSI_OVERBOUGHT:
            return build_signal(
                Direction.LONG,
                entry_price=price,
                atr=snapshot.atr_14,
                strength=min(1.0, (snapshot.rsi_14 - RSI_LONG_FLOOR) / (RSI_OVERBOUGHT - RSI_LONG_FLOOR)),
            )

        downtrend = price < snapshot.sma_20 < snapshot.sma_50
        if downtrend and not macd_above_signal and RSI_OVERSOLD < snapshot.rsi_14 <= RSI_SHORT_CEILING:
            return build_signal(
                Direction.SHORT,
                entry_price=price,
                atr=snapshot.atr_14,
                strength=min(1.0, (RSI_SHORT_CEILING - snapshot.rsi_14) / (RSI_SHORT_CEILING - RSI_OVERSOLD)),
            )

        return None
