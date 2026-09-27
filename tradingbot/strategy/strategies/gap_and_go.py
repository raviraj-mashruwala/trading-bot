"""Gap-and-go strategy: trades opening gaps that continue in gap direction."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy


class GapAndGoStrategy(Strategy):
    name = StrategyName.GAP_AND_GO

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        return None  # Stub — full implementation in a later task.
