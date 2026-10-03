"""Jev-based shortlist pre-scorer: rank candidates before Claude shortlist."""

from __future__ import annotations

import logging
from typing import Any

from tradingbot.core.jev_client import JevClient, Noul, Score

log = logging.getLogger(__name__)


def _build_questions() -> dict:
    try:
        if Score is None:
            return {}
    except Exception:
        return {}
    return {
        "setup_quality": Score(
            instructions="How promising is this stock as an intraday trade setup today?",
            criteria=[
                "Poor — no clear edge, conflicting signals",
                "Below average — some signals but weak conviction",
                "Decent — tradeable setup with moderate conviction",
                "Good — clear setup with multiple confirming signals",
                "Excellent — textbook setup with strong confluence",
            ],
        ),
        "regime_alignment": Noul(
            instructions="Does this stock's setup align with the current market regime?",
        ),
        "risk_reward_attractive": Noul(
            instructions=(
                "Based on the technical levels, does this stock offer "
                "an attractive risk:reward ratio (at least 2:1)?"
            ),
        ),
        "volume_conviction": Noul(
            instructions="Does volume data suggest institutional participation or accumulation?",
        ),
    }


def score_candidates(
    jev_client: JevClient,
    candidates: list[dict[str, Any]],
    regime: str,
    min_confidence: float = 0.0,
) -> list[dict[str, Any]]:
    """Score and rank candidates via Jev. Returns candidates with jev_composite added."""
    questions = _build_questions()
    scored = []

    for stock in candidates:
        state = {
            "stock": {
                "symbol": stock.get("symbol"),
                "composite_score": stock.get("composite_score"),
                "sector": stock.get("sector"),
                "last_price": stock.get("last_price"),
                "factor_scores": stock.get("factor_scores", {}),
            },
            "market_regime": regime,
        }

        answers = jev_client.evaluate(state=state, questions=questions)
        if answers is None:
            scored.append({**stock, "jev_composite": 0.0, "jev_setup_confidence": 0.0})
            continue

        try:
            quality = answers["setup_quality"].score / 4.0
            quality_conf = answers["setup_quality"].confidence
            alignment = answers["regime_alignment"].noul
            rr = answers["risk_reward_attractive"].noul
            volume = answers["volume_conviction"].noul

            composite = (
                0.35 * quality
                + 0.25 * alignment
                + 0.25 * rr
                + 0.15 * volume
            )

            scored.append({
                **stock,
                "jev_composite": round(composite, 4),
                "jev_setup_confidence": round(quality_conf, 4),
            })
        except Exception:
            log.warning("Jev scoring failed for %s", stock.get("symbol"), exc_info=True)
            scored.append({**stock, "jev_composite": 0.0, "jev_setup_confidence": 0.0})

    if min_confidence > 0:
        scored = [s for s in scored if s["jev_setup_confidence"] >= min_confidence]

    scored.sort(key=lambda s: s["jev_composite"], reverse=True)
    return scored
