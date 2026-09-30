"""Tier 3 Deep Analyzer + Adversarial Validation.

Two LLM call types:
  1. deep_analyze        -- per-stock: designs precise trade setups
  2. validate_portfolio  -- adversarial: stress-tests the full trade book
"""

from __future__ import annotations

import logging
from typing import Any

from tradingbot.core.llm.provider import LLMProvider
from tradingbot.analysis.prompts import (
    DEEP_ANALYSIS_SYSTEM, DEEP_ANALYSIS_TOOL, build_deep_analysis_user_prompt,
    ADVERSARIAL_SYSTEM, ADVERSARIAL_TOOL,
)

log = logging.getLogger(__name__)


class Tier3Analyzer:
    """Per-stock deep analysis and adversarial portfolio validation."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def deep_analyze(
        self,
        symbol: str,
        direction: str,
        regime: dict,
        indicators: dict,
        backtest_results: list[dict],
        price_action: str,
        performance_context: str = "",
    ) -> dict[str, Any]:
        """Design 1-3 precise trade setups for a single stock.

        Returns setups with entry/stop/targets only when 3+ confluence
        signals exist and R:R >= 1.5:1. Otherwise returns no_trade_reason.
        """
        user_prompt = build_deep_analysis_user_prompt(
            symbol, direction, regime, indicators,
            backtest_results, price_action,
            performance_context=performance_context,
        )
        name, desc, schema = DEEP_ANALYSIS_TOOL
        result = await self._provider.analyze(
            DEEP_ANALYSIS_SYSTEM, user_prompt, name, desc, schema,
        )
        n_setups = len(result.get("setups", []))
        no_trade = result.get("no_trade_reason")
        if no_trade:
            log.info("%s: no trade -- %s", symbol, no_trade)
        else:
            log.info("%s: %d setups proposed", symbol, n_setups)
        return result

    async def validate_portfolio(
        self,
        all_setups: list[dict],
        regime: dict,
        sector_analysis: dict,
    ) -> dict[str, Any]:
        """Adversarial review of the full proposed trade book.

        Checks correlations, total risk, regime alignment. Approves,
        rejects, or conditionally approves each setup.
        """
        setups_text = "\n\n".join(
            f"Stock: {s['symbol']}\n"
            + "\n".join(
                f"  Setup {i}: {setup.get('strategy', 'unknown')} "
                f"{setup.get('direction', '?')} @ {setup.get('entry_price', 0)} "
                f"SL={setup.get('stop_loss', 0)} T1={setup.get('target_1', 0)} "
                f"conf={setup.get('confidence', 0)}"
                for i, setup in enumerate(s.get("setups", []))
            )
            for s in all_setups
            if s.get("setups")
        )
        user_prompt = (
            f"Market Regime: {regime.get('regime')} "
            f"(confidence: {regime.get('regime_confidence', 0):.0%})\n\n"
            f"Proposed Setups for Today:\n{setups_text}\n\n"
            f"Review as a portfolio. Check correlations, total risk, "
            f"regime alignment. Approve, reject, or conditionally approve each."
        )
        name, desc, schema = ADVERSARIAL_TOOL
        result = await self._provider.analyze(
            ADVERSARIAL_SYSTEM, user_prompt, name, desc, schema,
        )
        approved = len(result.get("approved", []))
        rejected = len(result.get("rejected", []))
        log.info("Validation: %d approved, %d rejected", approved, rejected)
        return result
