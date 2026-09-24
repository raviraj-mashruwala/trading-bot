"""Fade an extreme: price outside a Bollinger band with RSI confirming exhaustion."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal

RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0


class MeanReversionStrategy(Strategy):
    name = StrategyName.MEAN_REVERSION

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        price = snapshot.last_close

        if price <= snapshot.bb_lower and snapshot.rsi_14 <= RSI_OVERSOLD:
            return build_signal(
                Direction.LONG,
                entry_price=price,
                atr=snapshot.atr_14,
                strength=min(1.0, (RSI_OVERSOLD - snapshot.rsi_14) / RSI_OVERSOLD + 0.5),
            )

        if price >= snapshot.bb_upper and snapshot.rsi_14 >= RSI_OVERBOUGHT:
            return build_signal(
                Direction.SHORT,
                entry_price=price,
                atr=snapshot.atr_14,
                strength=min(1.0, (snapshot.rsi_14 - RSI_OVERBOUGHT) / (100.0 - RSI_OVERBOUGHT) + 0.5),
            )

        return None
