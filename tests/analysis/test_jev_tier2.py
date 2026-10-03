"""Tests for JevTier2Analyzer — Jev-based regime + sector classification."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _noul(v):
    return SimpleNamespace(noul=v)


def _choice(v, c=0.8):
    return SimpleNamespace(choice=v, confidence=c)


def _score(v, c=0.8):
    return SimpleNamespace(score=v, confidence=c)


def _mock_jev(answers):
    client = MagicMock()
    client.available = True
    client.evaluate = MagicMock(return_value=answers)
    return client


def _regime_answers(regime="trending_up", conf_score=2.5, bias="bullish",
                    risk="moderate", trend=2.5, inst=3.0):
    return {
        "regime": _choice(regime, 0.85),
        "regime_confidence_level": _score(conf_score),
        "bias": _choice(bias),
        "risk_appetite": _choice(risk),
        "trend_strength": _score(trend),
        "institutional_sentiment": _score(inst),
    }


def _sector_answers():
    """Banking strong, IT weak, pharma moderate."""
    answers = {}
    data = {"banking": (3.5, 0.8), "it": (1.0, 0.2), "pharma": (2.0, 0.5),
            "auto": (2.5, 0.6), "metal": (1.5, 0.3), "fmcg": (2.0, 0.4),
            "energy": (3.0, 0.7), "realty": (1.0, 0.2), "infra": (2.5, 0.5)}
    for sector, (mom, rot) in data.items():
        answers[f"{sector}_momentum"] = _score(mom)
        answers[f"{sector}_rotation"] = _noul(rot)
    return answers


# --- Regime tests ---

@pytest.mark.asyncio
async def test_regime_trending_up():
    from tradingbot.analysis.jev_tier2 import JevTier2Analyzer
    jev = _mock_jev(_regime_answers())
    analyzer = JevTier2Analyzer(jev)
    result = await analyzer.analyze_regime(
        nifty=19500, banknifty=45000, vix=13.5,
        nifty_5d_change=1.2, fii_5d_net=-500, dii_5d_net=800,
        advance_decline=1.4, sector_data={"banking": 1.5},
    )
    assert result["regime"] == "trending_up"
    assert 0.0 <= result["regime_confidence"] <= 1.0
    assert result["bias"] == "bullish"
    assert result["risk_appetite"] == "moderate"


@pytest.mark.asyncio
async def test_regime_volatile_low_confidence():
    from tradingbot.analysis.jev_tier2 import JevTier2Analyzer
    jev = _mock_jev(_regime_answers(regime="volatile", conf_score=1.0))
    analyzer = JevTier2Analyzer(jev)
    result = await analyzer.analyze_regime(
        nifty=19500, banknifty=45000, vix=22.0,
        nifty_5d_change=-0.5, fii_5d_net=-1000, dii_5d_net=200,
        advance_decline=0.8, sector_data={},
    )
    assert result["regime"] == "volatile"
    assert result["regime_confidence"] < 0.5


@pytest.mark.asyncio
async def test_regime_jev_fails_returns_none():
    from tradingbot.analysis.jev_tier2 import JevTier2Analyzer
    jev = _mock_jev(None)
    analyzer = JevTier2Analyzer(jev)
    result = await analyzer.analyze_regime(
        nifty=19500, banknifty=45000, vix=13.5,
        nifty_5d_change=1.2, fii_5d_net=0, dii_5d_net=0,
        advance_decline=1.0, sector_data={},
    )
    assert result is None


@pytest.mark.asyncio
async def test_regime_returns_all_schema_fields():
    from tradingbot.analysis.jev_tier2 import JevTier2Analyzer
    jev = _mock_jev(_regime_answers())
    analyzer = JevTier2Analyzer(jev)
    result = await analyzer.analyze_regime(
        nifty=19500, banknifty=45000, vix=13.5,
        nifty_5d_change=1.2, fii_5d_net=0, dii_5d_net=0,
        advance_decline=1.0, sector_data={},
    )
    required_keys = {"regime", "regime_confidence", "bias", "key_levels",
                     "sectors_in_play", "sectors_to_avoid", "risk_appetite", "reasoning"}
    assert required_keys.issubset(result.keys())


# --- Sector tests ---

@pytest.mark.asyncio
async def test_sectors_ranked_by_composite():
    from tradingbot.analysis.jev_tier2 import JevTier2Analyzer
    jev = _mock_jev(_sector_answers())
    analyzer = JevTier2Analyzer(jev)
    result = await analyzer.analyze_sectors(
        regime={"regime": "trending_up"},
        sector_data={}, top_stocks_by_sector={},
    )
    names = [s["name"] for s in result["sectors"]]
    assert names[0] == "banking"


@pytest.mark.asyncio
async def test_sectors_bias_assignment():
    from tradingbot.analysis.jev_tier2 import JevTier2Analyzer
    jev = _mock_jev(_sector_answers())
    analyzer = JevTier2Analyzer(jev)
    result = await analyzer.analyze_sectors(
        regime={"regime": "trending_up"},
        sector_data={}, top_stocks_by_sector={},
    )
    sectors = result["sectors"]
    top3_biases = [s["intraday_bias"] for s in sectors[:3]]
    bottom3_biases = [s["intraday_bias"] for s in sectors[-3:]]
    assert all(b == "bullish" for b in top3_biases)
    assert all(b == "bearish" for b in bottom3_biases)


@pytest.mark.asyncio
async def test_sectors_jev_fails_returns_none():
    from tradingbot.analysis.jev_tier2 import JevTier2Analyzer
    jev = _mock_jev(None)
    analyzer = JevTier2Analyzer(jev)
    result = await analyzer.analyze_sectors(
        regime={"regime": "trending_up"}, sector_data={}, top_stocks_by_sector={},
    )
    assert result is None


@pytest.mark.asyncio
async def test_sectors_returns_all_schema_fields():
    from tradingbot.analysis.jev_tier2 import JevTier2Analyzer
    jev = _mock_jev(_sector_answers())
    analyzer = JevTier2Analyzer(jev)
    result = await analyzer.analyze_sectors(
        regime={"regime": "trending_up"}, sector_data={}, top_stocks_by_sector={},
    )
    assert "sectors" in result
    assert "reasoning" in result
    assert len(result["sectors"]) == 9
    for s in result["sectors"]:
        assert "name" in s
        assert "intraday_bias" in s
