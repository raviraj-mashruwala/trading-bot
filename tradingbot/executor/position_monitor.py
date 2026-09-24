"""Reads live position state from the broker."""

from __future__ import annotations

from tradingbot.core.broker import BrokerInterface
from tradingbot.core.models import Position


class PositionMonitor:
    """Turns the broker's position list into something keyed by symbol."""

    def __init__(self, broker: BrokerInterface) -> None:
        self.broker = broker

    def snapshot(self) -> dict[str, Position]:
        return {position.symbol: position for position in self.broker.get_positions()}

    def unrealised_pnl(self, positions: dict[str, Position]) -> float:
        total = 0.0
        for symbol, position in positions.items():
            total += position.unrealised_pnl(self.broker.get_ltp(symbol))
        return total
