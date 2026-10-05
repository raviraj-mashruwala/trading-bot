"""Tests for Tier 1 screening engine components."""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock
from tradingbot.screening.liquidity_filter import LiquidityFilter
from tradingbot.screening.factor_scorer import FactorScorer
from tradingbot.screening.correlation_filter import CorrelationFilter

IST = ZoneInfo("Asia/Kolkata")


def _make_candle_df(n=30, base_price=500, avg_vol=600000):
    dates = pd.date_range("2026-08-01", periods=n, freq="B", tz=IST)
    close = base_price + np.cumsum(np.random.randn(n) * 2)
    return pd.DataFrame({
        "open": close + np.random.randn(n),
        "high": close + abs(np.random.randn(n) * 3),
        "low": close - abs(np.random.randn(n) * 3),
        "close": close,
        "volume": np.random.randint(int(avg_vol * 0.8), int(avg_vol * 1.2), n),
    }, index=dates)


def test_liquidity_filter_passes_valid():
    filt = LiquidityFilter(
        min_volume=500000, min_price=50, max_price=5000,
        min_market_cap_cr=1000, min_trading_days=10,
    )
    stock = {"symbol": "RELIANCE", "token": 1, "last_price": 2500.0,
             "avg_volume": 5_000_000.0, "market_cap_cr": 1_700_000.0,
             "trading_days": 20, "atr_pct": 1.5, "sector": "energy"}
    assert filt.passes(stock) is True


def test_liquidity_filter_rejects_low_volume():
    filt = LiquidityFilter(
        min_volume=500000, min_price=50, max_price=5000,
        min_market_cap_cr=1000, min_trading_days=10,
    )
    stock = {"symbol": "SMALLCO", "token": 2, "last_price": 200.0,
             "avg_volume": 50_000.0, "market_cap_cr": 500.0,
             "trading_days": 20, "atr_pct": 1.0, "sector": "misc"}
    assert filt.passes(stock) is False


def test_liquidity_filter_rejects_price_too_low():
    filt = LiquidityFilter(
        min_volume=500000, min_price=50, max_price=5000,
        min_market_cap_cr=1000, min_trading_days=10,
    )
    stock = {"symbol": "PENNY", "token": 3, "last_price": 10.0,
             "avg_volume": 1_000_000.0, "market_cap_cr": 2000.0,
             "trading_days": 20, "atr_pct": 2.0, "sector": "misc"}
    assert filt.passes(stock) is False


def test_liquidity_filter_rejects_price_too_high():
    filt = LiquidityFilter(
        min_volume=500000, min_price=50, max_price=5000,
        min_market_cap_cr=1000, min_trading_days=10,
    )
    stock = {"symbol": "EXPENSIVE", "token": 4, "last_price": 10000.0,
             "avg_volume": 1_000_000.0, "market_cap_cr": 5000.0,
             "trading_days": 20, "atr_pct": 1.0, "sector": "tech"}
    assert filt.passes(stock) is False


def test_liquidity_filter_ignores_market_cap():
    filt = LiquidityFilter(
        min_volume=500000, min_price=50, max_price=5000,
        min_market_cap_cr=1000, min_trading_days=10,
    )
    stock = {"symbol": "SMALLCAP", "token": 5, "last_price": 100.0,
             "avg_volume": 1_000_000.0, "market_cap_cr": 500.0,
             "trading_days": 20, "atr_pct": 1.5, "sector": "misc"}
    assert filt.passes(stock) is True


def test_liquidity_filter_rejects_few_trading_days():
    filt = LiquidityFilter(
        min_volume=500000, min_price=50, max_price=5000,
        min_market_cap_cr=1000, min_trading_days=10,
    )
    stock = {"symbol": "NEWCO", "token": 6, "last_price": 200.0,
             "avg_volume": 1_000_000.0, "market_cap_cr": 2000.0,
             "trading_days": 5, "atr_pct": 1.5, "sector": "misc"}
    assert filt.passes(stock) is False


def test_liquidity_filter_all():
    filt = LiquidityFilter(
        min_volume=500000, min_price=50, max_price=5000,
        min_market_cap_cr=1000, min_trading_days=10,
    )
    stocks = [
        {"symbol": "GOOD", "token": 1, "last_price": 500.0,
         "avg_volume": 1_000_000.0, "market_cap_cr": 5000.0,
         "trading_days": 20, "atr_pct": 1.5, "sector": "tech"},
        {"symbol": "BAD", "token": 2, "last_price": 5.0,
         "avg_volume": 100.0, "market_cap_cr": 10.0,
         "trading_days": 2, "atr_pct": 0.1, "sector": "misc"},
    ]
    result = filt.filter_all(stocks)
    assert len(result) == 1
    assert result[0]["symbol"] == "GOOD"


