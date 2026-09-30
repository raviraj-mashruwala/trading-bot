"""Tests for TradeScorecard and PerformanceStats models."""

from __future__ import annotations

import pytest

from tradingbot.core.models import (
    PerformanceStats,
    StrategyStats,
    TradeScorecard,
)


def _make_scorecard(**overrides) -> TradeScorecard:
    defaults = dict(
        trade_id=1, setup_id=42, symbol="TCS", strategy="breakout",
        direction="long", trade_date="2026-09-30",
        predicted_entry=3500.0, predicted_stop=3450.0,
        predicted_target_1=3600.0, predicted_target_2=3680.0,
        confidence=0.78, confluence_count=4,
        regime_at_generation="trending_up",
        thesis="Breakout above resistance", invalidation_condition="Close below 3460",
        bear_case="FII selling pressure",
        actual_entry=3502.0, actual_exit=3598.0, pnl=9600.0,
        exit_reason="target_hit", quantity=100,
    )
    defaults.update(overrides)
    return TradeScorecard(**defaults)


def test_scorecard_r_multiple():
    sc = _make_scorecard()
    assert sc.r_multiple == pytest.approx(1.92)


def test_scorecard_r_multiple_zero_when_stop_equals_entry():
    sc = _make_scorecard(predicted_stop=3500.0)
    assert sc.r_multiple == 0.0


def test_scorecard_hit_target_long():
    sc = _make_scorecard(actual_exit=3600.0)
    assert sc.hit_target is True


def test_scorecard_missed_target_long():
    sc = _make_scorecard(actual_exit=3451.0)
    assert sc.hit_target is False


def test_scorecard_hit_target_short():
    sc = _make_scorecard(direction="short", actual_exit=3400.0,
                         predicted_entry=3500.0, predicted_target_1=3400.0)
    assert sc.hit_target is True


def test_scorecard_entry_slippage():
    sc = _make_scorecard()
    assert sc.entry_slippage == pytest.approx(2.0)


def test_scorecard_predicted_rr():
    sc = _make_scorecard()
    assert sc.predicted_rr == pytest.approx(2.0)


def test_scorecard_invalidation_fired_numeric():
    sc = _make_scorecard(
        invalidation_condition="Close below 3460",
        actual_exit=3451.0, pnl=-5100.0,
    )
    assert sc.invalidation_fired is True


def test_scorecard_invalidation_not_fired():
    sc = _make_scorecard(
        invalidation_condition="Close below 3460",
        actual_exit=3598.0,
    )
    assert sc.invalidation_fired is False


def test_invalidation_fired_false_on_unparseable_condition():
    sc = _make_scorecard(invalidation_condition="Market sentiment shift")
    assert sc.invalidation_fired is False


def test_strategy_stats_frozen():
    ss = StrategyStats(trades=10, win_rate=0.65, avg_r=0.8, total_pnl=5000.0)
    assert ss.trades == 10
    with pytest.raises(AttributeError):
        ss.trades = 20


def test_performance_stats_creation():
    ps = PerformanceStats(
        period_days=30, total_trades=42, win_rate=0.595,
        avg_r_multiple=0.8, total_pnl=12400.0,
        by_strategy={}, by_regime={}, by_strategy_regime={},
        confluence_buckets={"low": 0.42, "mid": 0.58, "high": 0.73},
        confidence_calibration={"0.5-0.6": 0.48, "0.6-0.7": 0.55},
    )
    assert ps.total_trades == 42
