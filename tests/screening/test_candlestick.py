"""Tests for candlestick pattern scorer."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingbot.screening.candlestick import score_patterns


def _candle(open_: float, high: float, low: float, close: float) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "volume": 1_000_000}


def _df(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


# ── Neutral / edge cases ──────────────────────────────────────────────────────

def test_empty_df_returns_50():
    assert score_patterns(pd.DataFrame()) == pytest.approx(50.0)


def test_insufficient_candles_returns_50():
    df = _df(_candle(100, 105, 95, 102))
    assert score_patterns(df) == pytest.approx(50.0)


def test_score_in_range():
    df = _df(
        *[_candle(100, 105, 95, 102)] * 10
    )
    score = score_patterns(df)
    assert 0.0 <= score <= 100.0


def test_doji_returns_near_50():
    """Doji = open ≈ close → indecision → score near neutral."""
    doji = _candle(100, 105, 95, 100.1)
    df = _df(*[_candle(102, 106, 99, 100)] * 9, doji)
    score = score_patterns(df)
    assert 40.0 <= score <= 60.0


# ── Bullish patterns → score > 50 ────────────────────────────────────────────

def test_bullish_marubozu_scores_above_70():
    """Full bullish body, no wicks → very strong bullish signal."""
    marubozu = _candle(100, 115, 100, 115)  # open=low, close=high
    df = _df(*[_candle(102, 106, 99, 103)] * 9, marubozu)
    assert score_patterns(df) > 70.0


def test_hammer_scores_above_60():
    """Small body at top, long lower wick ≥ 2× body → bullish reversal."""
    # body = 2, lower wick = 8, upper wick = 0.5
    hammer = _candle(110, 110.5, 100, 112)
    df = _df(*[_candle(115, 118, 112, 113)] * 9, hammer)
    assert score_patterns(df) > 60.0


def test_bullish_engulfing_scores_above_65():
    """Curr bullish candle body engulfs prev bearish body."""
    prev_bearish = _candle(105, 106, 99, 100)
    curr_bullish = _candle(99, 110, 98, 109)  # opens lower, closes higher than prev open
    df = _df(*[_candle(108, 112, 105, 107)] * 8, prev_bearish, curr_bullish)
    assert score_patterns(df) > 65.0


def test_morning_star_scores_above_65():
    """Large bearish → small body (star) → large bullish = morning star."""
    large_bear = _candle(110, 111, 99, 100)
    small_star = _candle(99, 102, 97, 100)   # small body
    large_bull = _candle(100, 115, 99, 113)
    df = _df(*[_candle(112, 115, 110, 111)] * 7, large_bear, small_star, large_bull)
    assert score_patterns(df) > 65.0


# ── Bearish patterns → score > 50 (strong signal, direction-neutral) ─────────

def test_bearish_marubozu_scores_above_70():
    """Full bearish body = strong signal magnitude, scores high."""
    marubozu = _candle(115, 115, 100, 100)  # open=high, close=low
    df = _df(*[_candle(112, 116, 109, 113)] * 9, marubozu)
    assert score_patterns(df) > 70.0


def test_shooting_star_scores_above_60():
    """Shooting star = strong bearish signal, scores high."""
    star = _candle(110, 120, 109.5, 108)
    df = _df(*[_candle(106, 109, 104, 108)] * 9, star)
    assert score_patterns(df) > 60.0


def test_bearish_engulfing_scores_above_65():
    """Bearish engulfing = strong signal magnitude, scores high."""
    prev_bullish = _candle(100, 107, 99, 106)
    curr_bearish = _candle(107, 108, 97, 98)
    df = _df(*[_candle(100, 104, 98, 102)] * 8, prev_bullish, curr_bearish)
    assert score_patterns(df) > 65.0


def test_evening_star_scores_above_65():
    """Evening star = strong bearish signal, scores high."""
    large_bull = _candle(100, 115, 99, 114)
    small_star = _candle(114, 117, 113, 115)
    large_bear = _candle(115, 116, 101, 102)
    df = _df(*[_candle(99, 102, 97, 101)] * 7, large_bull, small_star, large_bear)
    assert score_patterns(df) > 65.0