def test_factor_scorer_returns_sorted_scores():
    scorer = FactorScorer(weights={
        "volume_surge": 15, "relative_strength": 15, "atr_expansion": 10,
        "price_structure": 15, "delivery_pct": 10, "sector_momentum": 10,
        "gap_analysis": 10, "candlestick_pattern": 10, "volume_profile": 5,
    })
    stocks = [
        {"symbol": "A", "scores": {"volume_surge": 90, "relative_strength": 80}},
        {"symbol": "B", "scores": {"volume_surge": 40, "relative_strength": 30}},
    ]
    # Scorer should weight and rank
    result = scorer.compute_composite(stocks[0]["scores"])
    assert isinstance(result, float)
    assert 0 <= result <= 100


def test_factor_scorer_all_max_scores():
    scorer = FactorScorer(weights={
        "volume_surge": 15, "relative_strength": 15, "atr_expansion": 10,
        "price_structure": 15, "delivery_pct": 10, "sector_momentum": 10,
        "gap_analysis": 10, "candlestick_pattern": 10, "volume_profile": 5,
    })
    all_100 = {k: 100.0 for k in FactorScorer.FACTOR_KEYS}
    assert scorer.compute_composite(all_100) == 100.0


def test_factor_scorer_all_zero_scores():
    scorer = FactorScorer(weights={
        "volume_surge": 15, "relative_strength": 15, "atr_expansion": 10,
        "price_structure": 15, "delivery_pct": 10, "sector_momentum": 10,
        "gap_analysis": 10, "candlestick_pattern": 10, "volume_profile": 5,
    })
    all_zero = {k: 0.0 for k in FactorScorer.FACTOR_KEYS}
    assert scorer.compute_composite(all_zero) == 0.0


def test_factor_scorer_missing_keys_default_50():
    scorer = FactorScorer(weights={
        "volume_surge": 15, "relative_strength": 15, "atr_expansion": 10,
        "price_structure": 15, "delivery_pct": 10, "sector_momentum": 10,
        "gap_analysis": 10, "candlestick_pattern": 10, "volume_profile": 5,
    })
    # Missing keys should default to 50
    result = scorer.compute_composite({})
    assert result == 50.0


def test_correlation_filter_caps_per_sector():
    filt = CorrelationFilter(max_per_sector=2)
    from tradingbot.core.models import ScoredStock
    stocks = [
        ScoredStock("HDFCBANK", "NSE", 1600, 8e6, 12e5, 1.0, "banking", 90, {}, 1),
        ScoredStock("ICICIBANK", "NSE", 1000, 7e6, 7e5, 1.1, "banking", 85, {}, 2),
        ScoredStock("SBIN", "NSE", 600, 1e7, 5e5, 1.2, "banking", 80, {}, 3),
        ScoredStock("RELIANCE", "NSE", 2500, 5e6, 17e5, 1.5, "energy", 88, {}, 4),
    ]
    result = filt.filter(stocks)
    banking = [s for s in result if s.sector == "banking"]
    assert len(banking) <= 2
    assert len(result) == 3  # 2 banking + 1 energy


def test_correlation_filter_preserves_sort_order():
    filt = CorrelationFilter(max_per_sector=1)
    from tradingbot.core.models import ScoredStock
    stocks = [
        ScoredStock("LOW", "NSE", 100, 1e6, 1e5, 1.0, "tech", 60, {}, 1),
        ScoredStock("HIGH", "NSE", 200, 2e6, 2e5, 1.0, "tech", 90, {}, 2),
    ]
    result = filt.filter(stocks)
    assert len(result) == 1
    assert result[0].symbol == "HIGH"  # Highest score kept


def test_tier1_screener_end_to_end():
    from tradingbot.screening.screener import Tier1Screener
    from tradingbot.core.config import ScreeningConfig
    config = ScreeningConfig(
        min_volume=100000, min_price=50, max_price=5000,
        min_market_cap_cr=500, min_atr_pct=0.5, min_trading_days=5,
        max_per_sector=2,
        volume_surge_weight=15, relative_strength_weight=15,
        atr_expansion_weight=10, price_structure_weight=15,
        delivery_pct_weight=10, sector_momentum_weight=10,
        gap_analysis_weight=10, candlestick_pattern_weight=10,
        volume_profile_weight=5,
    )
    candle_store = MagicMock()
    screener = Tier1Screener(config, candle_store)
    stocks = [
        {"symbol": "A", "token": 1, "last_price": 500.0, "avg_volume": 1e6,
         "market_cap_cr": 5000.0, "trading_days": 20, "atr_pct": 1.5,
         "sector": "tech", "factor_scores": {"volume_surge": 80}},
        {"symbol": "B", "token": 2, "last_price": 300.0, "avg_volume": 500000.0,
         "market_cap_cr": 2000.0, "trading_days": 15, "atr_pct": 1.0,
         "sector": "tech", "factor_scores": {"volume_surge": 40}},
        {"symbol": "C", "token": 3, "last_price": 10.0, "avg_volume": 100.0,
         "market_cap_cr": 10.0, "trading_days": 2, "atr_pct": 0.1,
         "sector": "misc", "factor_scores": {}},
    ]
    result = screener.screen(stocks)
    # C filtered by liquidity, A and B pass, both tech capped at 2
    assert len(result) == 2
    symbols = {s.symbol for s in result}
    assert "C" not in symbols
