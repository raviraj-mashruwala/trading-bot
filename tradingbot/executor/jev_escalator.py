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
_EXIT_FALLBACK = EscalationResult("EXIT", "all_escalators_unavailable — exiting for safety", 0.0, True)


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


def _compute_indicators(candles_1m: list[LiveCandle], candles_5m: list[LiveCandle]) -> dict:
    """Compute technical indicators for Jev context."""
    indicators: dict[str, Any] = {}
    if not candles_1m:
        return indicators

    closes = [c.close for c in candles_1m]

    # RSI(14)
    if len(closes) >= 15:
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [max(d, 0) for d in deltas]
        losses = [max(-d, 0) for d in deltas]
        ag = sum(gains[:14]) / 14
        al = sum(losses[:14]) / 14
        for i in range(14, len(gains)):
            ag = (ag * 13 + gains[i]) / 14
            al = (al * 13 + losses[i]) / 14
        indicators["rsi_14"] = round(100 - 100 / (1 + ag / al), 1) if al else 100.0

    # BB position (0=lower, 0.5=mid, 1=upper)
    if len(closes) >= 20:
        sma20 = sum(closes[-20:]) / 20
        std = (sum((c - sma20) ** 2 for c in closes[-20:]) / 20) ** 0.5
        if std > 0:
            bb_upper = sma20 + 2 * std
            bb_lower = sma20 - 2 * std
            indicators["bb_position"] = round((closes[-1] - bb_lower) / (bb_upper - bb_lower), 3)

    # ATR(14)
    if len(candles_1m) >= 2:
        trs = []
        for i in range(1, min(15, len(candles_1m))):
            c = candles_1m[i]
            prev_close = candles_1m[i - 1].close
            trs.append(max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close)))
        if trs:
            indicators["atr_1m"] = round(sum(trs) / len(trs), 2)

    # Candle trend: ratio of green vs red in last 5 candles (-1 to 1)
    recent = candles_1m[-5:]
    if recent:
        green = sum(1 for c in recent if c.close >= c.open)
        indicators["candle_trend_1m"] = round((2 * green / len(recent)) - 1, 2)

    # Volume surge: latest vol / avg of last 20
    vols = [c.volume for c in candles_1m[-20:]]
    if len(vols) >= 2 and sum(vols[:-1]) > 0:
        avg_vol = sum(vols[:-1]) / len(vols[:-1])
        indicators["volume_surge"] = round(vols[-1] / avg_vol, 2) if avg_vol > 0 else 1.0

    return indicators


def _state_from_entry(leg: Any, state: SymbolState, candles_1m: list[LiveCandle], candles_5m: list[LiveCandle]) -> dict:
    live = {
        "momentum_1m": state.momentum_1m,
        "momentum_5m": state.momentum_5m,
        "volume_ratio": state.volume_ratio,
        "vwap_position": state.vwap_position,
        "trend_alignment": state.trend_alignment,
        "strength": state.strength,
        "body_dominance": state.body_dominance,
        "last_pattern_1m": state.last_pattern_1m,
        "last_pattern_5m": state.last_pattern_5m,
    }
    live.update(_compute_indicators(candles_1m, candles_5m))
    return {
        "setup": {
            "symbol": leg.symbol,
            "direction": leg.direction.value,
            "strategy": leg.strategy.value,
            "entry_price": leg.entry_price,
            "stop_loss": leg.stop_loss,
            "target_1": leg.target_1,
        },
        "live": live,
        "candles_5m": [
            {"o": c.open, "h": c.high, "l": c.low, "c": c.close, "v": c.volume}
            for c in candles_5m[-6:]
        ],
    }


def _state_from_exit(leg_state: Any, state: SymbolState, candles_1m: list[LiveCandle], candles_5m: list[LiveCandle]) -> dict:
    leg = getattr(leg_state, "leg", None)
    position = {
        "symbol": state.symbol,
        "direction": getattr(getattr(leg, "direction", None), "value", "unknown"),
        "entry_price": getattr(leg_state, "entry_fill_price", None),
        "current_stop": getattr(leg_state, "current_stop", None),
        "momentum_1m": state.momentum_1m,
        "momentum_5m": state.momentum_5m,
        "volume_ratio": state.volume_ratio,
        "vwap_position": state.vwap_position,
        "trend_alignment": state.trend_alignment,
        "strength": state.strength,
    }
    position.update(_compute_indicators(candles_1m, candles_5m))
    return {
        "position": position,
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
            state=_state_from_entry(leg, state, candles_1m, candles_5m),
            questions=_build_entry_questions(),
        )

        if answers is None:
            return await self._entry_fallback(leg, state, candles_1m, candles_5m, ticker_degraded)

        try:
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
        except Exception:
            log.warning("Jev entry answer parsing failed, using fallback", exc_info=True)
            return await self._entry_fallback(leg, state, candles_1m, candles_5m, ticker_degraded)

    async def evaluate_exit(
        self,
        leg_state: Any,
        state: SymbolState,
        candles_1m: list[LiveCandle],
        candles_5m: list[LiveCandle],
    ) -> EscalationResult:
        answers = await self._jev.aevaluate(
            state=_state_from_exit(leg_state, state, candles_1m, candles_5m),
            questions=_build_exit_questions(),
        )

        if answers is None:
            return await self._exit_fallback(leg_state, state, candles_1m, candles_5m)

        try:
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
        except Exception:
            log.warning("Jev exit answer parsing failed, using fallback", exc_info=True)
            return await self._exit_fallback(leg_state, state, candles_1m, candles_5m)

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
