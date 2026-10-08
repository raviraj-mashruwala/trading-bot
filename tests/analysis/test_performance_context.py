"""Tests for _build_performance_context in AnalysisPipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tradingbot.core.models import PerformanceStats, StrategyStats


def _make_pipeline(**overrides):
    from tradingbot.analysis.pipeline import AnalysisPipeline
    defaults = dict(
        data_sync=MagicMock(), candle_store=MagicMock(), screener=MagicMock(),
        tier2=MagicMock(), tier3=MagicMock(), backtest_engine=MagicMock(),
        monte_carlo=MagicMock(), run_store=MagicMock(),
        setup_store=MagicMock(), event_bus=MagicMock(), capital=100_000,
        db_path="/tmp/test.db",
    )
    defaults.update(overrides)
    return AnalysisPipeline(**defaults)


def _make_stats(total_trades=42) -> PerformanceStats:
    return PerformanceStats(
        period_days=30, total_trades=total_trades, win_rate=0.595,
        avg_r_multiple=0.8, total_pnl=12400.0,
        by_strategy={"breakout": StrategyStats(trades=20, win_rate=0.65, avg_r=0.9, total_pnl=8000.0)},
        by_regime={"trending_up": StrategyStats(trades=22, win_rate=0.68, avg_r=1.0, total_pnl=10000.0)},
        by_strategy_regime={},
        confluence_buckets={"low": 0.42, "mid": 0.58, "high": 0.73},
        confidence_calibration={"0.7-0.8": 0.67},
    )


def test_performance_context_empty_when_no_db_path():
    p = _make_pipeline(db_path=None)
    result = p._build_performance_context()
    assert result == ""


def test_performance_context_empty_under_threshold():
    p = _make_pipeline()
    with patch("tradingbot.analysis.pipeline.TradeReviewStore") as mock_cls:
        mock_store = MagicMock()
        mock_store.get_performance_stats.return_value = _make_stats(total_trades=5)
        mock_cls.return_value = mock_store

        result = p._build_performance_context()
        assert result == ""


def test_performance_context_includes_stats():
    p = _make_pipeline()
    with patch("tradingbot.analysis.pipeline.TradeReviewStore") as mock_cls:
        mock_store = MagicMock()
        mock_store.get_performance_stats.return_value = _make_stats(total_trades=42)
        mock_cls.return_value = mock_store

        result = p._build_performance_context()
        assert "42 trades" in result
        assert "59.5%" in result
        assert "breakout" in result
        assert "onfluence" in result.lower()


def test_performance_context_contains_calibration():
    p = _make_pipeline()
    with patch("tradingbot.analysis.pipeline.TradeReviewStore") as mock_cls:
        mock_store = MagicMock()
        mock_store.get_performance_stats.return_value = _make_stats()
        mock_cls.return_value = mock_store

        result = p._build_performance_context()
        assert "0.7-0.8" in result


def test_deep_analysis_system_mentions_performance():
    from tradingbot.analysis.prompts import DEEP_ANALYSIS_SYSTEM
    assert "performance" in DEEP_ANALYSIS_SYSTEM.lower()
