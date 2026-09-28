"""Tests for DataSync.full_sync() convenience method."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo
from tradingbot.data.data_sync import DataSync
from tradingbot.data.instrument_cache import InstrumentCache
from tradingbot.data.candle_store import CandleStore

IST = ZoneInfo("Asia/Kolkata")


def _mock_client(instrument_count=2):
    client = MagicMock()
    client.fetch_instruments.return_value = [
        {"instrument_token": i + 1, "tradingsymbol": f"STOCK{i}",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"}
        for i in range(instrument_count)
    ]
    client.fetch_historical.return_value = [
        {"date": datetime(2026, 9, 26, tzinfo=IST),
         "open": 500, "high": 520, "low": 490, "close": 510, "volume": 100000},
    ]
    return client


def test_full_sync_returns_stats(tmp_path):
    cache = InstrumentCache(tmp_path / "inst.db")
    store = CandleStore(tmp_path / "candles.db")
    sync = DataSync(_mock_client(3), cache, store)

    stats = sync.full_sync(daily_lookback=30, intraday_lookback=7)

    assert stats["instruments"] == 3
    assert stats["symbols"] == 3
    assert "daily_candles" in stats
    assert "intraday_candles" in stats


def test_full_sync_empty_instruments(tmp_path):
    cache = InstrumentCache(tmp_path / "inst.db")
    store = CandleStore(tmp_path / "candles.db")
    client = MagicMock()
    client.fetch_instruments.return_value = []
    sync = DataSync(client, cache, store)

    stats = sync.full_sync()

    assert stats["instruments"] == 0
    assert stats["daily_candles"] == 0
    assert stats["symbols"] == 0


def test_full_sync_uses_default_lookbacks(tmp_path):
    cache = InstrumentCache(tmp_path / "inst.db")
    store = CandleStore(tmp_path / "candles.db")
    sync = DataSync(_mock_client(1), cache, store)

    stats = sync.full_sync()

    assert stats["instruments"] == 1
