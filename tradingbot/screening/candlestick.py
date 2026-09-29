"""Candlestick pattern scorer for Tier 1 screening.

Detects 8 common single-, two-, and three-candle patterns from daily OHLCV data.
Returns a score in [0, 100]: >50 bullish, <50 bearish, 50 neutral.

Patterns detected:
  Bullish (+):  Bullish Marubozu, Hammer, Bullish Engulfing, Morning Star
  Bearish (-):  Bearish Marubozu, Shooting Star, Bearish Engulfing, Evening Star
"""

from __future__ import annotations

import pandas as pd


# Minimum number of candles required to attempt pattern detection
_MIN_CANDLES = 3

# Body-to-range ratio thresholds
_MARUBOZU_BODY_RATIO = 0.85   # body ≥ 85% of high-low range
_DOJI_BODY_RATIO = 0.05        # body ≤ 5% of high-low range
_HAMMER_WICK_RATIO = 2.0       # lower/upper wick ≥ 2× body
_STAR_BODY_RATIO = 0.3         # star body ≤ 30% of prior large candle body

# Pattern scores (signed, centered on 0)
_SCORE: dict[str, float] = {
    "bullish_marubozu":  25.0,
    "morning_star":      20.0,
    "bullish_engulfing": 20.0,
    "hammer":            15.0,
    "bearish_marubozu": -25.0,
    "evening_star":     -20.0,
    "bearish_engulfing": -20.0,
    "shooting_star":     -15.0,
}


def score_patterns(df: pd.DataFrame) -> float:
    """Return 0-100 candlestick pattern score for the tail of df.

    Uses the last 3 candles. Returns 50.0 (neutral) on insufficient data.
    Multiple patterns stack; result clamped to [0, 100].
    """
    if df.empty or len(df) < _MIN_CANDLES:
        return 50.0

    tail = df.tail(3).reset_index(drop=True)
    c0, c1, c2 = tail.iloc[0], tail.iloc[1], tail.iloc[2]

    signed = 0.0

    # Single-candle patterns on last candle (c2)
    if _is_bullish_marubozu(c2):
        signed += _SCORE["bullish_marubozu"]
    elif _is_bearish_marubozu(c2):
        signed += _SCORE["bearish_marubozu"]
    elif _is_hammer(c2):
        signed += _SCORE["hammer"]
    elif _is_shooting_star(c2):
        signed += _SCORE["shooting_star"]

    # Two-candle patterns on (c1, c2)
    if _is_bullish_engulfing(c1, c2):
        signed += _SCORE["bullish_engulfing"]
    elif _is_bearish_engulfing(c1, c2):
        signed += _SCORE["bearish_engulfing"]

    # Three-candle patterns on (c0, c1, c2)
    if _is_morning_star(c0, c1, c2):
        signed += _SCORE["morning_star"]
    elif _is_evening_star(c0, c1, c2):
        signed += _SCORE["evening_star"]

    return float(max(0.0, min(100.0, 50.0 + signed)))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _body(c) -> float:
    return abs(float(c["close"]) - float(c["open"]))


def _range(c) -> float:
    return float(c["high"]) - float(c["low"])


def _upper_wick(c) -> float:
    return float(c["high"]) - max(float(c["open"]), float(c["close"]))


def _lower_wick(c) -> float:
    return min(float(c["open"]), float(c["close"])) - float(c["low"])


def _is_bull(c) -> bool:
    return float(c["close"]) > float(c["open"])


def _is_bear(c) -> bool:
    return float(c["close"]) < float(c["open"])


# ── Single-candle ─────────────────────────────────────────────────────────────

def _is_bullish_marubozu(c) -> bool:
    r = _range(c)
    return r > 0 and _is_bull(c) and _body(c) / r >= _MARUBOZU_BODY_RATIO


def _is_bearish_marubozu(c) -> bool:
    r = _range(c)
    return r > 0 and _is_bear(c) and _body(c) / r >= _MARUBOZU_BODY_RATIO


def _is_hammer(c) -> bool:
    """Small body at top, long lower wick ≥ 2× body, tiny upper wick."""
    b = _body(c)
    lw = _lower_wick(c)
    uw = _upper_wick(c)
    if b <= 0:
        return False
    return lw >= _HAMMER_WICK_RATIO * b and uw <= 0.5 * b


def _is_shooting_star(c) -> bool:
    """Small body at bottom, long upper wick ≥ 2× body, tiny lower wick."""
    b = _body(c)
    lw = _lower_wick(c)
    uw = _upper_wick(c)
    if b <= 0:
        return False
    return uw >= _HAMMER_WICK_RATIO * b and lw <= 0.5 * b


# ── Two-candle ────────────────────────────────────────────────────────────────

def _is_bullish_engulfing(prev, curr) -> bool:
    """prev bearish; curr bullish body fully engulfs prev body."""
    return (
        _is_bear(prev)
        and _is_bull(curr)
        and float(curr["open"]) <= float(prev["close"])
        and float(curr["close"]) >= float(prev["open"])
    )


def _is_bearish_engulfing(prev, curr) -> bool:
    """prev bullish; curr bearish body fully engulfs prev body."""
    return (
        _is_bull(prev)
        and _is_bear(curr)
        and float(curr["open"]) >= float(prev["close"])
        and float(curr["close"]) <= float(prev["open"])
    )


# ── Three-candle ──────────────────────────────────────────────────────────────

def _is_morning_star(c0, c1, c2) -> bool:
    """c0 large bearish, c1 small body (star), c2 large bullish closing into c0 body."""
    b0, b1, b2 = _body(c0), _body(c1), _body(c2)
    if b0 <= 0:
        return False
    return (
        _is_bear(c0)
        and b1 <= _STAR_BODY_RATIO * b0    # star has small body
        and _is_bull(c2)
        and b2 >= 0.5 * b0                 # recovery is substantial
        and float(c2["close"]) > (float(c0["open"]) + float(c0["close"])) / 2
    )


def _is_evening_star(c0, c1, c2) -> bool:
    """c0 large bullish, c1 small body (star), c2 large bearish closing into c0 body."""
    b0, b1, b2 = _body(c0), _body(c1), _body(c2)
    if b0 <= 0:
        return False
    return (
        _is_bull(c0)
        and b1 <= _STAR_BODY_RATIO * b0
        and _is_bear(c2)
        and b2 >= 0.5 * b0
        and float(c2["close"]) < (float(c0["open"]) + float(c0["close"])) / 2
    )
