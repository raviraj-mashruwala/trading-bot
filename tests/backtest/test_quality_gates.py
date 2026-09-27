"""Tests for quality gates."""

import pytest
from datetime import date

from tradingbot.backtest.quality_gates import QualityGates
from tradingbot.core.models import BacktestReport, MonteCarloResult, StrategyName


def _report(**overrides):
    defaults = dict(
        symbol="TEST",
        strategy=StrategyName.BREAKOUT,
        period_start=date(2025, 1, 1),
        period_end=date(2026, 1, 1),
        total_trades=50,
        winners=30,
        losers=20,
        win_rate=0.60,
        avg_winner=5000,
        avg_loser=-3000,
        profit_factor=2.5,
        expectancy=1200,
        expectancy_r=0.5,
        sharpe_ratio=1.8,
        max_drawdown_pct=5.0,
        max_consecutive_losses=4,
        avg_hold_minutes=45,
        oos_degradation=0.1,
        calmar_ratio=2.0,
    )
    defaults.update(overrides)
    return BacktestReport(**defaults)


def _mc(**overrides):
    defaults = dict(
        simulations=10000,
        median_return_pct=15.0,
        p10_return_pct=5.0,
        p90_return_pct=30.0,
        median_max_drawdown=6.0,
        p95_max_drawdown=12.0,
        risk_of_ruin_pct=1.0,
        confidence_score=0.75,
    )
    defaults.update(overrides)
    return MonteCarloResult(**defaults)


def test_all_gates_pass():
    gates = QualityGates()
    result = gates.evaluate(_report(), _mc())
    assert result.passed is True
    assert len(result.failures) == 0


def test_insufficient_trades_fails():
    gates = QualityGates()
    result = gates.evaluate(_report(total_trades=10), _mc())
    assert result.passed is False
    assert result.total_trades_ok is False


def test_low_win_rate_fails():
    gates = QualityGates()
    result = gates.evaluate(_report(win_rate=0.30), _mc())
    assert result.passed is False
    assert result.win_rate_ok is False


def test_low_profit_factor_fails():
    gates = QualityGates()
    result = gates.evaluate(_report(profit_factor=1.0), _mc())
    assert result.passed is False
    assert result.profit_factor_ok is False


def test_low_expectancy_r_fails():
    gates = QualityGates()
    result = gates.evaluate(_report(expectancy_r=0.1), _mc())
    assert result.passed is False
    assert result.expectancy_ok is False


def test_high_oos_degradation_fails():
    gates = QualityGates()
    result = gates.evaluate(_report(oos_degradation=0.5), _mc())
    assert result.passed is False
    assert result.oos_ok is False


def test_negative_mc_p10_fails():
    gates = QualityGates()
    result = gates.evaluate(_report(), _mc(p10_return_pct=-2.0))
    assert result.passed is False
    assert result.monte_carlo_p10_ok is False


def test_high_ruin_risk_fails():
    gates = QualityGates()
    result = gates.evaluate(_report(), _mc(risk_of_ruin_pct=10.0))
    assert result.passed is False
    assert result.ruin_risk_ok is False


def test_high_consecutive_losses_fails():
    gates = QualityGates()
    result = gates.evaluate(_report(max_consecutive_losses=12), _mc())
    assert result.passed is False
    assert result.consecutive_losses_ok is False


def test_multiple_failures_reported():
    gates = QualityGates()
    result = gates.evaluate(
        _report(total_trades=10, win_rate=0.2, profit_factor=0.8),
        _mc(risk_of_ruin_pct=20.0),
    )
    assert result.passed is False
    assert len(result.failures) >= 4


def test_custom_thresholds():
    gates = QualityGates(min_trades=100, min_win_rate=0.6)
    result = gates.evaluate(_report(total_trades=50, win_rate=0.55), _mc())
    assert result.passed is False
    assert result.total_trades_ok is False
    assert result.win_rate_ok is False
