"""Tests for KiteDataSync — paginated Kite fetcher with resume/retry."""

from __future__ import annotations

import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest


@pytest.fixture
def store(tmp_path):
    from tradingbot.data.candle_store import CandleStore
    s = CandleStore(tmp_path / "test.duckdb")
    yield s
    s.close()


def _mock_kite(candles_per_call=5):
    kite = MagicMock()
    def _fetch(token, interval, from_date, to_date):
        rows = []
        for i in range(candles_per_call):
            rows.append({
                "date": datetime(2026, 10, 1, 9, 15 + i),
                "open": 2450.0, "high": 2460.0,
                "low": 2440.0, "close": 2455.0,
                "volume": 100000,
            })
        return rows
    kite.fetch_historical = MagicMock(side_effect=_fetch)
    return kite


def _mock_instruments():
    cache = MagicMock()
    cache.get_token = MagicMock(return_value=738561)
    cache.get_all = MagicMock(return_value=[
        {"token": 738561, "symbol": "RELIANCE", "sector": "energy"},
    ])
    return cache


def _mock_screening():
    config = MagicMock()
    config.min_volume = 100_000
    config.min_price = 50.0
    config.max_price = 5000.0
    config.min_market_cap_cr = 500.0
    return config


def test_date_chunks():
    from tradingbot.data.kite_data_sync import _date_chunks
    chunks = list(_date_chunks(date(2026, 1, 1), date(2026, 12, 31), max_days=100))
    assert len(chunks) == 4
    assert chunks[0][0] == date(2026, 1, 1)
    assert chunks[-1][1] == date(2026, 12, 31)
    for i in range(len(chunks) - 1):
        assert (chunks[i + 1][0] - chunks[i][1]).days == 1


@pytest.mark.asyncio
async def test_resume_skips_fetched(store):
    from tradingbot.data.kite_data_sync import KiteDataSync
    rows = [{"timestamp": datetime(2026, 10, 1 + i, 9, 15),
             "open": 2450.0, "high": 2460.0, "low": 2440.0,
             "close": 2455.0, "volume": 100000} for i in range(3)]
    store.write("RELIANCE", "day", pd.DataFrame(rows))

    kite = _mock_kite()
    sync = KiteDataSync(kite, store, _mock_instruments(), _mock_screening())
    await sync.fetch_on_demand("RELIANCE", ["day"])

    calls = kite.fetch_historical.call_args_list
    if calls:
        from_arg = calls[0][0][2]
        assert from_arg >= date(2026, 10, 3)


@pytest.mark.asyncio
async def test_per_stock_failure_continues():
    from tradingbot.data.kite_data_sync import KiteDataSync
    from tradingbot.data.candle_store import CandleStore

    with tempfile.TemporaryDirectory() as tmp:
        cs = CandleStore(Path(tmp) / "test.duckdb")
        kite = MagicMock()
        call_count = [0]
        def _fetch(token, interval, from_date, to_date):
            call_count[0] += 1
            if call_count[0] <= 3:  # first stock retries all fail
                raise Exception("Kite API error")
            return [{"date": datetime(2026, 10, 1, 9, 15),
                     "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000}]
        kite.fetch_historical = MagicMock(side_effect=_fetch)

        instruments = MagicMock()
        instruments.get_all = MagicMock(return_value=[
            {"token": 1, "symbol": "FAIL_STOCK", "sector": "x"},
            {"token": 2, "symbol": "OK_STOCK", "sector": "y"},
        ])
        instruments.get_token = MagicMock(side_effect=lambda s: 1 if s == "FAIL_STOCK" else 2)

        sync = KiteDataSync(kite, cs, instruments, _mock_screening())
        report = await sync._sync_interval(["FAIL_STOCK", "OK_STOCK"], "day",
                                           date(2026, 10, 1), date(2026, 10, 1))
        assert len(report.errors) >= 1
        assert report.stocks_synced >= 1
        cs.close()


@pytest.mark.asyncio
async def test_daily_sync_incremental(store):
    from tradingbot.data.kite_data_sync import KiteDataSync
    rows = [{"timestamp": datetime(2026, 10, 1, 9, 15),
             "open": 2450.0, "high": 2460.0, "low": 2440.0,
             "close": 2455.0, "volume": 100000}]
    store.write("RELIANCE", "day", pd.DataFrame(rows))

    kite = _mock_kite(candles_per_call=1)
    sync = KiteDataSync(kite, store, _mock_instruments(), _mock_screening())
    await sync.daily_sync()

    calls = kite.fetch_historical.call_args_list
    if calls:
        from_arg = calls[0][0][2]
        assert from_arg >= date(2026, 10, 1)
