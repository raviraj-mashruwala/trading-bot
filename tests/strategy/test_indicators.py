import numpy as np
import pandas as pd
import pytest

from tradingbot.strategy.indicators import (
    InsufficientDataError,
    atr,
    bollinger_bands,
    compute_snapshot,
    ema,
    macd,
    pivot_points,
    rsi,
    sma,
    support_resistance,
    vwap,
)


def make_candles(closes, volumes=None, spread=1.0):
    index = pd.date_range("2026-09-01 09:15", periods=len(closes), freq="15min", tz="Asia/Kolkata")
    closes = np.asarray(closes, dtype=float)
    volumes = np.full(len(closes), 10000.0) if volumes is None else np.asarray(volumes, dtype=float)
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes + spread,
            "low": closes - spread,
            "close": closes,
            "volume": volumes,
        },
        index=index,
    )


def test_rsi_of_a_monotonic_rise_approaches_100():
    df = make_candles(np.arange(100, 140, dtype=float))
    assert rsi(df["close"], period=14).iloc[-1] == pytest.approx(100.0, abs=1e-6)


def test_rsi_of_a_monotonic_fall_approaches_zero():
    df = make_candles(np.arange(140, 100, -1, dtype=float))
    assert rsi(df["close"], period=14).iloc[-1] == pytest.approx(0.0, abs=1e-6)


def test_rsi_of_a_flat_series_is_neutral():
    df = make_candles([100.0] * 40)
    assert rsi(df["close"], period=14).iloc[-1] == pytest.approx(50.0)


def test_sma_equals_the_arithmetic_mean_of_the_window():
    series = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
    assert sma(series, period=5).iloc[-1] == pytest.approx(30.0)


def test_ema_weights_recent_values_more_heavily_than_sma():
    series = pd.Series([10.0] * 19 + [100.0])
    assert ema(series, period=20).iloc[-1] > sma(series, period=20).iloc[-1]


def test_macd_line_is_positive_when_the_trend_is_up():
    df = make_candles(np.arange(100, 160, dtype=float))
    macd_line, signal_line = macd(df["close"])
    assert macd_line.iloc[-1] > 0
    assert len(signal_line) == len(macd_line)


def test_bollinger_bands_are_ordered_and_centred_on_the_sma():
    df = make_candles(np.random.default_rng(42).normal(100, 2, 60))
    upper, middle, lower = bollinger_bands(df["close"], period=20, std=2.0)
    assert upper.iloc[-1] > middle.iloc[-1] > lower.iloc[-1]
    assert middle.iloc[-1] == pytest.approx(sma(df["close"], 20).iloc[-1])


def test_atr_of_a_constant_range_equals_that_range():
    df = make_candles([100.0] * 30, spread=2.5)
    assert atr(df, period=14).iloc[-1] == pytest.approx(5.0)


def test_vwap_equals_price_when_price_never_moves():
    df = make_candles([100.0] * 10)
    assert vwap(df).iloc[-1] == pytest.approx(100.0)


def test_vwap_is_pulled_toward_the_high_volume_price():
    df = make_candles([100.0, 200.0], volumes=[1.0, 99.0], spread=0.0)
    assert vwap(df).iloc[-1] == pytest.approx(199.0)


def test_pivot_points_follow_the_classic_formula():
    df = make_candles([100.0, 110.0, 105.0], spread=0.0)
    df.iloc[-1, df.columns.get_loc("high")] = 110.0
    df.iloc[-1, df.columns.get_loc("low")] = 100.0
    df.iloc[-1, df.columns.get_loc("close")] = 105.0

    levels = pivot_points(df)

    assert levels["pivot"] == pytest.approx(105.0)
    assert levels["r1"] == pytest.approx(110.0)
    assert levels["s1"] == pytest.approx(100.0)


def test_support_resistance_clusters_repeated_touches():
    closes = [100.0, 120.0, 100.5, 121.0, 99.8, 120.5, 100.2, 119.5] * 4
    df = make_candles(closes, spread=0.2)

    supports, resistances = support_resistance(df, eps_pct=1.0, min_samples=3)

    assert any(99.0 <= level <= 102.0 for level in supports + resistances)
    assert any(118.0 <= level <= 122.0 for level in supports + resistances)


def test_support_levels_sit_below_the_last_close_and_resistance_above():
    closes = [100.0, 120.0, 100.5, 121.0, 99.8, 120.5, 100.2, 119.5] * 4 + [110.0]
    df = make_candles(closes, spread=0.2)

    supports, resistances = support_resistance(df, eps_pct=1.0, min_samples=3)

    assert all(level < 110.0 for level in supports)
    assert all(level > 110.0 for level in resistances)


def test_compute_snapshot_populates_every_field():
    rng = np.random.default_rng(7)
    df = make_candles(100 + np.cumsum(rng.normal(0, 1, 250)))

    snapshot = compute_snapshot("RELIANCE", df)

    assert snapshot.symbol == "RELIANCE"
    assert snapshot.last_close == pytest.approx(df["close"].iloc[-1])
    assert 0.0 <= snapshot.rsi_14 <= 100.0
    assert snapshot.atr_14 > 0
    assert snapshot.bb_upper > snapshot.bb_lower
    assert isinstance(snapshot.support_levels, list)
    assert isinstance(snapshot.resistance_levels, list)


def test_compute_snapshot_rejects_too_few_candles():
    df = make_candles([100.0] * 10)

    with pytest.raises(InsufficientDataError, match="at least"):
        compute_snapshot("TCS", df)


def test_indicator_functions_never_mutate_the_input_frame():
    df = make_candles(np.arange(100, 300, dtype=float))
    before = df.copy(deep=True)

    compute_snapshot("INFY", df)

    pd.testing.assert_frame_equal(df, before)
