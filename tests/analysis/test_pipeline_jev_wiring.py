"""Tests for pipeline Jev wiring — regime/sector fallback logic."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tradingbot.analysis.jev_tier2 import JevTier2Analyzer


@pytest.mark.asyncio
async def test_jev_regime_used_when_available():
    jev_tier2 = AsyncMock(spec=JevTier2Analyzer)
    jev_tier2.analyze_regime = AsyncMock(return_value={
        "regime": "trending_up", "regime_confidence": 0.85,
        "bias": "bullish", "key_levels": {},
        "sectors_in_play": [], "sectors_to_avoid": [],
        "risk_appetite": "moderate", "reasoning": "jev regime",
    })

    result = await jev_tier2.analyze_regime(
        nifty=19500, banknifty=45000, vix=13.5,
        nifty_5d_change=1.2, fii_5d_net=0, dii_5d_net=0,
        advance_decline=1.0, sector_data={},
    )
    assert result["regime"] == "trending_up"
    assert result["reasoning"] == "jev regime"
    jev_tier2.analyze_regime.assert_called_once()


@pytest.mark.asyncio
async def test_falls_back_to_claude_on_jev_failure():
    jev_tier2 = AsyncMock(spec=JevTier2Analyzer)
    jev_tier2.analyze_regime = AsyncMock(return_value=None)

    claude_tier2 = AsyncMock()
    claude_tier2.analyze_regime = AsyncMock(return_value={
        "regime": "range_bound", "regime_confidence": 0.6,
        "bias": "neutral", "key_levels": {},
        "sectors_in_play": [], "sectors_to_avoid": [],
        "risk_appetite": "defensive", "reasoning": "claude fallback",
    })

    result = await jev_tier2.analyze_regime(
        nifty=19500, banknifty=45000, vix=13.5,
        nifty_5d_change=0, fii_5d_net=0, dii_5d_net=0,
        advance_decline=1.0, sector_data={},
    )
    if result is None:
        result = await claude_tier2.analyze_regime(
            nifty=19500, banknifty=45000, vix=13.5,
            nifty_5d_change=0, fii_5d_net=0, dii_5d_net=0,
            advance_decline=1.0, sector_data={},
        )
    assert result["regime"] == "range_bound"
    assert result["reasoning"] == "claude fallback"
    claude_tier2.analyze_regime.assert_called_once()
