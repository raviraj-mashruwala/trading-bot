"""Tests for Tier 3 Deep Analyzer + Adversarial Validation."""

import pytest
from unittest.mock import AsyncMock

from tradingbot.analysis.tier3_analyzer import Tier3Analyzer
from tradingbot.analysis.prompts import (
    DEEP_ANALYSIS_SYSTEM, DEEP_ANALYSIS_TOOL,
    ADVERSARIAL_SYSTEM, ADVERSARIAL_TOOL,
)


@pytest.fixture
def mock_provider():
    return AsyncMock()


# ── deep_analyze ─────────────────────────────────────────────────────────────


async def test_deep_analyze_returns_setups(mock_provider):
    mock_provider.analyze.return_value = {
        "symbol": "RELIANCE",
        "setups": [{
            "strategy": "vwap_mean_reversion",
            "direction": "long",
            "entry_price": 2485.0,
            "stop_loss": 2468.0,
            "target_1": 2510.0,
            "target_2": 2530.0,
            "confidence": 0.82,
            "invalidation": "close below 2460",
            "confluence_count": 4,
        }],
        "no_trade_reason": None,
    }
    analyzer = Tier3Analyzer(mock_provider)
    result = await analyzer.deep_analyze(
        symbol="RELIANCE", direction="long",
        regime={"regime": "trending_up"},
        indicators={"rsi_14": 45, "vwap": 2505},
        backtest_results=[],
        price_action="3 day pullback to VWAP support",
    )
    assert result["symbol"] == "RELIANCE"
    assert len(result["setups"]) == 1
    assert result["setups"][0]["confidence"] == 0.82
    assert result["setups"][0]["confluence_count"] == 4


async def test_deep_analyze_no_trade(mock_provider):
    mock_provider.analyze.return_value = {
        "symbol": "TCS",
        "setups": [],
        "no_trade_reason": "No 3+ confluence found. RSI and Stoch both momentum = 1 signal.",
    }
    analyzer = Tier3Analyzer(mock_provider)
    result = await analyzer.deep_analyze(
        symbol="TCS", direction="short",
        regime={"regime": "range_bound"},
        indicators={"rsi_14": 55},
        backtest_results=[], price_action="choppy",
    )
    assert result["symbol"] == "TCS"
    assert len(result["setups"]) == 0
    assert result["no_trade_reason"] is not None


async def test_deep_analyze_passes_correct_prompt(mock_provider):
    mock_provider.analyze.return_value = {"symbol": "INFY", "setups": []}
    analyzer = Tier3Analyzer(mock_provider)
    await analyzer.deep_analyze(
        symbol="INFY", direction="long",
        regime={"regime": "trending_up"},
        indicators={"rsi_14": 40, "adx": 28, "vwap": 1400},
        backtest_results=[{
            "strategy": "breakout", "total_trades": 15,
            "win_rate": 0.60, "profit_factor": 1.8, "expectancy_r": 0.25,
        }],
        price_action="consolidation near VWAP",
    )
    call_args = mock_provider.analyze.call_args
    assert call_args[0][0] == DEEP_ANALYSIS_SYSTEM
    assert "INFY" in call_args[0][1]
    assert "rsi_14" in call_args[0][1]
    assert "breakout" in call_args[0][1]
    name, desc, schema = DEEP_ANALYSIS_TOOL
    assert call_args[0][2] == name
    assert call_args[0][3] == desc
    assert call_args[0][4] == schema


async def test_deep_analyze_multiple_setups(mock_provider):
    mock_provider.analyze.return_value = {
        "symbol": "HDFCBANK",
        "setups": [
            {"strategy": "vwap_bounce", "direction": "long",
             "entry_price": 1650, "stop_loss": 1640,
             "target_1": 1670, "confidence": 0.78,
             "invalidation": "below 1635", "confluence_count": 3},
            {"strategy": "orb_breakout", "direction": "long",
             "entry_price": 1660, "stop_loss": 1645,
             "target_1": 1685, "confidence": 0.72,
             "invalidation": "fails to hold 1655", "confluence_count": 3},
        ],
        "no_trade_reason": None,
    }
    analyzer = Tier3Analyzer(mock_provider)
    result = await analyzer.deep_analyze(
        symbol="HDFCBANK", direction="long",
        regime={"regime": "trending_up"},
        indicators={}, backtest_results=[], price_action="bullish",
    )
    assert len(result["setups"]) == 2


