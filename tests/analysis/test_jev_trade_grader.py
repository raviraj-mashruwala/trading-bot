"""Tests for Jev trade grader — auto-grade execution quality + plan quality."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _noul(v):
    return SimpleNamespace(noul=v)


def _score(v, c=0.8):
    return SimpleNamespace(score=v, confidence=c)


def _mock_jev(answers):
    client = MagicMock()
    client.available = True
    client.evaluate = MagicMock(return_value=answers)
    return client


def _scorecard():
    return {
        "predicted_entry": 2450.0,
        "predicted_stop": 2430.0,
        "predicted_target_1": 2490.0,
        "strategy": "breakout",
        "direction": "long",
        "actual_entry": 2452.0,
        "actual_exit": 2485.0,
        "pnl": 3300.0,
        "exit_reason": "target_1",
        "r_multiple": 1.65,
    }


def _grade_answers(execution=2.5, plan_good=0.8, notable=0.3):
    return {
        "execution_quality": _score(execution),
        "plan_was_good": _noul(plan_good),
        "learned_something": _noul(notable),
    }


@pytest.mark.asyncio
async def test_grades_good_trade():
    from tradingbot.analysis.jev_trade_grader import grade_trade
    jev = _mock_jev(_grade_answers(execution=2.7, plan_good=0.85))
    result = await grade_trade(jev, _scorecard())
    assert result["execution_grade"] > 0.8
    assert result["plan_quality"] > 0.7
    assert result["notable"] is False


@pytest.mark.asyncio
async def test_grades_poor_execution():
    from tradingbot.analysis.jev_trade_grader import grade_trade
    jev = _mock_jev(_grade_answers(execution=0.5, plan_good=0.7))
    result = await grade_trade(jev, _scorecard())
    assert result["execution_grade"] < 0.3


@pytest.mark.asyncio
async def test_detects_notable_trade():
    from tradingbot.analysis.jev_trade_grader import grade_trade
    jev = _mock_jev(_grade_answers(notable=0.85))
    result = await grade_trade(jev, _scorecard())
    assert result["notable"] is True


@pytest.mark.asyncio
async def test_jev_fails_returns_defaults():
    from tradingbot.analysis.jev_trade_grader import grade_trade
    jev = _mock_jev(None)
    result = await grade_trade(jev, _scorecard())
    assert result["execution_grade"] == 0.0
    assert result["plan_quality"] == 0.0
    assert result["notable"] is False


@pytest.mark.asyncio
async def test_returns_all_fields():
    from tradingbot.analysis.jev_trade_grader import grade_trade
    jev = _mock_jev(_grade_answers())
    result = await grade_trade(jev, _scorecard())
    assert "execution_grade" in result
    assert "plan_quality" in result
    assert "notable" in result
