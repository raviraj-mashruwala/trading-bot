"""News headline screener: Jev-based market-moving event detection."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from tradingbot.core.jev_client import JevClient, Choice, Noul

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class NewsScreenResult:
    market_moving: float
    sentiment: str
    sentiment_confidence: float
    urgent: bool
    headlines_checked: int


_NEUTRAL = NewsScreenResult(
    market_moving=0.0, sentiment="neutral",
    sentiment_confidence=0.0, urgent=False, headlines_checked=0,
)


def _build_questions() -> dict:
    try:
        if Noul is None:
            return {}
    except Exception:
        return {}
    return {
        "market_moving": Noul(
            instructions="Do any of these headlines contain market-moving information?",
            criteria={
                "true": "Material news — rate decisions, earnings beats/misses, policy changes, major corporate events",
                "false": "Routine coverage — market commentary, predictions, opinion pieces",
            },
        ),
        "sentiment_shift": Choice(
            instructions="What is the dominant sentiment shift in these headlines?",
            criteria={
                "bullish": "Positive catalysts — upgrades, earnings beats, policy support, rate cuts",
                "bearish": "Negative catalysts — downgrades, earnings misses, regulatory risk, global selloff",
                "neutral": "No clear directional signal — mixed or routine news",
                "mixed": "Conflicting signals across headlines — some positive, some negative",
            },
        ),
        "urgency": Noul(
            instructions="Do these headlines require immediate trading action (position adjustment)?",
            criteria={
                "true": "Breaking news that could move markets significantly in the next hour",
                "false": "News that can be absorbed gradually — no immediate action needed",
            },
        ),
    }


class NewsScreener:
    """Screen news headlines for trading-relevant signals via Jev."""

    def __init__(self, jev_client: JevClient, check_interval_seconds: int = 60) -> None:
        self._jev = jev_client
        self._interval = check_interval_seconds
        self._last_check: datetime | None = None

    def should_check(self, now: datetime) -> bool:
        if self._last_check is None:
            return True
        return (now - self._last_check).total_seconds() >= self._interval

    def screen(self, headlines: list[dict[str, Any]]) -> NewsScreenResult:
        """Screen a batch of headlines. Returns neutral on empty input or Jev failure."""
        if not headlines:
            return _NEUTRAL

        state = {"headlines": headlines}
        questions = _build_questions()

        answers = self._jev.evaluate(state=state, questions=questions)
        self._last_check = datetime.now()

        if answers is None:
            return NewsScreenResult(
                market_moving=0.0, sentiment="neutral",
                sentiment_confidence=0.0, urgent=False,
                headlines_checked=len(headlines),
            )

        try:
            mm = answers["market_moving"].noul
            sentiment = answers["sentiment_shift"].choice
            sent_conf = answers["sentiment_shift"].confidence
            urg = answers["urgency"].noul

            result = NewsScreenResult(
                market_moving=mm,
                sentiment=sentiment,
                sentiment_confidence=sent_conf,
                urgent=urg > 0.8,
                headlines_checked=len(headlines),
            )

            if result.urgent:
                log.warning(
                    "URGENT NEWS: sentiment=%s (conf=%.2f), market_moving=%.2f",
                    sentiment, sent_conf, mm,
                )
            elif mm > 0.7:
                log.info(
                    "Market-moving news: sentiment=%s, score=%.2f",
                    sentiment, mm,
                )

            return result
        except Exception:
            log.warning("News screening answer parsing failed", exc_info=True)
            return NewsScreenResult(
                market_moving=0.0, sentiment="neutral",
                sentiment_confidence=0.0, urgent=False,
                headlines_checked=len(headlines),
            )