# ── validate_portfolio ───────────────────────────────────────────────────────


async def test_validate_portfolio(mock_provider):
    mock_provider.analyze.return_value = {
        "approved": [
            {"symbol": "RELIANCE", "setup_index": 0, "approval": "strong"},
        ],
        "rejected": [
            {"symbol": "TCS", "setup_index": 0,
             "reason": "regime contradiction — shorting in bullish regime"},
        ],
        "portfolio_risk_assessment": {
            "total_setups": 2,
            "approved_count": 1,
            "max_correlated_exposure": "none",
            "regime_alignment": "1/2 aligned",
            "worst_case_loss": "1.2%",
            "recommendation": "proceed with RELIANCE only",
        },
    }
    analyzer = Tier3Analyzer(mock_provider)
    result = await analyzer.validate_portfolio(
        all_setups=[
            {"symbol": "RELIANCE", "setups": [{"strategy": "vwap", "direction": "long",
             "entry_price": 2485, "stop_loss": 2468, "target_1": 2510, "confidence": 0.82}]},
            {"symbol": "TCS", "setups": [{"strategy": "breakdown", "direction": "short",
             "entry_price": 3500, "stop_loss": 3530, "target_1": 3440, "confidence": 0.65}]},
        ],
        regime={"regime": "trending_up", "regime_confidence": 0.82},
        sector_analysis={},
    )
    assert len(result["approved"]) == 1
    assert len(result["rejected"]) == 1
    assert result["portfolio_risk_assessment"]["approved_count"] == 1
    assert result["portfolio_risk_assessment"]["total_setups"] == 2


async def test_validate_portfolio_passes_correct_prompt(mock_provider):
    mock_provider.analyze.return_value = {
        "approved": [], "rejected": [],
        "portfolio_risk_assessment": {
            "total_setups": 0, "approved_count": 0,
            "recommendation": "no trades",
        },
    }
    analyzer = Tier3Analyzer(mock_provider)
    await analyzer.validate_portfolio(
        all_setups=[], regime={"regime": "volatile", "regime_confidence": 0.6},
        sector_analysis={},
    )
    call_args = mock_provider.analyze.call_args
    assert call_args[0][0] == ADVERSARIAL_SYSTEM
    name, desc, schema = ADVERSARIAL_TOOL
    assert call_args[0][2] == name
    assert call_args[0][4] == schema


async def test_validate_portfolio_all_approved(mock_provider):
    mock_provider.analyze.return_value = {
        "approved": [
            {"symbol": "RELIANCE", "setup_index": 0, "approval": "strong"},
            {"symbol": "HDFCBANK", "setup_index": 0, "approval": "conditional",
             "adjustment": "reduce size to 0.5x"},
        ],
        "rejected": [],
        "portfolio_risk_assessment": {
            "total_setups": 2, "approved_count": 2,
            "recommendation": "execute with reduced HDFCBANK size",
        },
    }
    analyzer = Tier3Analyzer(mock_provider)
    result = await analyzer.validate_portfolio(
        all_setups=[
            {"symbol": "RELIANCE", "setups": [{"confidence": 0.85}]},
            {"symbol": "HDFCBANK", "setups": [{"confidence": 0.72}]},
        ],
        regime={"regime": "trending_up", "regime_confidence": 0.8},
        sector_analysis={},
    )
    assert len(result["approved"]) == 2
    assert result["approved"][1]["approval"] == "conditional"
    assert result["approved"][1]["adjustment"] == "reduce size to 0.5x"


async def test_validate_portfolio_includes_setups_in_prompt(mock_provider):
    mock_provider.analyze.return_value = {
        "approved": [], "rejected": [],
        "portfolio_risk_assessment": {
            "total_setups": 1, "approved_count": 0, "recommendation": "skip all",
        },
    }
    analyzer = Tier3Analyzer(mock_provider)
    await analyzer.validate_portfolio(
        all_setups=[
            {"symbol": "SBIN", "setups": [{
                "strategy": "pullback", "direction": "long",
                "entry_price": 620, "stop_loss": 612,
                "target_1": 635, "confidence": 0.75,
            }]},
        ],
        regime={"regime": "trending_up", "regime_confidence": 0.8},
        sector_analysis={},
    )
    user_prompt = mock_provider.analyze.call_args[0][1]
    assert "SBIN" in user_prompt
    assert "620" in user_prompt
    assert "pullback" in user_prompt
