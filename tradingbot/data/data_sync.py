"""Incrementally sync market data from Kite Connect to local SQLite stores."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from tradingbot.data.candle_store import CandleStore
from tradingbot.data.instrument_cache import InstrumentCache
from tradingbot.data.kite_client import KiteClient

IST = ZoneInfo("Asia/Kolkata")
log = logging.getLogger(__name__)

KITE_MAX_DAYS = {
    "day": 2000,
    "60minute": 400,
    "30minute": 200,
    "15minute": 200,
    "5minute": 100,
    "minute": 60,
}


class DataSync:
    """Incrementally syncs market data from Kite to local stores."""

    def __init__(
        self,
        client: KiteClient,
        instrument_cache: InstrumentCache,
        candle_store: CandleStore,
    ):
        self._client = client
        self._instruments = instrument_cache
        self._candles = candle_store

    def sync_instruments(self) -> int:
        """Fetch all NSE instruments and refresh local cache."""
        raw = self._client.fetch_instruments("NSE")
        count = self._instruments.refresh(raw)
        log.info("Synced %d NSE equity instruments", count)
        return count

    def sync_daily_candles(
        self, symbols: list[str], lookback_days: int = 365,
    ) -> int:
        """Fetch daily candles for given symbols, incrementally."""
        total = 0
        for symbol in symbols:
            total += self._sync_symbol(symbol, "day", lookback_days)
        return total

    def sync_intraday_candles(
        self, symbols: list[str], interval: str = "15minute",
        lookback_days: int = 60,
    ) -> int:
        """Fetch intraday candles, clamped to Kite API max days."""
        max_days = KITE_MAX_DAYS.get(interval, 60)
        days = min(lookback_days, max_days)
        total = 0
        for symbol in symbols:
            total += self._sync_symbol(symbol, interval, days)
        return total

    def deep_fetch(self, symbols: list[str]) -> int:
        """Fetch 5-minute (100 days) and 1-minute (5 days) candles."""
        total = 0
        for symbol in symbols:
            total += self._sync_symbol(symbol, "5minute", 100)
            total += self._sync_symbol(symbol, "minute", 5)
        return total

    def _sync_symbol(self, symbol: str, interval: str, lookback_days: int) -> int:
        """Fetch and upsert candles for one symbol/interval pair."""
        try:
            token = self._instruments.get_token(symbol)
        except KeyError:
            log.warning("No instrument token for %s, skipping", symbol)
            return 0

        last = self._candles.last_timestamp(symbol, interval)
        if last is not None:
            from_date = last.date() + timedelta(days=1)
        else:
            from_date = date.today() - timedelta(days=lookback_days)

        to_date = date.today()
        if from_date > to_date:
            return 0

        try:
            candles = self._client.fetch_historical(
                instrument_token=token,
                interval=interval,
                from_date=from_date,
                to_date=to_date,
            )
        except Exception:
            log.exception("Failed to fetch %s %s", symbol, interval)
            return 0

        if candles:
            self._candles.upsert(symbol, interval, candles)
            log.info("Synced %d %s candles for %s", len(candles), interval, symbol)
        return len(candles)
