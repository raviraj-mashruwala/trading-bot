"""Tests for new indicator functions: ADX, Supertrend, Camarilla, VWAP bands,
Bollinger bandwidth, and volume profile."""

import numpy as np
import pandas as pd
import pytest
from tradingbot.strategy.indicators import (
    adx, supertrend, camarilla_pivots, vwap_bands, bollinger_bandwidth,
    volume_profile,
)


@pytest.fixture
def sample_df():
    np.random.seed(42)
    n = 100
    close = 2500 + np.cumsum(np.random.randn(n) * 5)
    high = close + np.abs(np.random.randn(n) * 3)
    low = close - np.abs(np.random.randn(n) * 3)
    volume = np.random.randint(50000, 200000, n)
    return pd.DataFrame({
        "open": close + np.random.randn(n),
        "high": high, "low": low, "close": close,
        "volume": volume,
    })


def test_adx_returns_series(sample_df):
    result = adx(sample_df, period=14)
    assert isinstance(result, pd.Series)
    assert len(result) == len(sample_df)
    valid = result.dropna()
    assert len(valid) > 0
    assert all(0 <= v <= 100 for v in valid)


def test_supertrend_returns_series(sample_df):
    upper, lower, direction = supertrend(sample_df, period=10, multiplier=3.0)
    assert len(upper) == len(sample_df)
    assert len(direction) == len(sample_df)
    # direction is 1 (up) or -1 (down)
    valid_dir = direction.dropna()
    assert all(d in (1, -1) for d in valid_dir)


def test_camarilla_pivots_has_correct_keys(sample_df):
    result = camarilla_pivots(sample_df)
    expected_keys = {"h1", "h2", "h3", "h4", "l1", "l2", "l3", "l4"}
    assert set(result.keys()) == expected_keys
    assert all(isinstance(v, float) for v in result.values())


def test_vwap_bands(sample_df):
    vwap_line, upper_1, lower_1, upper_2, lower_2 = vwap_bands(sample_df)
    assert len(vwap_line) == len(sample_df)
    # upper bands above vwap, lower below
    last_idx = -1
    assert upper_1.iloc[last_idx] >= vwap_line.iloc[last_idx]
    assert lower_1.iloc[last_idx] <= vwap_line.iloc[last_idx]


def test_bollinger_bandwidth(sample_df):
    bw = bollinger_bandwidth(sample_df["close"])
    assert isinstance(bw, pd.Series)
    valid = bw.dropna()
    assert all(v >= 0 for v in valid)


def test_volume_profile(sample_df):
    result = volume_profile(sample_df, bins=20)
    assert "poc" in result
    assert "vah" in result
    assert "val" in result
    assert result["vah"] >= result["poc"] >= result["val"]


def test_adx_monotonic_trend_is_high():
    """Strong trend should produce high ADX."""
    n = 100
    closes = np.linspace(100, 200, n)
    df = pd.DataFrame({
        "open": closes - 0.5,
        "high": closes + 1.0,
        "low": closes - 1.0,
        "close": closes,
        "volume": np.full(n, 100000),
    })
    result = adx(df, period=14)
    # Strong trend, ADX should be reasonably high at end
    assert result.iloc[-1] > 20


def test_supertrend_uptrend_direction():
    """During persistent uptrend, direction should settle to 1."""
    n = 100
    closes = np.linspace(100, 200, n)
    df = pd.DataFrame({
        "open": closes - 0.5,
        "high": closes + 1.0,
        "low": closes - 1.0,
        "close": closes,
        "volume": np.full(n, 100000),
    })
    _, _, direction = supertrend(df, period=10, multiplier=3.0)
    # Latter half should be consistently bullish
    assert direction.iloc[-1] == 1


def test_volume_profile_single_price():
    """All candles at same price — POC should equal that price."""
    n = 50
    price = 1000.0
    df = pd.DataFrame({
        "open": np.full(n, price),
        "high": np.full(n, price + 1),
        "low": np.full(n, price - 1),
        "close": np.full(n, price),
        "volume": np.full(n, 10000),
    })
    result = volume_profile(df, bins=10)
    assert abs(result["poc"] - price) < 2.0
