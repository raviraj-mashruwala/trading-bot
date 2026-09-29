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


def test_build_stock_metrics_includes_gap_score():
    cache = MagicMock()
    cache.get_all.return_value = [
        {"token": 1, "symbol": "GAPPER", "exchange": "NSE", "lot_size": 1, "tick_size": 0.05},
    ]
    store = MagicMock()
    n = 30
    dates = [datetime.now(tz=IST) - timedelta(days=n - i) for i in range(n)]
    close = np.full(n, 500.0)
    close[-1] = 502.0  # today's close
    opens = np.full(n, 500.0)
    opens[-1] = 510.0  # today opened with a 2% gap
    df = pd.DataFrame({
        "open": opens, "high": close + 5, "low": close - 5,
        "close": close, "volume": np.full(n, 600000),
    }, index=pd.DatetimeIndex(dates, name="date"))
    store.read.return_value = df

    pipeline = _make_pipeline(cache, store)
    result = pipeline._build_stock_metrics()
    assert len(result) == 1
    assert "gap_analysis" in result[0]["factor_scores"]
    assert result[0]["factor_scores"]["gap_analysis"] > 0


# ── New tests for 9-factor completeness ──────────────────────────────────────

NINE_FACTOR_KEYS = {
    "volume_surge", "relative_strength", "atr_expansion",
    "price_structure", "delivery_pct", "sector_momentum",
    "gap_analysis", "candlestick_pattern", "volume_profile",
}


def test_all_nine_factor_keys_present():
    cache = MagicMock()
    cache.get_all.return_value = [
        {"token": 1, "symbol": "TCS", "exchange": "NSE", "lot_size": 1, "tick_size": 0.05},
    ]
    store = MagicMock()
    store.read.return_value = _make_daily_df(30)

    pipeline = _make_pipeline(cache, store)
    result = pipeline._build_stock_metrics()
    assert len(result) == 1
    assert NINE_FACTOR_KEYS == set(result[0]["factor_scores"].keys())


def test_volume_surge_score_in_range():
    cache = MagicMock()
    cache.get_all.return_value = [
        {"token": 1, "symbol": "TCS", "exchange": "NSE", "lot_size": 1, "tick_size": 0.05},
    ]
    store = MagicMock()
    store.read.return_value = _make_daily_df(30)

    pipeline = _make_pipeline(cache, store)
    result = pipeline._build_stock_metrics()
    score = result[0]["factor_scores"]["volume_surge"]
    assert 0.0 <= score <= 100.0


def test_relative_strength_score_in_range():
    cache = MagicMock()
    cache.get_all.return_value = [
        {"token": 1, "symbol": "TCS", "exchange": "NSE", "lot_size": 1, "tick_size": 0.05},
    ]
    store = MagicMock()
    store.read.return_value = _make_daily_df(30)

    pipeline = _make_pipeline(cache, store)
    result = pipeline._build_stock_metrics(nifty_5d_change=0.0)
    score = result[0]["factor_scores"]["relative_strength"]
    assert 0.0 <= score <= 100.0


def test_price_structure_above_50_for_uptrend():
    """Close > SMA20 in uptrend must score above 50."""
    cache = MagicMock()
    cache.get_all.return_value = [
        {"token": 1, "symbol": "TCS", "exchange": "NSE", "lot_size": 1, "tick_size": 0.05},
    ]
    store = MagicMock()
    n = 30
    # Strict uptrend: close rises 1 each day, so last close > SMA20
    close = np.arange(480.0, 480.0 + n)
    df = pd.DataFrame({
        "open": close - 0.5, "high": close + 1, "low": close - 1,
        "close": close, "volume": np.full(n, 600000),
    })
    store.read.return_value = df

    pipeline = _make_pipeline(cache, store)
    result = pipeline._build_stock_metrics()
    assert result[0]["factor_scores"]["price_structure"] > 50.0


def test_delivery_pct_uses_fetched_data():
    """delivery_pct must use real delivery data when provided, not hardcoded 50.0."""
    cache = MagicMock()
    cache.get_all.return_value = [
        {"token": 1, "symbol": "TCS", "exchange": "NSE", "lot_size": 1, "tick_size": 0.05, "sector": "IT"},
    ]
    store = MagicMock()
    store.read.return_value = _make_daily_df(30)

    pipeline = _make_pipeline(cache, store)
    result = pipeline._build_stock_metrics(delivery_data={"TCS": 78.5})
    assert result[0]["factor_scores"]["delivery_pct"] == pytest.approx(78.5)


