"""Jev-based escalator: drop-in replacement for LLMEscalator."""

from __future__ import annotations

import logging
from typing import Any

from tradingbot.core.config import JevConfig
from tradingbot.core.jev_client import JevClient, Choice, Noul, Score
from tradingbot.executor.candle_aggregator import LiveCandle
from tradingbot.executor.llm_escalator import EscalationResult, LLMEscalator
from tradingbot.executor.momentum_scorer import SymbolState

log = logging.getLogger(__name__)

_ENTRY_FALLBACK = EscalationResult("WAIT", "all_escalators_unavailable", 0.0, True)
_EXIT_FALLBACK = EscalationResult("HOLD", "all_escalators_unavailable", 0.0, True)


def _build_entry_questions() -> dict[str, Any]:
    if Noul is None:
        return {}
    return {
        "should_enter": Noul(
            instructions="Should this trade be entered based on the live price action?",
            criteria={
                "true": "Momentum, volume, and price action confirm the setup thesis — enter",
                "false": "Price action contradicts or weakens the setup — wait or skip",
            },
        ),
        "invalidated": Noul(
            instructions="Has the original trade setup been invalidated by current price action?",
            criteria={
                "true": "Key levels broken, pattern failed, or thesis no longer holds",
                "false": "Setup thesis still intact despite current conditions",
            },
        ),
        "timing": Choice(
            instructions="What is the best action right now?",
            criteria={
                "enter_now": "Conditions are favorable — execute immediately",
                "wait_5min": "Close but not quite — reassess shortly",
                "skip": "Setup is no longer valid — do not enter today",
            },
        ),
    }


def _build_exit_questions() -> dict[str, Any]:
    if Noul is None:
        return {}
    return {
        "exit_now": Noul(
            instructions="Should this position be closed immediately?",
            criteria={
                "true": "Momentum exhausted, reversal signals, or risk elevated — close now",
                "false": "Position still has favorable momentum — hold",
            },
        ),
        "momentum_exhaustion": Noul(
            instructions="Is the momentum that drove this trade showing signs of exhaustion?",
        ),
        "reversal_risk": Score(
            instructions="How likely is a reversal against this position in the next 30 minutes?",
            criteria=[
                "Very unlikely — strong trend continuation signals",
                "Unlikely — some noise but trend intact",
                "Possible — mixed signals, caution warranted",
                "Likely — multiple reversal signals forming",
                "Very likely — clear reversal pattern underway",
            ],
        ),
    }


def _state_from_entry(leg: Any, state: SymbolState, candles_5m: list[LiveCandle]) -> dict:
    return {
        "setup": {
            "symbol": leg.symbol,
            "direction": leg.direction.value,
            "strategy": leg.strategy.value,
            "entry_price": leg.entry_price,
            "stop_loss": leg.stop_loss,
            "target_1": leg.target_1,
        },
        "live": {
            "momentum_1m": state.momentum_1m,
            "momentum_5m": state.momentum_5m,
            "volume_ratio": state.volume_ratio,
            "vwap_position": state.vwap_position,
            "trend_alignment": state.trend_alignment,
            "strength": state.strength,
            "body_dominance": state.body_dominance,
            "last_pattern_1m": state.last_pattern_1m,
            "last_pattern_5m": state.last_pattern_5m,
        },
        "candles_5m": [
            {"o": c.open, "h": c.high, "l": c.low, "c": c.close, "v": c.volume}
            for c in candles_5m[-6:]
        ],
    }


def _state_from_exit(leg_state: Any, state: SymbolState, candles_5m: list[LiveCandle]) -> dict:
    return {
        "position": {
            "symbol": state.symbol,
            "momentum_1m": state.momentum_1m,
            "momentum_5m": state.momentum_5m,
            "volume_ratio": state.volume_ratio,
            "vwap_position": state.vwap_position,
            "trend_alignment": state.trend_alignment,
            "strength": state.strength,
        },
        "candles_5m": [
            {"o": c.open, "h": c.high, "l": c.low, "c": c.close, "v": c.volume}
            for c in candles_5m[-6:]
        ],
    }


def _format_entry_reasoning(answers: dict) -> str:
    se = answers["should_enter"].noul
    inv = answers["invalidated"].noul
    tm = answers["timing"].choice
    tc = answers["timing"].confidence
    return f"jev: should_enter={se:.2f}, timing={tm}(conf={tc:.2f}), invalidated={inv:.2f}"


