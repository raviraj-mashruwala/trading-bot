"""Bollinger-squeeze strategy: trades volatility expansion after a squeeze."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy


class BollingerSqueezeStrategy(Strategy):
    name = StrategyName.BOLLINGER_SQUEEZE

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        return None  # Stub — full implementation in a later task.
