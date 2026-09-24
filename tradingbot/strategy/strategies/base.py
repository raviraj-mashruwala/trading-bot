"""Contract every strategy implements, plus the shared ATR risk geometry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd

from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName

STOP_ATR_MULTIPLE = 1.0
TARGET_1_ATR_MULTIPLE = 2.0
TARGET_2_ATR_MULTIPLE = 3.0


@dataclass(frozen=True)
class Signal:
    """A strategy's raw opinion, before risk sizing or LLM review."""

    direction: Direction
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    strength: float


def build_signal(
    direction: Direction,
    entry_price: float,
    atr: float,
    strength: float,
) -> Signal:
    """Place the stop at 1 ATR and the targets at 2 and 3 ATR from entry."""
    sign = 1.0 if direction is Direction.LONG else -1.0
    return Signal(
        direction=direction,
        entry_price=entry_price,
        stop_loss=entry_price - sign * STOP_ATR_MULTIPLE * atr,
        target_1=entry_price + sign * TARGET_1_ATR_MULTIPLE * atr,
        target_2=entry_price + sign * TARGET_2_ATR_MULTIPLE * atr,
        strength=max(0.0, min(1.0, strength)),
    )


class Strategy(ABC):
    """A strategy reads candles plus indicators and either speaks or stays silent."""

    name: StrategyName

    @abstractmethod
    def generate_signal(
        self,
        df: pd.DataFrame,
        snapshot: IndicatorSnapshot,
    ) -> Signal | None:
        """Return a Signal when this strategy has an opinion, else None."""
