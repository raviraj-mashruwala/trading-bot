"""Deterministic tick replay for regression and integration testing."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from tradingbot.executor.candle_aggregator import CandleAggregator


class TickReplayer:
    """Feed recorded tick data through a CandleAggregator in order.

    Ticks are sorted by timestamp on construction so replay is
    deterministic regardless of input ordering.
    """

    def __init__(self, ticks: list[dict[str, Any]]) -> None:
        self._ticks = sorted(ticks, key=lambda t: t["timestamp"])

    def replay(self, aggregator: CandleAggregator) -> None:
        """Push every tick into the aggregator in timestamp order."""
        for tick in self._ticks:
            aggregator.on_tick(
                tick["symbol"],
                tick["price"],
                tick["volume"],
                tick["timestamp"],
            )

    @property
    def tick_count(self) -> int:
        return len(self._ticks)

    @classmethod
    def from_file(cls, path: str) -> TickReplayer:
        """Load ticks from a JSON file. Each entry must have
        symbol, price, volume, and an ISO-format timestamp string.
        """
        with open(path) as f:
            ticks = json.load(f)
        for t in ticks:
            t["timestamp"] = datetime.fromisoformat(t["timestamp"])
        return cls(ticks)
