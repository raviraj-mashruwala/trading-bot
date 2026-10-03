"""Live regime monitor: Jev-based regime check during market hours."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from tradingbot.core.jev_client import JevClient, Choice, Noul

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegimeCheckResult:
    changed: bool
    new_regime: str | None
    confidence: float


_NO_CHANGE = RegimeCheckResult(changed=False, new_regime=None, confidence=0.0)


class RegimeMonitor:
    """Check for intraday regime shifts via Jev every N seconds."""

    def __init__(self, jev_client: JevClient, check_interval_seconds: int = 300) -> None:
        self._jev = jev_client
        self._interval = check_interval_seconds
        self._last_check: datetime | None = None

    def should_check(self, now: datetime) -> bool:
        if self._last_check is None:
            return True
        return (now - self._last_check).total_seconds() >= self._interval

    def check(self, market_data: dict[str, Any], current_regime: str) -> RegimeCheckResult:
        questions = _build_regime_check_questions(current_regime)

        answers = self._jev.evaluate(state=market_data, questions=questions)
        self._last_check = datetime.now()

        if answers is None:
            return _NO_CHANGE

        try:
            changed_prob = answers["regime_changed"].noul
            new_regime = answers["new_regime"].choice
            confidence = answers["new_regime"].confidence

            if changed_prob > 0.7 and confidence > 0.5:
                log.warning(
                    "Regime shift detected: %s → %s (change_prob=%.2f, conf=%.2f)",
                    current_regime, new_regime, changed_prob, confidence,
                )
                return RegimeCheckResult(changed=True, new_regime=new_regime, confidence=confidence)

            return _NO_CHANGE
        except Exception:
            log.warning("Regime monitor answer parsing failed", exc_info=True)
            return _NO_CHANGE


def _build_regime_check_questions(current_regime: str) -> dict:
    try:
        if Choice is None:
            return {}
    except Exception:
        return {}
    return {
        "regime_changed": Noul(
            instructions=f"Has the market regime changed from `{current_regime}`?",
            criteria={
                "true": "Significant shift in market conditions since morning",
                "false": "Conditions consistent with the morning regime",
            },
        ),
        "new_regime": Choice(
            instructions="What is the current market regime?",
            criteria={
                "trending_up": "Broad uptrend",
                "trending_down": "Broad downtrend",
                "range_bound": "Sideways, no conviction",
                "volatile": "High volatility, sharp swings",
                "low_vol_squeeze": "Compressed volatility, breakout imminent",
            },
        ),
    }