def _format_exit_reasoning(answers: dict) -> str:
    ex = answers["exit_now"].noul
    me = answers["momentum_exhaustion"].noul
    rr = answers["reversal_risk"].score
    return f"jev: exit_now={ex:.2f}, exhaustion={me:.2f}, reversal_risk={rr:.2f}"


class JevEscalator:
    """Drop-in replacement for LLMEscalator using TypeSafe Jev."""

    def __init__(
        self,
        jev_client: JevClient,
        config: JevConfig,
        llm_fallback: LLMEscalator | None = None,
    ) -> None:
        self._jev = jev_client
        self._config = config
        self._fallback = llm_fallback
        self._call_count = 0

    @property
    def escalation_count(self) -> int:
        return self._call_count

    async def evaluate_entry(
        self,
        leg: Any,
        state: SymbolState,
        candles_1m: list[LiveCandle],
        candles_5m: list[LiveCandle],
        ticker_degraded: bool = False,
    ) -> EscalationResult:
        answers = await self._jev.aevaluate(
            state=_state_from_entry(leg, state, candles_5m),
            questions=_build_entry_questions(),
        )

        if answers is None:
            return await self._entry_fallback(leg, state, candles_1m, candles_5m, ticker_degraded)

        self._call_count += 1
        reasoning = _format_entry_reasoning(answers)

        if answers["invalidated"].noul > 0.7:
            return EscalationResult("SKIP", reasoning, answers["invalidated"].noul, False)

        if answers["timing"].choice == "skip":
            return EscalationResult("SKIP", reasoning, answers["timing"].confidence, False)

        se = answers["should_enter"].noul
        if se >= self._config.entry_confidence_threshold:
            return EscalationResult("ENTER", reasoning, se, False)

        if se < self._config.uncertainty_threshold:
            log.info("Jev uncertain (%.2f < %.2f), trying Claude fallback",
                     se, self._config.uncertainty_threshold)
            return await self._entry_fallback(leg, state, candles_1m, candles_5m, ticker_degraded)

        return EscalationResult("WAIT", reasoning, se, False)

    async def evaluate_exit(
        self,
        leg_state: Any,
        state: SymbolState,
        candles_1m: list[LiveCandle],
        candles_5m: list[LiveCandle],
    ) -> EscalationResult:
        answers = await self._jev.aevaluate(
            state=_state_from_exit(leg_state, state, candles_5m),
            questions=_build_exit_questions(),
        )

        if answers is None:
            return await self._exit_fallback(leg_state, state, candles_1m, candles_5m)

        self._call_count += 1
        reasoning = _format_exit_reasoning(answers)

        ex = answers["exit_now"].noul
        if ex >= self._config.exit_confidence_threshold:
            return EscalationResult("EXIT", reasoning, ex, False)

        reversal_norm = answers["reversal_risk"].score / 4.0
        exhaustion = answers["momentum_exhaustion"].noul
        if reversal_norm > 0.7 and exhaustion > 0.6:
            return EscalationResult("HOLD", f"{reasoning}; tighten_stop", reversal_norm, False)

        if ex < self._config.uncertainty_threshold:
            log.info("Jev exit uncertain (%.2f), trying Claude fallback", ex)
            return await self._exit_fallback(leg_state, state, candles_1m, candles_5m)

        return EscalationResult("HOLD", reasoning, 1.0 - ex, False)

    async def _entry_fallback(self, leg, state, candles_1m, candles_5m, ticker_degraded):
        if self._fallback is None:
            return _ENTRY_FALLBACK
        try:
            return await self._fallback.evaluate_entry(
                leg, state, candles_1m, candles_5m, ticker_degraded,
            )
        except Exception:
            log.warning("Claude entry fallback also failed", exc_info=True)
            return _ENTRY_FALLBACK

    async def _exit_fallback(self, leg_state, state, candles_1m, candles_5m):
        if self._fallback is None:
            return _EXIT_FALLBACK
        try:
            return await self._fallback.evaluate_exit(
                leg_state, state, candles_1m, candles_5m,
            )
        except Exception:
            log.warning("Claude exit fallback also failed", exc_info=True)
            return _EXIT_FALLBACK
