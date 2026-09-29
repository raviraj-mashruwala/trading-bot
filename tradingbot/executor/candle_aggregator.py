from __future__ import annotations

import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Callable


@dataclass(frozen=True)
class LiveCandle:
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    is_complete: bool
    has_gap: bool = False


class CandleAggregator:
    HISTORY_DEPTH = 50

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._current: dict[str, dict[str, _CandleBuilder]] = defaultdict(dict)
        self._history: dict[str, dict[str, deque[LiveCandle]]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=CandleAggregator.HISTORY_DEPTH))
        )
        self._last_price: dict[str, float] = {}
        self._callbacks: dict[str, list[Callable]] = defaultdict(list)

    def on_tick(self, symbol: str, price: float, volume: int, timestamp: datetime) -> None:
        with self._locks[symbol]:
            self._last_price[symbol] = price
            for tf in ("1min", "5min"):
                boundary = _candle_boundary(timestamp, tf)
                builder = self._current[symbol].get(tf)
                if builder is None or builder.boundary != boundary:
                    if builder is not None:
                        closed = builder.to_candle(symbol, tf, is_complete=True)
                        self._history[symbol][tf].append(closed)
                        self._fire(f"{tf}_close", symbol, closed)
                    self._current[symbol][tf] = _CandleBuilder(boundary, price, volume)
                else:
                    builder.update(price, volume)

    def get_candles(self, symbol: str, timeframe: str) -> list[LiveCandle]:
        with self._locks[symbol]:
            return list(self._history[symbol][timeframe])

    def get_current(self, symbol: str, timeframe: str) -> LiveCandle | None:
        with self._locks[symbol]:
            builder = self._current.get(symbol, {}).get(timeframe)
            if builder is None:
                return None
            return builder.to_candle(symbol, timeframe, is_complete=False)

    def last_price(self, symbol: str) -> float | None:
        return self._last_price.get(symbol)

    def subscribe(self, event: str, callback: Callable) -> None:
        self._callbacks[event].append(callback)

    def seed(self, symbol: str, timeframe: str, candles: list[LiveCandle]) -> None:
        with self._locks[symbol]:
            q = self._history[symbol][timeframe]
            for c in candles:
                q.append(c)

    def close_stale_candles(self, symbol: str, now: datetime) -> None:
        with self._locks[symbol]:
            for tf in ("1min", "5min"):
                builder = self._current[symbol].get(tf)
                if builder is None:
                    continue
                current_boundary = _candle_boundary(now, tf)
                if builder.boundary != current_boundary:
                    closed = builder.to_candle(symbol, tf, is_complete=True, has_gap=True)
                    self._history[symbol][tf].append(closed)
                    self._fire(f"{tf}_close", symbol, closed)
                    self._current[symbol][tf] = None

    def _fire(self, event: str, symbol: str, candle: LiveCandle) -> None:
        for cb in self._callbacks.get(event, []):
            cb(symbol, candle)


def _candle_boundary(ts: datetime, timeframe: str) -> datetime:
    if timeframe == "1min":
        return ts.replace(second=0, microsecond=0)
    minute = (ts.minute // 5) * 5
    return ts.replace(minute=minute, second=0, microsecond=0)


class _CandleBuilder:
    __slots__ = ("boundary", "open", "high", "low", "close", "volume")

    def __init__(self, boundary: datetime, price: float, volume: int) -> None:
        self.boundary = boundary
        self.open = price
        self.high = price
        self.low = price
        self.close = price
        self.volume = volume

    def update(self, price: float, volume: int) -> None:
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += volume

    def to_candle(self, symbol: str, timeframe: str, is_complete: bool,
                  has_gap: bool = False) -> LiveCandle:
        return LiveCandle(
            symbol=symbol, timeframe=timeframe, timestamp=self.boundary,
            open=self.open, high=self.high, low=self.low, close=self.close,
            volume=self.volume, is_complete=is_complete, has_gap=has_gap,
        )
