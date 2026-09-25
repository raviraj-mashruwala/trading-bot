"""Trade the first pullback into VWAP in the direction of the prevailing trend."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal

MAX_VWAP_DISTANCE_PCT = 0.5


class VWAPBounceStrategy(Strategy):
    name = StrategyName.VWAP_BOUNCE

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        if snapshot.vwap <= 0:
            return None

        price = snapshot.last_close
        distance_pct = abs(price - snapshot.vwap) / snapshot.vwap * 100.0
        if distance_pct > MAX_VWAP_DISTANCE_PCT:
            return None

        strength = 1.0 - (distance_pct / MAX_VWAP_DISTANCE_PCT)

        if snapshot.sma_20 > snapshot.sma_50 and price >= snapshot.vwap:
            return build_signal(
                Direction.LONG, entry_price=price, atr=snapshot.atr_14, strength=strength
            )

        if snapshot.sma_20 < snapshot.sma_50 and price <= snapshot.vwap:
            return build_signal(
                Direction.SHORT, entry_price=price, atr=snapshot.atr_14, strength=strength
            )

        return None
