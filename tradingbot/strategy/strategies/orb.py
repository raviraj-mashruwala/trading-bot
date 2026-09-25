"""Opening range breakout: the first hour sets the range, a close outside it trades."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal

OPENING_RANGE_CANDLES = 4  # four 15-minute candles = the first hour


class ORBStrategy(Strategy):
    name = StrategyName.ORB

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        if len(df) <= OPENING_RANGE_CANDLES:
            return None

        opening = df.iloc[:OPENING_RANGE_CANDLES]
        range_high = float(opening["high"].max())
        range_low = float(opening["low"].min())
        range_width = range_high - range_low
        if range_width <= 0:
            return None

        price = snapshot.last_close

        if price > range_high:
            return build_signal(
                Direction.LONG,
                entry_price=price,
                atr=snapshot.atr_14,
                strength=min(1.0, (price - range_high) / range_width),
            )

        if price < range_low:
            return build_signal(
                Direction.SHORT,
                entry_price=price,
                atr=snapshot.atr_14,
                strength=min(1.0, (range_low - price) / range_width),
            )

        return None
