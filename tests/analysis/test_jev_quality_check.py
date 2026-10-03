"""Tests for Jev setup quality check — overfit detection + confluence."""

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


def _setup_data():
    return {
        "strategy": "breakout",
        "direction": "long",
        "entry_price": 2450.0,
        "stop_loss": 2430.0,
        "target_1": 2490.0,
        "target_2": 2520.0,
        "confidence": 0.75,
        "edge_description": "Price breaking above resistance with volume",
    }


def _backtest_summary():
    return {
        "win_rate": 0.55,
        "profit_factor": 1.8,
        "max_drawdown": 0.08,
        "n_trades": 42,
        "avg_r": 1.2,
    }


def _quality_answers(credible=0.8, confluence=1.8, rr_realistic=0.75, overfitted=0.2):
    return {
        "backtest_credible": _noul(credible),
        "setup_confluence": _score(confluence),
        "risk_reward_realistic": _noul(rr_realistic),
        "overfitted": _noul(overfitted),
    }


@pytest.mark.asyncio
async def test_quality_passes_good_setup():
    from tradingbot.analysis.jev_quality_check import jev_quality_check
    jev = _mock_jev(_quality_answers(credible=0.8, overfitted=0.15))
    result = await jev_quality_check(jev, _setup_data(), _backtest_summary())
    assert result["pass"] is True
    assert result["quality_score"] > 0.5


@pytest.mark.asyncio
async def test_quality_rejects_overfitted():
    from tradingbot.analysis.jev_quality_check import jev_quality_check
    jev = _mock_jev(_quality_answers(overfitted=0.75))
    result = await jev_quality_check(jev, _setup_data(), _backtest_summary())
    assert result["pass"] is False
    assert result["details"]["overfit_risk"] > 0.6


@pytest.mark.asyncio
async def test_quality_rejects_low_credibility():
    from tradingbot.analysis.jev_quality_check import jev_quality_check
    jev = _mock_jev(_quality_answers(credible=0.2))
    result = await jev_quality_check(jev, _setup_data(), _backtest_summary())
    assert result["pass"] is False


@pytest.mark.asyncio
async def test_quality_returns_pass_on_jev_failure():
    from tradingbot.analysis.jev_quality_check import jev_quality_check
    jev = _mock_jev(None)
    result = await jev_quality_check(jev, _setup_data(), _backtest_summary())
    assert result["pass"] is True  # don't block on Jev failure


@pytest.mark.asyncio
async def test_quality_returns_all_detail_fields():
    from tradingbot.analysis.jev_quality_check import jev_quality_check
    jev = _mock_jev(_quality_answers())
    result = await jev_quality_check(jev, _setup_data(), _backtest_summary())
    assert "quality_score" in result
    assert "pass" in result
    assert "details" in result
    details = result["details"]
    assert "backtest_credible" in details
    assert "confluence" in details
    assert "rr_realistic" in details
    assert "overfit_risk" in details
