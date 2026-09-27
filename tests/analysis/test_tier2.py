"""Tests for Tier 2 LLM Analyzer (regime, sector, shortlist)."""

import pytest
from unittest.mock import AsyncMock

from tradingbot.analysis.tier2_analyzer import Tier2Analyzer
from tradingbot.analysis.prompts import (
    REGIME_SYSTEM, REGIME_TOOL,
    SECTOR_SYSTEM, SECTOR_TOOL,
    SHORTLIST_SYSTEM, SHORTLIST_TOOL,
)


@pytest.fixture
def mock_provider():
    return AsyncMock()


# ── analyze_regime ───────────────────────────────────────────────────────────


async def test_analyze_regime_returns_result(mock_provider):
    mock_provider.analyze.return_value = {
        "regime": "trending_up",
        "regime_confidence": 0.82,
        "bias": "bullish",
        "key_levels": {"nifty_support": 19200, "nifty_resistance": 19600},
        "sectors_in_play": ["banking", "IT"],
        "sectors_to_avoid": ["pharma"],
        "risk_appetite": "moderate",
        "reasoning": "test reasoning",
    }
    analyzer = Tier2Analyzer(mock_provider)
    result = await analyzer.analyze_regime(
        nifty=19500, banknifty=45000, vix=13.5,
        nifty_5d_change=1.2, fii_5d_net=-500, dii_5d_net=800,
        advance_decline=1.4, sector_data={"banking": 1.5},
    )
    assert result["regime"] == "trending_up"
    assert result["regime_confidence"] == 0.82
    mock_provider.analyze.assert_called_once()


async def test_analyze_regime_passes_correct_prompt(mock_provider):
    mock_provider.analyze.return_value = {
        "regime": "range_bound", "regime_confidence": 0.5,
        "bias": "neutral", "key_levels": {"nifty_support": 19000, "nifty_resistance": 19600},
        "sectors_in_play": [], "risk_appetite": "defensive", "reasoning": "flat",
    }
    analyzer = Tier2Analyzer(mock_provider)
    await analyzer.analyze_regime(
        nifty=19500, banknifty=45000, vix=13.5,
        nifty_5d_change=0.1, fii_5d_net=0, dii_5d_net=0,
        advance_decline=1.0, sector_data={},
    )
    call_args = mock_provider.analyze.call_args
    assert call_args[0][0] == REGIME_SYSTEM  # system prompt
    assert "19500" in call_args[0][1]  # user prompt contains nifty
    name, desc, schema = REGIME_TOOL
    assert call_args[0][2] == name
    assert call_args[0][3] == desc
    assert call_args[0][4] == schema


# ── analyze_sectors ──────────────────────────────────────────────────────────


async def test_analyze_sectors_returns_result(mock_provider):
    mock_provider.analyze.return_value = {
        "sectors": [
            {"name": "banking", "intraday_bias": "bullish"},
            {"name": "IT", "intraday_bias": "bearish"},
        ],
        "reasoning": "banking strong due to rate cut expectations",
    }
    analyzer = Tier2Analyzer(mock_provider)
    regime = {"regime": "trending_up", "regime_confidence": 0.82,
              "sectors_in_play": ["banking"]}
    result = await analyzer.analyze_sectors(
        regime=regime,
        sector_data={"NIFTYBANK": "+1.2%", "NIFTYIT": "-0.5%"},
        top_stocks_by_sector={"banking": ["HDFCBANK", "ICICIBANK"]},
    )
    assert len(result["sectors"]) == 2
    assert result["sectors"][0]["name"] == "banking"


async def test_analyze_sectors_passes_correct_tool(mock_provider):
    mock_provider.analyze.return_value = {"sectors": [], "reasoning": "n/a"}
    analyzer = Tier2Analyzer(mock_provider)
    await analyzer.analyze_sectors(
        regime={"regime": "range_bound", "regime_confidence": 0.5, "sectors_in_play": []},
        sector_data={}, top_stocks_by_sector={},
    )
    call_args = mock_provider.analyze.call_args
    assert call_args[0][0] == SECTOR_SYSTEM
    name, desc, schema = SECTOR_TOOL
    assert call_args[0][2] == name
    assert call_args[0][4] == schema


# ── shortlist ────────────────────────────────────────────────────────────────


async def test_shortlist_returns_list(mock_provider):
    mock_provider.analyze.return_value = {
        "shortlist": [
            {"symbol": "RELIANCE", "direction": "long", "conviction": "high",
             "reasoning": "strong momentum"},
            {"symbol": "HDFCBANK", "direction": "long", "conviction": "medium",
             "reasoning": "sector rotation"},
        ],
        "max_positions_today": 3,
        "reasoning": "bullish regime favors longs",
    }
    analyzer = Tier2Analyzer(mock_provider)
    regime = {"regime": "trending_up", "regime_confidence": 0.82,
              "bias": "bullish", "sectors_in_play": ["energy"],
              "sectors_to_avoid": [], "risk_appetite": "moderate"}
    result = await analyzer.shortlist(regime, {}, [])
    assert len(result["shortlist"]) == 2
    assert result["shortlist"][0]["symbol"] == "RELIANCE"
    assert result["max_positions_today"] == 3


async def test_shortlist_passes_correct_prompt(mock_provider):
    mock_provider.analyze.return_value = {
        "shortlist": [], "max_positions_today": 1, "reasoning": "nothing",
    }
    analyzer = Tier2Analyzer(mock_provider)
    regime = {"regime": "volatile", "regime_confidence": 0.6,
              "bias": "bearish", "sectors_in_play": [],
              "sectors_to_avoid": ["pharma"], "risk_appetite": "defensive"}
    scored = [{"symbol": "TCS", "composite_score": 90, "sector": "IT",
               "last_price": 3500, "factor_scores": {"volume_surge": 2.0}}]
    await analyzer.shortlist(regime, {}, scored)
    call_args = mock_provider.analyze.call_args
    assert call_args[0][0] == SHORTLIST_SYSTEM
    assert "TCS" in call_args[0][1]  # user prompt
    name, desc, schema = SHORTLIST_TOOL
    assert call_args[0][2] == name
    assert call_args[0][4] == schema


async def test_shortlist_with_scored_stocks_data(mock_provider):
    mock_provider.analyze.return_value = {
        "shortlist": [{"symbol": "INFY", "direction": "short",
                       "conviction": "high", "reasoning": "weak IT"}],
        "max_positions_today": 2, "reasoning": "bearish regime",
    }
    analyzer = Tier2Analyzer(mock_provider)
    regime = {"regime": "trending_down", "regime_confidence": 0.75,
              "bias": "bearish", "sectors_in_play": ["IT"],
              "sectors_to_avoid": [], "risk_appetite": "moderate"}
    scored = [
        {"symbol": "INFY", "composite_score": 80, "sector": "IT",
         "last_price": 1400, "factor_scores": {"relative_strength": -0.5}},
        {"symbol": "TCS", "composite_score": 70, "sector": "IT",
         "last_price": 3500, "factor_scores": {}},
    ]
    result = await analyzer.shortlist(regime, {}, scored)
    assert result["shortlist"][0]["symbol"] == "INFY"
    # verify user prompt included both stocks
    user_prompt = mock_provider.analyze.call_args[0][1]
    assert "INFY" in user_prompt
    assert "TCS" in user_prompt
