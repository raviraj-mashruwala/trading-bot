"""Tests for AnalysisPipeline._build_stock_metrics()."""

import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo
from tradingbot.analysis.pipeline import AnalysisPipeline

IST = ZoneInfo("Asia/Kolkata")


def _make_daily_df(n=30, base_price=500, avg_vol=600000):
    now = datetime.now(tz=IST)
    dates = [now - timedelta(days=n - i) for i in range(n)]
    np.random.seed(42)
    close = base_price + np.cumsum(np.random.randn(n) * 2)
    return pd.DataFrame({
        "open": close + np.random.randn(n),
        "high": close + abs(np.random.randn(n) * 3),
        "low": close - abs(np.random.randn(n) * 3),
        "close": close,
        "volume": np.random.randint(int(avg_vol * 0.8), int(avg_vol * 1.2), n),
    }, index=pd.DatetimeIndex(dates, name="date"))


def _make_pipeline(instrument_cache, candle_store):
    pipeline = AnalysisPipeline.__new__(AnalysisPipeline)
    pipeline._instrument_cache = instrument_cache
    pipeline._candles = candle_store
    return pipeline


def test_build_stock_metrics_returns_list():
    cache = MagicMock()
    cache.get_all.return_value = [
        {"token": 1, "symbol": "RELIANCE", "exchange": "NSE", "lot_size": 1, "tick_size": 0.05},
        {"token": 2, "symbol": "TCS", "exchange": "NSE", "lot_size": 1, "tick_size": 0.05},
    ]
    store = MagicMock()
    store.read.return_value = _make_daily_df(30, 500, 600000)

    pipeline = _make_pipeline(cache, store)
    result = pipeline._build_stock_metrics()
    assert isinstance(result, list)
    assert len(result) == 2


def test_build_stock_metrics_has_required_fields():
    cache = MagicMock()
    cache.get_all.return_value = [
        {"token": 1, "symbol": "TEST", "exchange": "NSE", "lot_size": 1, "tick_size": 0.05},
    ]
    store = MagicMock()
    store.read.return_value = _make_daily_df(30, 500, 600000)

    pipeline = _make_pipeline(cache, store)
    result = pipeline._build_stock_metrics()
    stock = result[0]
    for field in ["symbol", "token", "last_price", "avg_volume", "atr_pct", "trading_days"]:
        assert field in stock, f"Missing field: {field}"
    assert stock["last_price"] > 0
    assert stock["avg_volume"] > 0
    assert stock["atr_pct"] > 0


def test_build_stock_metrics_empty_cache():
    cache = MagicMock()
    cache.get_all.return_value = []
    store = MagicMock()

    pipeline = _make_pipeline(cache, store)
    result = pipeline._build_stock_metrics()
    assert result == []


def test_build_stock_metrics_no_cache():
    pipeline = AnalysisPipeline.__new__(AnalysisPipeline)
    pipeline._instrument_cache = None
    pipeline._candles = MagicMock()
    result = pipeline._build_stock_metrics()
    assert result == []


def test_build_stock_metrics_skips_empty_candles():
    cache = MagicMock()
    cache.get_all.return_value = [
        {"token": 1, "symbol": "EMPTY", "exchange": "NSE", "lot_size": 1, "tick_size": 0.05},
    ]
    store = MagicMock()
    store.read.return_value = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    pipeline = _make_pipeline(cache, store)
    result = pipeline._build_stock_metrics()
    assert result == []
