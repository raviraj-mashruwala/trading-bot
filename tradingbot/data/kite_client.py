from __future__ import annotations

import time
import threading
from collections import deque
from datetime import date, datetime
from typing import Any


class KiteRateLimiter:
    """Token-bucket rate limiter for Kite API calls."""

    def __init__(self, max_per_sec: int = 3):
        self._max = max_per_sec
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            while self._timestamps and now - self._timestamps[0] > 1.0:
                self._timestamps.popleft()
            if len(self._timestamps) >= self._max:
                sleep_until = self._timestamps[0] + 1.0
                time.sleep(max(0, sleep_until - now))
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] > 1.0:
                    self._timestamps.popleft()
            self._timestamps.append(time.monotonic())


class KiteClient:
    """Thin wrapper around kiteconnect.KiteConnect with rate limiting."""

    def __init__(self, kite: Any, rate_limit_per_sec: int = 3):
        self._kite = kite
        self._limiter = KiteRateLimiter(rate_limit_per_sec)

    @property
    def kite(self) -> Any:
        return self._kite

    def fetch_instruments(self, exchange: str = "NSE") -> list[dict]:
        self._limiter.acquire()
        return self._kite.instruments(exchange)

    def fetch_historical(
        self,
        instrument_token: int,
        interval: str,
        from_date: date,
        to_date: date,
    ) -> list[dict]:
        self._limiter.acquire()
        return self._kite.historical_data(
            instrument_token, from_date, to_date, interval,
        )

    def get_margins(self, segment: str = "equity") -> dict:
        self._limiter.acquire()
        return self._kite.margins(segment)

    def get_ltp(self, symbols: list[str]) -> dict:
        self._limiter.acquire()
        return self._kite.ltp(symbols)

    def get_positions(self) -> dict:
        self._limiter.acquire()
        return self._kite.positions()

    def place_order(self, **kwargs: Any) -> str:
        self._limiter.acquire()
        return self._kite.place_order(**kwargs)

    def modify_order(self, **kwargs: Any) -> str:
        self._limiter.acquire()
        return self._kite.modify_order(**kwargs)

    def cancel_order(self, variety: str, order_id: str) -> str:
        self._limiter.acquire()
        return self._kite.cancel_order(variety, order_id)

    def profile(self) -> dict:
        self._limiter.acquire()
        return self._kite.profile()
