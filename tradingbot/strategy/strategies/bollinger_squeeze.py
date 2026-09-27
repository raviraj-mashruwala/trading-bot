"""Bollinger-squeeze strategy: trades volatility expansion after a squeeze."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal

SQUEEZE_THRESHOLD = 3.0  # bandwidth percentage below this = squeeze


class BollingerSqueezeStrategy(Strategy):
    name = StrategyName.BOLLINGER_SQUEEZE

    def generate_signal(
        self, df: pd.DataFrame, snapshot: IndicatorSnapshot
    ) -> Signal | None:
        if snapshot.bb_bandwidth > SQUEEZE_THRESHOLD:
            return None

        price = snapshot.last_close

        # Breakout above upper band with trend strength
        if price > snapshot.bb_upper and snapshot.adx_14 > 20:
            return build_signal(Direction.LONG, price, snapshot.atr_14, strength=0.7)

        # Breakdown below lower band with trend strength
        if price < snapshot.bb_lower and snapshot.adx_14 > 20:
            return build_signal(Direction.SHORT, price, snapshot.atr_14, strength=0.7)

        return None
