"""Strategy registry. Adding a strategy means adding one file and one entry here."""

from __future__ import annotations

from tradingbot.core.models import StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy
from tradingbot.strategy.strategies.breakout import BreakoutStrategy
from tradingbot.strategy.strategies.mean_reversion import MeanReversionStrategy
from tradingbot.strategy.strategies.momentum import MomentumStrategy
from tradingbot.strategy.strategies.orb import ORBStrategy
from tradingbot.strategy.strategies.vwap_bounce import VWAPBounceStrategy

STRATEGY_REGISTRY: dict[StrategyName, Strategy] = {
    StrategyName.BREAKOUT: BreakoutStrategy(),
    StrategyName.MOMENTUM: MomentumStrategy(),
    StrategyName.MEAN_REVERSION: MeanReversionStrategy(),
    StrategyName.VWAP_BOUNCE: VWAPBounceStrategy(),
    StrategyName.ORB: ORBStrategy(),
}


def all_strategies() -> list[Strategy]:
    """Every registered strategy, in registry order."""
    return list(STRATEGY_REGISTRY.values())


__all__ = [
    "STRATEGY_REGISTRY",
    "BreakoutStrategy",
    "MeanReversionStrategy",
    "MomentumStrategy",
    "ORBStrategy",
    "Signal",
    "Strategy",
    "VWAPBounceStrategy",
    "all_strategies",
]
