"""Tests for regime-conditional backtesting metrics."""

import numpy as np
import pandas as pd
import pytest

from tradingbot.backtest.walk_forward import WalkForwardEngine
from tradingbot.core.models import BacktestReport


@pytest.fixture
def trending_df():
    np.random.seed(42)
    n = 500
    close = 500 + np.cumsum(np.random.randn(n) * 3)
    return pd.DataFrame({
        "open": close - 1,
        "high": close + abs(np.random.randn(n) * 5),
        "low": close - abs(np.random.randn(n) * 5),
        "close": close,
        "volume": np.random.randint(500000, 2000000, n),
    })


def test_backtest_report_has_regime_performance(trending_df):
    from tradingbot.strategy.strategies.momentum import MomentumStrategy
    engine = WalkForwardEngine(windows=2, train_pct=70)
    report = engine.run("TEST", trending_df, MomentumStrategy())
    assert hasattr(report, "regime_performance")
    assert isinstance(report.regime_performance, dict)


def test_regime_performance_keys_are_valid(trending_df):
    from tradingbot.strategy.strategies.breakout import BreakoutStrategy
    engine = WalkForwardEngine(windows=2, train_pct=70)
    report = engine.run("TEST", trending_df, BreakoutStrategy())
    valid_regimes = {"trending_up", "trending_down", "range_bound", "volatile", "low_vol_squeeze", "unknown"}
    for regime_key in report.regime_performance:
        assert regime_key in valid_regimes


def test_regime_performance_stats_structure(trending_df):
    from tradingbot.strategy.strategies.momentum import MomentumStrategy
    engine = WalkForwardEngine(windows=2, train_pct=70)
    report = engine.run("TEST", trending_df, MomentumStrategy())
    for regime, stats in report.regime_performance.items():
        assert "trades" in stats
        assert "win_rate" in stats
        assert "profit_factor" in stats
        assert isinstance(stats["trades"], int)
        assert 0 <= stats["win_rate"] <= 1


def test_regime_performance_trade_counts_sum(trending_df):
    """Sum of per-regime trade counts should equal total_trades."""
    from tradingbot.strategy.strategies.momentum import MomentumStrategy
    engine = WalkForwardEngine(windows=2, train_pct=70)
    report = engine.run("TEST", trending_df, MomentumStrategy())
    if report.total_trades > 0:
        regime_total = sum(s["trades"] for s in report.regime_performance.values())
        assert regime_total == report.total_trades


def test_empty_report_has_empty_regime_performance():
    """Empty reports should have empty regime_performance dict."""
    np.random.seed(99)
    tiny_df = pd.DataFrame({
        "open": [100.0], "high": [101.0], "low": [99.0],
        "close": [100.5], "volume": [1000000],
    })
    from tradingbot.strategy.strategies.momentum import MomentumStrategy
    engine = WalkForwardEngine(windows=2, train_pct=70)
    report = engine.run("TINY", tiny_df, MomentumStrategy())
    assert report.regime_performance == {}
