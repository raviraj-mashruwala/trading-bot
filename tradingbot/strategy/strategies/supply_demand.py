"""Supply-demand zone strategy: trades reactions at institutional S/D zones."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy


class SupplyDemandStrategy(Strategy):
    name = StrategyName.SUPPLY_DEMAND

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        return None  # Stub — full implementation in a later task.
