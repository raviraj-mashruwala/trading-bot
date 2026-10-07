"""Tests for volume profile scorer used in Tier 1 screening."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingbot.screening.volume_profile_score import score_volume_profile, score_from_levels


def _df_at_price(close: float, n: int = 30, volume: int = 1_000_000) -> pd.DataFrame:
    """All candles at same price → VAH=VAL=POC=close (flat profile)."""
    return pd.DataFrame({
        "open": [close - 1] * n,
        "high": [close + 2] * n,
        "low": [close - 2] * n,
        "close": [close] * n,
        "volume": [volume] * n,
    })


def _df_with_profile(
    poc: float, vah: float, val: float, close: float, n: int = 30
) -> pd.DataFrame:
    """Build a df whose volume profile concentrates volume at POC level."""
    rng = np.random.default_rng(42)
    # Most volume at POC, spread closes from val to vah
    closes = np.linspace(val, vah, n)
    closes[-1] = close  # last candle is the current price
    vols = np.full(n, 100_000)
    # Concentrate volume at the bin closest to poc
    poc_idx = int((poc - val) / (vah - val) * (n - 1)) if vah > val else 0
    vols[poc_idx] = 5_000_000  # big volume at POC
    return pd.DataFrame({
        "open": closes - 1, "high": closes + 2,
        "low": closes - 2, "close": closes,
        "volume": vols,
    })


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_empty_df_returns_50():
    assert score_volume_profile(pd.DataFrame()) == pytest.approx(50.0)


def test_insufficient_candles_returns_50():
    assert score_volume_profile(_df_at_price(100, n=2)) == pytest.approx(50.0)


def test_score_in_range():
    score = score_volume_profile(_df_at_price(500))
    assert 0.0 <= score <= 100.0


# ── Price above VAH → bullish breakout ───────────────────────────────────────

def test_close_above_vah_scores_above_70():
    """Price breaking above value area high = bullish breakout signal."""
    df = _df_with_profile(poc=100, vah=110, val=90, close=115)
    assert score_volume_profile(df) > 70.0


# ── Price below VAL → breakdown (high score, direction-neutral) ──────────────

def test_close_below_val_scores_above_70():
    """Price breaking below VAL = strong signal (short candidate), scores high."""
    df = _df_with_profile(poc=100, vah=110, val=90, close=85)
    assert score_volume_profile(df) > 70.0


# ── score_from_levels: exact level tests (no df construction ambiguity) ──────

def test_close_at_poc_scores_exactly_50():
    assert score_from_levels(close=100, poc=100, vah=110, val=90) == pytest.approx(50.0)


def test_close_above_poc_within_va_scores_above_50():
    score = score_from_levels(close=106, poc=100, vah=110, val=90)
    assert score > 50.0


def test_close_below_poc_within_va_scores_above_50():
    """Distance from POC determines interest, regardless of direction."""
    score = score_from_levels(close=94, poc=100, vah=110, val=90)
    assert score > 50.0


def test_close_at_vah_scores_60():
    score = score_from_levels(close=110, poc=100, vah=110, val=90)
    assert score >= 60.0


def test_close_at_val_scores_60():
    """VAL = extreme of value area, high interest for shorts."""
    score = score_from_levels(close=90, poc=100, vah=110, val=90)
    assert score >= 60.0


def test_degenerate_profile_returns_50():
    assert score_from_levels(close=100, poc=100, vah=100, val=100) == pytest.approx(50.0)
