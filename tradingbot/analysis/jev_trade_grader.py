"""Jev-based post-trade grading: execution quality + plan quality."""

from __future__ import annotations

import logging
from typing import Any

from tradingbot.core.jev_client import JevClient, Noul, Score

log = logging.getLogger(__name__)

_DEFAULT = {"execution_grade": 0.0, "plan_quality": 0.0, "notable": False}


def _build_questions() -> dict:
    try:
        if Score is None:
            return {}
    except Exception:
        return {}
    return {
        "execution_quality": Score(
            instructions="How well was this trade executed vs. the plan?",
            criteria=[
                "Poor — large slippage, missed entry/exit, deviated from plan",
                "Acceptable — minor deviations, reasonable execution",
                "Good — executed close to plan with minimal slippage",
                "Excellent — textbook execution, optimal timing",
            ],
        ),
        "plan_was_good": Noul(
            instructions="Was the original trade plan well-designed (regardless of outcome)?",
            criteria={
                "true": "Sound thesis, realistic levels, good risk-reward, clear edge",
                "false": "Flawed thesis, unrealistic levels, or no clear edge",
            },
        ),
        "learned_something": Noul(
            instructions="Does this trade reveal a pattern worth noting for future reference?",
            criteria={
                "true": "Unusual outcome, edge case, or actionable insight for future trades",
                "false": "Routine trade outcome — nothing new to learn",
            },
        ),
    }


async def grade_trade(
    jev_client: JevClient,
    scorecard: dict[str, Any],
) -> dict[str, Any]:
    """Grade a completed trade. Returns defaults on Jev failure."""
    state = {
        "plan": {
            "entry_price": scorecard.get("predicted_entry"),
            "stop_loss": scorecard.get("predicted_stop"),
            "target_1": scorecard.get("predicted_target_1"),
            "strategy": scorecard.get("strategy"),
            "direction": scorecard.get("direction"),
        },
        "execution": {
            "actual_entry": scorecard.get("actual_entry"),
            "actual_exit": scorecard.get("actual_exit"),
            "pnl": scorecard.get("pnl"),
            "exit_reason": scorecard.get("exit_reason"),
            "r_multiple": scorecard.get("r_multiple"),
        },
    }

    answers = jev_client.evaluate(state=state, questions=_build_questions())
    if answers is None:
        return _DEFAULT

    try:
        exec_grade = answers["execution_quality"].score / 3.0
        plan_quality = answers["plan_was_good"].noul
        notable = answers["learned_something"].noul > 0.6

        return {
            "execution_grade": round(exec_grade, 3),
            "plan_quality": round(plan_quality, 3),
            "notable": notable,
        }
    except Exception:
        log.warning("Jev trade grading failed", exc_info=True)
        return _DEFAULT
