"""Tests for IntelligentScreener — rescue pool, adaptive weights, smart caps."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tradingbot.core.config import ScreeningConfig


def _config() -> ScreeningConfig:
    return ScreeningConfig(
        min_volume=100_000, min_price=50.0, max_price=5000.0,
        min_market_cap_cr=500.0, min_atr_pct=0.5, min_trading_days=10,
        max_per_sector=3,
        volume_surge_weight=15, relative_strength_weight=15,
        atr_expansion_weight=10, price_structure_weight=15,
        delivery_pct_weight=10, sector_momentum_weight=10,
        gap_analysis_weight=10, candlestick_pattern_weight=10,
        volume_profile_weight=5,
    )


def _stock(symbol="RELIANCE", avg_volume=200_000, last_price=2500.0,
           market_cap_cr=1000.0, sector="energy", **overrides):
    defaults = {
        "symbol": symbol, "avg_volume": avg_volume, "last_price": last_price,
        "market_cap_cr": market_cap_cr, "sector": sector,
        "atr_pct": 1.5, "trading_days": 20, "token": 0,
        "factor_scores": {
            "volume_surge": 70.0, "relative_strength": 60.0,
            "atr_expansion": 55.0, "price_structure": 65.0,
            "delivery_pct": 50.0, "sector_momentum": 50.0,
            "gap_analysis": 50.0, "candlestick_pattern": 50.0,
            "volume_profile": 50.0,
        },
    }
    defaults.update(overrides)
    return defaults


def _near_miss_stock(symbol="INFY", avg_volume=85_000, **overrides):
    """Stock that barely misses volume threshold (85K vs 100K min)."""
    return _stock(symbol=symbol, avg_volume=avg_volume, sector="it", **overrides)


def _mock_jev_rescue(unusual=0.8, tradeable=0.7, quality=1.5):
    """Mock JevClient that returns rescue answers."""
    client = MagicMock()
    client.available = True
    client.evaluate = MagicMock(return_value={
        "unusual_activity": SimpleNamespace(noul=unusual),
        "tradeable_despite_threshold": SimpleNamespace(noul=tradeable),
        "opportunity_quality": SimpleNamespace(score=quality, confidence=0.8),
    })
    return client


# --- No Jev: falls back to deterministic ---

def test_no_jev_behaves_like_deterministic():
    from tradingbot.screening.intelligent_screener import IntelligentScreener
    screener = IntelligentScreener(_config(), jev_client=None)
    stocks = [_stock(f"STOCK{i}", sector=f"s{i % 3}") for i in range(10)]
    result = screener.screen(stocks)
    assert len(result) > 0
    assert all(hasattr(s, "composite_score") for s in result)


# --- Rescue pool ---

def test_rescue_pool_saves_near_miss():
    from tradingbot.screening.intelligent_screener import IntelligentScreener
    jev = _mock_jev_rescue(unusual=0.85, tradeable=0.75, quality=1.8)
    screener = IntelligentScreener(_config(), jev_client=jev)

    good_stock = _stock("RELIANCE", avg_volume=200_000, sector="energy")
    near_miss = _near_miss_stock("INFY", avg_volume=85_000)

    result = screener.screen([good_stock, near_miss])
    symbols = [s.symbol for s in result]
    assert "RELIANCE" in symbols
    assert "INFY" in symbols  # rescued!


def test_rescue_pool_rejects_far_miss():
    from tradingbot.screening.intelligent_screener import IntelligentScreener
    jev = _mock_jev_rescue()
    screener = IntelligentScreener(_config(), jev_client=jev)

    good_stock = _stock("RELIANCE")
    far_miss = _stock("JUNK", avg_volume=10_000)  # 10% of threshold, below 60%

    result = screener.screen([good_stock, far_miss])
    symbols = [s.symbol for s in result]
    assert "RELIANCE" in symbols
    assert "JUNK" not in symbols  # too far from threshold


def test_rescue_pool_skipped_when_no_jev():
    from tradingbot.screening.intelligent_screener import IntelligentScreener
    screener = IntelligentScreener(_config(), jev_client=None)

    good_stock = _stock("RELIANCE")
    near_miss = _near_miss_stock("INFY", avg_volume=85_000)

    result = screener.screen([good_stock, near_miss])
    symbols = [s.symbol for s in result]
    assert "RELIANCE" in symbols
    assert "INFY" not in symbols  # no Jev, no rescue


# --- Adaptive weights ---

def test_trending_up_boosts_momentum_factors():
    from tradingbot.screening.intelligent_screener import IntelligentScreener
    screener = IntelligentScreener(_config(), jev_client=None)
    adapted = screener._adapt_weights("trending_up", regime_confidence=0.85)
    # relative_strength should be boosted (multiplier 1.5)
    base_rs = _config().relative_strength_weight
    assert adapted["relative_strength"] > base_rs


def test_low_confidence_barely_shifts_weights():
    from tradingbot.screening.intelligent_screener import IntelligentScreener
    screener = IntelligentScreener(_config(), jev_client=None)
    adapted = screener._adapt_weights("trending_up", regime_confidence=0.1)
    base_rs = _config().relative_strength_weight
    # With 0.1 confidence, shift should be minimal
    assert abs(adapted["relative_strength"] - base_rs) <= 1


# --- Smart sector caps ---

def test_smart_caps_give_strong_sector_more_slots():
    from tradingbot.screening.intelligent_screener import IntelligentScreener
    from tradingbot.core.models import ScoredStock
    screener = IntelligentScreener(_config(), jev_client=None)

    stocks = []
    for i in range(6):
        stocks.append(ScoredStock(
            symbol=f"BANK{i}", exchange="NSE", last_price=2000.0,
            avg_volume=200_000, market_cap_cr=1000.0, atr_pct=1.5,
            sector="banking", composite_score=80.0 - i,
            factor_scores={}, instrument_token=0,
        ))

    sector_scores = {"banking": 0.85}  # strong sector
    result = screener._smart_sector_filter(stocks, sector_scores)
    # base cap=3, strong=+2 → 5 allowed
    assert len(result) == 5


def test_signals_survive_the_intelligent_screener():
    from tradingbot.screening.intelligent_screener import IntelligentScreener

    stock = _stock(signals={"change_1d_pct": -4.2, "rsi_14": 27.0})

    scored = IntelligentScreener(_config(), jev_client=None).screen([stock], regime="range_bound")

    assert scored and scored[0].signals == {"change_1d_pct": -4.2, "rsi_14": 27.0}
