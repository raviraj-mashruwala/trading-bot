"""Supply-demand zone strategy: trades reactions at institutional S/D zones."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal

ZONE_PROXIMITY_PCT = 0.5
MIN_MOVE_PCT = 1.5


class SupplyDemandStrategy(Strategy):
    name = StrategyName.SUPPLY_DEMAND

    def generate_signal(
        self, df: pd.DataFrame, snapshot: IndicatorSnapshot
    ) -> Signal | None:
        if len(df) < 30:
            return None

        price = snapshot.last_close
        demand_zones = self._find_zones(df, "demand")
        supply_zones = self._find_zones(df, "supply")

        # Price near demand zone + RSI confirms weakness => long bounce
        for zone_price in demand_zones:
            if abs(price - zone_price) / price * 100 < ZONE_PROXIMITY_PCT:
                if snapshot.rsi_14 < 45:
                    return build_signal(
                        Direction.LONG, price, snapshot.atr_14, strength=0.65
                    )

        # Price near supply zone + RSI confirms strength => short rejection
        for zone_price in supply_zones:
            if abs(price - zone_price) / price * 100 < ZONE_PROXIMITY_PCT:
                if snapshot.rsi_14 > 55:
                    return build_signal(
                        Direction.SHORT, price, snapshot.atr_14, strength=0.65
                    )
        return None

    def _find_zones(self, df: pd.DataFrame, zone_type: str) -> list[float]:
        """Identify S/D zones from sharp historical moves."""
        zones: list[float] = []
        closes = df["close"].values
        for i in range(2, len(closes) - 2):
            move = abs(closes[i + 2] - closes[i]) / closes[i] * 100
            if move < MIN_MOVE_PCT:
                continue
            if zone_type == "demand" and closes[i + 2] > closes[i]:
                zones.append(float(closes[i]))
            elif zone_type == "supply" and closes[i + 2] < closes[i]:
                zones.append(float(closes[i]))
        return zones[-5:] if zones else []
