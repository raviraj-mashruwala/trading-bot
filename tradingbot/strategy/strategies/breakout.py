"""Price clearing a clustered resistance or support level on expanding volume."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal

VOLUME_LOOKBACK = 20
VOLUME_SURGE_MULTIPLE = 1.5
RSI_LONG_FLOOR = 50.0
RSI_SHORT_CEILING = 50.0


class BreakoutStrategy(Strategy):
    name = StrategyName.BREAKOUT

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        if len(df) < VOLUME_LOOKBACK + 1:
            return None

        recent_volume = float(df["volume"].iloc[-1])
        average_volume = float(df["volume"].iloc[-VOLUME_LOOKBACK - 1 : -1].mean())
        if average_volume <= 0:
            return None
        volume_ratio = recent_volume / average_volume

        price = snapshot.last_close

        nearest_resistance = min(
            (level for level in snapshot.resistance_levels if level < price),
            default=None,
            key=lambda level: price - level,
        )
        if (
            nearest_resistance is not None
            and volume_ratio >= VOLUME_SURGE_MULTIPLE
            and snapshot.rsi_14 >= RSI_LONG_FLOOR
        ):
            return build_signal(
                Direction.LONG,
                entry_price=price,
                atr=snapshot.atr_14,
                strength=min(1.0, volume_ratio / (VOLUME_SURGE_MULTIPLE * 2)),
            )

        nearest_support = min(
            (level for level in snapshot.support_levels if level > price),
            default=None,
            key=lambda level: level - price,
        )
        if (
            nearest_support is not None
            and volume_ratio >= VOLUME_SURGE_MULTIPLE
            and snapshot.rsi_14 <= RSI_SHORT_CEILING
        ):
            return build_signal(
                Direction.SHORT,
                entry_price=price,
                atr=snapshot.atr_14,
                strength=min(1.0, volume_ratio / (VOLUME_SURGE_MULTIPLE * 2)),
            )

        return None