def test_delivery_pct_defaults_50_when_symbol_missing():
    cache = MagicMock()
    cache.get_all.return_value = [
        {"token": 1, "symbol": "TCS", "exchange": "NSE", "lot_size": 1, "tick_size": 0.05, "sector": "IT"},
    ]
    store = MagicMock()
    store.read.return_value = _make_daily_df(30)

    pipeline = _make_pipeline(cache, store)
    result = pipeline._build_stock_metrics(delivery_data={})  # TCS not in data
    assert result[0]["factor_scores"]["delivery_pct"] == pytest.approx(50.0)


def test_volume_profile_not_always_neutral():
    """volume_profile factor must use real score, not hardcoded 50.0."""
    cache = MagicMock()
    cache.get_all.return_value = [
        {"token": 1, "symbol": "TCS", "exchange": "NSE", "lot_size": 1, "tick_size": 0.05},
    ]
    store = MagicMock()
    # Build df with volume concentrated in 90-105 range, last close at 130.
    # volume_profile will compute POC ~95-100, VAH ~105, VAL ~90.
    # close=130 > VAH → score > 70.
    n = 30
    closes = np.linspace(90, 105, n)   # prices spread 90-105 with even volume
    closes[-1] = 130.0                 # last close well above value area
    df = pd.DataFrame({
        "open": closes - 1, "high": closes + 2,
        "low": closes - 2, "close": closes,
        "volume": np.full(n, 1_000_000),
    })
    store.read.return_value = df

    pipeline = _make_pipeline(cache, store)
    result = pipeline._build_stock_metrics()
    score = result[0]["factor_scores"]["volume_profile"]
    # close=130 above VAH (~105) → bullish breakout → score > 50
    assert score > 50.0


def test_candlestick_pattern_not_always_neutral():
    """candlestick_pattern must use real score, not hardcoded 50.0."""
    cache = MagicMock()
    cache.get_all.return_value = [
        {"token": 1, "symbol": "TCS", "exchange": "NSE", "lot_size": 1, "tick_size": 0.05},
    ]
    store = MagicMock()
    # Build df where last 3 candles form a bullish marubozu
    n = 30
    close = np.arange(480.0, 480.0 + n)
    opens = close.copy()
    highs = close + 1
    lows = close - 1
    # Last candle: bullish marubozu (open=low, close=high, no wicks)
    opens[-1] = close[-2]        # open at prior close
    highs[-1] = opens[-1] + 15   # high = close (no upper wick)
    lows[-1] = opens[-1]         # low = open (no lower wick)
    close[-1] = highs[-1]
    df = pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": close, "volume": np.full(n, 600000),
    })
    store.read.return_value = df

    pipeline = _make_pipeline(cache, store)
    result = pipeline._build_stock_metrics()
    score = result[0]["factor_scores"]["candlestick_pattern"]
    # Bullish marubozu → score should be > 50 (not the old hardcoded 50.0)
    assert score > 50.0


def test_sector_momentum_populated_for_all_stocks():
    """sector_momentum must not be the default 50.0 when sector has multiple stocks."""
    cache = MagicMock()
    cache.get_all.return_value = [
        {"token": 1, "symbol": "TCS", "exchange": "NSE", "lot_size": 1, "tick_size": 0.05, "sector": "IT"},
        {"token": 2, "symbol": "INFY", "exchange": "NSE", "lot_size": 1, "tick_size": 0.05, "sector": "IT"},
    ]
    store = MagicMock()
    # Uptrending stock — 5d return positive → sector_momentum > 50
    n = 30
    close = np.arange(480.0, 480.0 + n)
    df = pd.DataFrame({
        "open": close - 0.5, "high": close + 1, "low": close - 1,
        "close": close, "volume": np.full(n, 600000),
    })
    store.read.return_value = df

    pipeline = _make_pipeline(cache, store)
    result = pipeline._build_stock_metrics()
    assert len(result) == 2
    # sector_momentum should reflect positive sector return, not stuck at 50
    assert result[0]["factor_scores"]["sector_momentum"] > 50.0
