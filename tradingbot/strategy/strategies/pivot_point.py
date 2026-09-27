"""Pivot-point strategy: trades bounces off classic pivot support/resistance."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy


class PivotPointStrategy(Strategy):
    name = StrategyName.PIVOT_POINT

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        return None  # Stub — full implementation in a later task.
