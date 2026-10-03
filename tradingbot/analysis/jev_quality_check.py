"""Jev-based setup quality check: overfit detection + confluence scoring."""

from __future__ import annotations

import logging
from typing import Any

from tradingbot.core.jev_client import JevClient, Noul, Score

log = logging.getLogger(__name__)

_PASS_DEFAULT = {"pass": True, "quality_score": 1.0, "details": {}}


def _build_questions() -> dict:
    try:
        if Noul is None:
            return {}
    except Exception:
        return {}
    return {
        "backtest_credible": Noul(
            instructions=(
                "Is the backtest result statistically credible? "
                "Consider trade count, consistency, and whether results "
                "could be from curve-fitting."
            ),
            criteria={
                "true": "Sufficient trades, consistent performance, realistic results",
                "false": "Too few trades, suspiciously perfect, or likely overfitted",
            },
        ),
        "setup_confluence": Score(
            instructions="How many independent signals support this trade setup?",
            criteria=[
                "Single signal — one indicator or pattern only",
                "Two signals — some confluence",
                "Three+ signals — strong multi-factor confluence",
            ],
        ),
        "risk_reward_realistic": Noul(
            instructions=(
                "Are the target and stop-loss levels realistic based on "
                "the stock's characteristics and recent price action?"
            ),
            criteria={
                "true": "Levels are plausible given the stock's volatility and structure",
                "false": "Target too ambitious or stop too tight for the stock's behavior",
            },
        ),
        "overfitted": Noul(
            instructions=(
                "Does this setup show signs of overfitting — too-perfect backtest, "
                "narrow conditions, or cherry-picked parameters?"
            ),
            criteria={
                "true": "Suspiciously good results that likely won't generalize",
                "false": "Results are robust and likely to hold out-of-sample",
            },
        ),
    }


async def jev_quality_check(
    jev_client: JevClient,
    setup_data: dict[str, Any],
    backtest_summary: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate setup quality via Jev. Returns pass=True on failure (don't block)."""
    state = {
        "setup": {
            "strategy": setup_data.get("strategy", "unknown"),
            "direction": setup_data.get("direction", "long"),
            "entry_price": setup_data.get("entry_price"),
            "stop_loss": setup_data.get("stop_loss"),
            "target_1": setup_data.get("target_1"),
            "confidence": setup_data.get("confidence"),
        },
        "backtest": backtest_summary,
    }

    answers = jev_client.evaluate(state=state, questions=_build_questions())
    if answers is None:
        return _PASS_DEFAULT

    try:
        credible = answers["backtest_credible"].noul
        confluence = answers["setup_confluence"].score / 2.0
        rr_realistic = answers["risk_reward_realistic"].noul
        overfitted = answers["overfitted"].noul

        quality = (
            0.3 * credible
            + 0.3 * confluence
            + 0.25 * rr_realistic
            + 0.15 * (1.0 - overfitted)
        )

        passed = quality > 0.5 and overfitted < 0.6 and credible > 0.4

        return {
            "quality_score": round(quality, 3),
            "pass": passed,
            "details": {
                "backtest_credible": round(credible, 3),
                "confluence": round(confluence, 3),
                "rr_realistic": round(rr_realistic, 3),
                "overfit_risk": round(overfitted, 3),
            },
        }
    except Exception:
        log.warning("Jev quality check parsing failed", exc_info=True)
        return _PASS_DEFAULT
