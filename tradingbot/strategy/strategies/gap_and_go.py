"""Gap-and-go strategy: trades opening gaps that continue in gap direction."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal

GAP_THRESHOLD_PCT = 1.0
VOLUME_SURGE = 2.0
LOOKBACK = 20


class GapAndGoStrategy(Strategy):
    name = StrategyName.GAP_AND_GO

    def generate_signal(
        self, df: pd.DataFrame, snapshot: IndicatorSnapshot
    ) -> Signal | None:
        if len(df) < LOOKBACK + 2:
            return None

        prev_close = float(df["close"].iloc[-2])
        curr_open = float(df["open"].iloc[-1])
        gap_pct = (curr_open - prev_close) / prev_close * 100

        if abs(gap_pct) < GAP_THRESHOLD_PCT:
            return None

        avg_vol = float(df["volume"].iloc[-LOOKBACK - 1 : -1].mean())
        curr_vol = float(df["volume"].iloc[-1])
        if avg_vol <= 0 or curr_vol / avg_vol < VOLUME_SURGE:
            return None

        # Gap up: hold above gap level = long
        if gap_pct > 0 and snapshot.last_close >= curr_open:
            return build_signal(
                Direction.LONG,
                snapshot.last_close,
                snapshot.atr_14,
                strength=min(1.0, abs(gap_pct) / 3.0),
            )

        # Gap down: hold below gap level = short
        if gap_pct < 0 and snapshot.last_close <= curr_open:
            return build_signal(
                Direction.SHORT,
                snapshot.last_close,
                snapshot.atr_14,
                strength=min(1.0, abs(gap_pct) / 3.0),
            )
        return None
