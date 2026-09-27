"""Relative-strength strategy: long leaders outperforming the benchmark."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy


class RelativeStrengthStrategy(Strategy):
    name = StrategyName.RELATIVE_STRENGTH

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        return None  # Stub — full implementation in a later task.
