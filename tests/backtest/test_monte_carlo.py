"""Tests for Monte Carlo simulation."""

import pytest

from tradingbot.backtest.monte_carlo import MonteCarloSimulator


def test_monte_carlo_returns_result():
    trades = [
        100, -50, 200, -80, 150, -30, 120, -60, 90, -40,
        110, -45, 180, -70, 130, -55, 95, -35, 140, -65,
        160, -75, 125, -50, 115, -40, 175, -60, 135, -45,
    ]
    sim = MonteCarloSimulator(simulations=1000, capital=400000)
    result = sim.run(trades)
    assert result.simulations == 1000
    assert result.median_return_pct != 0
    assert result.p10_return_pct <= result.median_return_pct <= result.p90_return_pct
    assert 0 <= result.risk_of_ruin_pct <= 100
    assert 0 <= result.confidence_score <= 1


def test_monte_carlo_empty_trades():
    sim = MonteCarloSimulator(simulations=100, capital=400000)
    result = sim.run([])
    assert result.confidence_score == 0


def test_monte_carlo_fewer_than_5_trades():
    sim = MonteCarloSimulator(simulations=100, capital=400000)
    result = sim.run([100, -50, 200])
    assert result.confidence_score == 0


def test_monte_carlo_all_winners():
    trades = [100, 200, 150, 120, 180, 90, 110, 130, 160, 140]
    sim = MonteCarloSimulator(simulations=500, capital=400000)
    result = sim.run(trades)
    assert result.median_return_pct > 0
    assert result.risk_of_ruin_pct == 0  # all positive, no ruin possible


def test_monte_carlo_all_losers():
    trades = [-100, -200, -150, -120, -180, -90, -110, -130, -160, -140]
    sim = MonteCarloSimulator(simulations=500, capital=400000)
    result = sim.run(trades)
    assert result.median_return_pct < 0


def test_monte_carlo_percentile_ordering():
    trades = [50, -20, 80, -30, 60, -10, 70, -25, 40, -15]
    sim = MonteCarloSimulator(simulations=2000, capital=400000)
    result = sim.run(trades)
    assert result.p10_return_pct <= result.median_return_pct
    assert result.median_return_pct <= result.p90_return_pct
    assert result.median_max_drawdown <= result.p95_max_drawdown
