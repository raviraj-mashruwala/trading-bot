from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time

from tradingbot.executor.momentum_scorer import SymbolState

_BEARISH_PATTERNS = {"bearish_engulf", "bearish_marubozu", "evening_star", "shooting_star"}
_BULLISH_PATTERNS = {"bullish_engulf", "bullish_marubozu", "morning_star", "hammer"}

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EntryVerdict:
    action: str
    reason: str
    confidence: float
    reassess_after: int


class EntryGuard:
    def __init__(self, max_drift_pct: float, jev_client=None) -> None:
        self._max_drift_pct = max_drift_pct
        self._jev = jev_client

    def evaluate(self, leg, state: SymbolState, current_price: float,
                 now: datetime) -> EntryVerdict:
        direction = leg.direction.value
        now_time = now.time() if isinstance(now, datetime) else now

        # Rule 1: entry window expired
        if now_time > leg.entry_window_end:
            return EntryVerdict("VETO", "Entry window expired", 1.0, 0)

        # Rule 1b: max entry wait expired
        if now_time > leg.max_entry_wait:
            return EntryVerdict("VETO", "Max entry wait expired", 1.0, 0)

        # Rule 2: price drift
        drift_pct = abs(current_price - leg.entry_price) / leg.entry_price * 100
        if drift_pct > self._max_drift_pct:
            return EntryVerdict("VETO", f"Price drift {drift_pct:.1f}% exceeds {self._max_drift_pct}%", 1.0, 0)

        # Rule 3: LONG into strong selling
        if direction == "long" and state.momentum_5m < -60:
            return EntryVerdict("VETO", f"Strong 5m selling (momentum {state.momentum_5m:.0f})", 0.9, 0)

        # Rule 4: SHORT into strong buying
        if direction == "short" and state.momentum_5m > 60:
            return EntryVerdict("VETO", f"Strong 5m buying (momentum {state.momentum_5m:.0f})", 0.9, 0)

        # Rule 5: low volume
        if state.volume_ratio < 0.3:
            return EntryVerdict("WAIT", "Volume too low, no liquidity", 0.7, 60)

        # Rule 6: choppy, no alignment
        if not state.trend_alignment and state.body_dominance < 0.3:
            return EntryVerdict("WAIT", "Choppy, conflicting signals", 0.6, 60)

        # Rule 7: LONG falling below VWAP
        if direction == "long" and state.vwap_position < -0.8 and state.momentum_1m < -30:
            return EntryVerdict("WAIT", "Price falling below VWAP", 0.5, 60)

        # Rule 7b: SHORT rising above VWAP
        if direction == "short" and state.vwap_position > 0.8 and state.momentum_1m > 30:
            return EntryVerdict("WAIT", "Price rising above VWAP", 0.5, 60)

        # Rule 8: adverse candle pattern
        if direction == "long" and state.last_pattern_5m in _BEARISH_PATTERNS:
            return EntryVerdict("WAIT", f"Bearish 5m pattern: {state.last_pattern_5m}", 0.5, 60)
        if direction == "short" and state.last_pattern_5m in _BULLISH_PATTERNS:
            return EntryVerdict("WAIT", f"Bullish 5m pattern: {state.last_pattern_5m}", 0.5, 60)

        # Rule 10: clean setup — momentum aligned + volume adequate
        aligned_momentum = (
            (direction == "long" and state.momentum_1m > 20 and state.momentum_5m > 15)
            or (direction == "short" and state.momentum_1m < -20 and state.momentum_5m < -15)
        )
        if aligned_momentum and state.volume_ratio > 0.7 and state.trend_alignment:
            verdict = EntryVerdict("ENTER", "Momentum aligned, volume adequate", 0.8, 0)
            return self._jev_validate(leg, state, verdict)

        # Rule 9: gray zone — nothing disqualifying but nothing strong
        confidence = 0.2 + min(0.1, state.volume_ratio * 0.05) + min(0.09, state.body_dominance * 0.05)
        verdict = EntryVerdict("ENTER", "No disqualifying signal, marginal conditions", confidence, 0)
        return self._jev_enrich_gray_zone(leg, state, verdict)

    def _jev_validate(self, leg, state: SymbolState, verdict: EntryVerdict) -> EntryVerdict:
        jev_result = self._jev_evaluate(leg, state)
        if jev_result is None:
            return verdict

        if jev_result["fading_risk"] > 0.65:
            return EntryVerdict("WAIT", "jev_fading_risk", 0.5, 30)
        if jev_result["momentum_quality"] < 0.25:
            return EntryVerdict("WAIT", "jev_low_momentum_quality", 0.45, 60)

        boosted = min(0.95, verdict.confidence + jev_result["momentum_quality"] * 0.15)
        return EntryVerdict(verdict.action, verdict.reason, boosted, verdict.reassess_after)

    def _jev_enrich_gray_zone(self, leg, state: SymbolState, verdict: EntryVerdict) -> EntryVerdict:
        jev_result = self._jev_evaluate(leg, state)
        if jev_result is None:
            return verdict

        enriched = 0.3 * jev_result["enter_now"] + 0.2 * jev_result["momentum_quality"]
        return EntryVerdict(verdict.action, verdict.reason, enriched, verdict.reassess_after)

    def _jev_evaluate(self, leg, state: SymbolState) -> dict | None:
        if self._jev is None or not self._jev.available:
            return None
        try:
            questions = self._build_jev_questions()
            answers = self._jev.evaluate(
                state={
                    "direction": leg.direction.value,
                    "momentum_1m": state.momentum_1m,
                    "momentum_5m": state.momentum_5m,
                    "volume_ratio": state.volume_ratio,
                    "vwap_position": state.vwap_position,
                    "trend_alignment": state.trend_alignment,
                    "strength": state.strength,
                    "body_dominance": state.body_dominance,
                },
                questions=questions,
            )
            if answers is None:
                return None
            return {
                "enter_now": answers["enter_now"].noul,
                "momentum_quality": answers["momentum_quality"].score / 4.0,
                "fading_risk": answers["fading_risk"].noul,
            }
        except Exception:
            log.warning("Jev entry validation failed", exc_info=True)
            return None

    @staticmethod
    def _build_jev_questions() -> dict:
        try:
            from tradingbot.core.jev_client import Noul, Score
            if Noul is None:
                return {}
            return {
                "enter_now": Noul(
                    instructions=(
                        "Given the live momentum data, should this trade be entered NOW? "
                        "Consider direction alignment, momentum strength, volume, and VWAP."
                    ),
                    criteria={
                        "true": "Momentum, volume, and price action support immediate entry",
                        "false": "Conditions are unfavorable — wait or skip",
                    },
                ),
                "momentum_quality": Score(
                    instructions="How favorable is current momentum for this trade direction?",
                    criteria=[
                        "Hostile — momentum strongly against trade direction",
                        "Unfavorable — weak or conflicting momentum",
                        "Neutral — no strong momentum either way",
                        "Favorable — momentum aligns with trade direction",
                        "Ideal — strong, clean momentum with volume confirmation",
                    ],
                ),
                "fading_risk": Noul(
                    instructions="Is there a risk that the move has already played out (late entry)?",
                ),
            }
        except Exception:
            return {}
