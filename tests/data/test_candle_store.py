"""Tests for CandleStore — DuckDB OHLCV storage."""

from __future__ import annotations

import threading
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def store(tmp_path):
    from tradingbot.data.candle_store import CandleStore
    s = CandleStore(tmp_path / "test.duckdb")
    yield s
    s.close()


def _sample_df(days: int = 5, base_date: int = 1):
    rows = []
    for i in range(days):
        rows.append({
            "timestamp": datetime(2026, 10, base_date + i, 9, 15),
            "open": 2450.0 + i, "high": 2460.0 + i,
            "low": 2440.0 + i, "close": 2455.0 + i,
            "volume": 100000 + i * 1000,
        })
    return pd.DataFrame(rows)


def test_write_and_read(store):
    df = _sample_df()
    written = store.write("RELIANCE", "day", df)
    assert written == 5
    result = store.read("RELIANCE", "day")
    assert len(result) == 5
    assert list(result.columns) == ["timestamp", "open", "high", "low", "close", "volume"]


def test_write_deduplicates(store):
    df = _sample_df()
    store.write("RELIANCE", "day", df)
    written2 = store.write("RELIANCE", "day", df)
    assert written2 == 0
    assert len(store.read("RELIANCE", "day")) == 5


def test_read_batch(store):
    store.write("RELIANCE", "day", _sample_df())
    store.write("HDFCBANK", "day", _sample_df())
    result = store.read_batch(["RELIANCE", "HDFCBANK", "MISSING"], "day")
    assert "RELIANCE" in result
    assert "HDFCBANK" in result
    assert len(result["RELIANCE"]) == 5


def test_read_with_days_limit(store):
    store.write("RELIANCE", "day", _sample_df(days=10, base_date=1))
    result = store.read("RELIANCE", "day", days=3)
    assert len(result) == 3


def test_read_with_date_range(store):
    store.write("RELIANCE", "day", _sample_df(days=10, base_date=1))
    result = store.read("RELIANCE", "day",
                        from_date=date(2026, 10, 3),
                        to_date=date(2026, 10, 7))
    assert len(result) > 0
    for _, row in result.iterrows():
        ts = row["timestamp"]
        assert ts >= datetime(2026, 10, 3)
        assert ts <= datetime(2026, 10, 7, 23, 59, 59)


def test_last_date(store):
    store.write("RELIANCE", "day", _sample_df())
    last = store.last_date("RELIANCE", "day")
    assert last is not None
    assert last == date(2026, 10, 5)
    assert store.last_date("MISSING", "day") is None


def test_freshness(store):
    store.write("RELIANCE", "day", _sample_df())
    store.write("RELIANCE", "15m", _sample_df())
    fresh = store.freshness()
    assert "day" in fresh
    assert "15m" in fresh


def test_empty_read_returns_empty_df(store):
    result = store.read("NONEXISTENT", "day")
    assert isinstance(result, pd.DataFrame)
    assert result.empty
