"""Tests for walk-forward backtesting engine."""

import numpy as np
import pandas as pd
import pytest

from tradingbot.backtest.walk_forward import WalkForwardEngine
from tradingbot.core.models import BacktestReport, StrategyName


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


@pytest.fixture
def short_df():
    """Too short for meaningful backtest (< WARMUP + 50)."""
    np.random.seed(42)
    n = 100
    close = 500 + np.cumsum(np.random.randn(n) * 3)
    return pd.DataFrame({
        "open": close - 1,
        "high": close + abs(np.random.randn(n) * 5),
        "low": close - abs(np.random.randn(n) * 5),
        "close": close,
        "volume": np.random.randint(500000, 2000000, n),
    })


def test_walk_forward_returns_backtest_report(trending_df):
    from tradingbot.strategy.strategies.momentum import MomentumStrategy
    engine = WalkForwardEngine(windows=3, train_pct=70)
    report = engine.run("RELIANCE", trending_df, MomentumStrategy())
    assert isinstance(report, BacktestReport)
    assert report.symbol == "RELIANCE"
    assert report.total_trades >= 0


def test_walk_forward_computes_oos_degradation(trending_df):
    from tradingbot.strategy.strategies.breakout import BreakoutStrategy
    engine = WalkForwardEngine(windows=3, train_pct=70)
    report = engine.run("TCS", trending_df, BreakoutStrategy())
    assert hasattr(report, "oos_degradation")
    assert report.oos_degradation >= 0


def test_walk_forward_includes_transaction_costs(trending_df):
    from tradingbot.strategy.strategies.momentum import MomentumStrategy
    engine_with_costs = WalkForwardEngine(windows=2, train_pct=70, include_costs=True)
    engine_no_costs = WalkForwardEngine(windows=2, train_pct=70, include_costs=False)
    r1 = engine_with_costs.run("TEST", trending_df, MomentumStrategy())
    r2 = engine_no_costs.run("TEST", trending_df, MomentumStrategy())
    # With costs, expectancy should be lower or equal
    if r1.total_trades > 0 and r2.total_trades > 0:
        assert r1.expectancy <= r2.expectancy + 1  # small tolerance


def test_walk_forward_short_data_returns_empty(short_df):
    from tradingbot.strategy.strategies.momentum import MomentumStrategy
    engine = WalkForwardEngine(windows=3, train_pct=70)
    report = engine.run("SHORT", short_df, MomentumStrategy())
    assert isinstance(report, BacktestReport)
    assert report.total_trades == 0


def test_walk_forward_report_has_all_fields(trending_df):
    from tradingbot.strategy.strategies.momentum import MomentumStrategy
    engine = WalkForwardEngine(windows=2, train_pct=70)
    report = engine.run("INFY", trending_df, MomentumStrategy())
    assert hasattr(report, "sharpe_ratio")
    assert hasattr(report, "max_drawdown_pct")
    assert hasattr(report, "calmar_ratio")
    assert hasattr(report, "max_consecutive_losses")
    assert hasattr(report, "profit_factor")
