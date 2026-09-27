"""Tier 2 LLM Analyzer: market regime, sector analysis, candidate shortlisting.

Three focused LLM calls that build on each other:
  1. analyze_regime  -- determines market regime and bias
  2. analyze_sectors -- sector-level opportunities given the regime
  3. shortlist       -- 10-15 high-conviction candidates from scored stocks
"""

from __future__ import annotations

import logging
from typing import Any

from tradingbot.core.llm.provider import LLMProvider
from tradingbot.analysis.prompts import (
    REGIME_SYSTEM, REGIME_TOOL, build_regime_user_prompt,
    SECTOR_SYSTEM, SECTOR_TOOL,
    SHORTLIST_SYSTEM, SHORTLIST_TOOL, build_shortlist_user_prompt,
)

log = logging.getLogger(__name__)


class Tier2Analyzer:
    """Orchestrates the three Tier 2 LLM calls."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def analyze_regime(
        self,
        nifty: float,
        banknifty: float,
        vix: float,
        nifty_5d_change: float,
        fii_5d_net: float,
        dii_5d_net: float,
        advance_decline: float,
        sector_data: dict[str, float],
    ) -> dict[str, Any]:
        """Determine current market regime from broad market data."""
        user_prompt = build_regime_user_prompt(
            nifty, banknifty, vix, nifty_5d_change,
            fii_5d_net, dii_5d_net, advance_decline, sector_data,
        )
        name, desc, schema = REGIME_TOOL
        result = await self._provider.analyze(
            REGIME_SYSTEM, user_prompt, name, desc, schema,
        )
        log.info(
            "Regime: %s (confidence: %.0f%%)",
            result.get("regime"),
            result.get("regime_confidence", 0) * 100,
        )
        return result

    async def analyze_sectors(
        self,
        regime: dict,
        sector_data: dict,
        top_stocks_by_sector: dict,
    ) -> dict[str, Any]:
        """Identify best sector-level opportunities given the regime."""
        user_prompt = (
            f"Market Regime: {regime.get('regime')} "
            f"(confidence: {regime.get('regime_confidence', 0):.0%})\n"
            f"Sectors in play: {regime.get('sectors_in_play', [])}\n\n"
            f"Sector Index Data:\n"
            + "\n".join(f"  {k}: {v}" for k, v in sector_data.items())
            + f"\n\nTop stocks per sector:\n"
            + "\n".join(
                f"  {sector}: {', '.join(stocks)}"
                for sector, stocks in top_stocks_by_sector.items()
            )
        )
        name, desc, schema = SECTOR_TOOL
        return await self._provider.analyze(
            SECTOR_SYSTEM, user_prompt, name, desc, schema,
        )

    async def shortlist(
        self,
        regime: dict,
        sector_analysis: dict,
        scored_stocks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Select 10-15 high-conviction candidates from scored stock list."""
        user_prompt = build_shortlist_user_prompt(
            regime, sector_analysis, scored_stocks,
        )
        name, desc, schema = SHORTLIST_TOOL
        result = await self._provider.analyze(
            SHORTLIST_SYSTEM, user_prompt, name, desc, schema,
        )
        log.info("Shortlisted %d candidates", len(result.get("shortlist", [])))
        return result
