from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import anthropic

from tradingbot.executor.candle_aggregator import LiveCandle
from tradingbot.executor.momentum_scorer import SymbolState

logger = logging.getLogger(__name__)

_ENTRY_FALLBACK = "WAIT"
_EXIT_FALLBACK = "HOLD"
_VALID_ENTRY_ACTIONS = {"ENTER", "WAIT", "VETO"}
_VALID_EXIT_ACTIONS = {"EXIT", "HOLD"}


@dataclass(frozen=True)
class EscalationResult:
    action: str
    reasoning: str
    confidence: float
    fallback_used: bool


class LLMEscalator:
    def __init__(self, max_escalations: int = 5, timeout: float = 10.0) -> None:
        self._max = max_escalations
        self._timeout = timeout
        self._count = 0
        self._client: anthropic.Anthropic | None = None

    @property
    def escalation_count(self) -> int:
        return self._count

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    async def evaluate_entry(self, leg, state: SymbolState,
                             candles_1m: list[LiveCandle],
                             candles_5m: list[LiveCandle],
                             ticker_degraded: bool = False) -> EscalationResult:
        if self._count >= self._max:
            return EscalationResult(_ENTRY_FALLBACK, "Max escalations reached", 0.0, True)
        prompt = self._build_entry_prompt(leg, state, candles_1m, candles_5m, ticker_degraded)
        return await self._call(prompt, _VALID_ENTRY_ACTIONS, _ENTRY_FALLBACK)

    async def evaluate_exit(self, leg_state, state: SymbolState,
                            candles_1m: list[LiveCandle],
                            candles_5m: list[LiveCandle]) -> EscalationResult:
        if self._count >= self._max:
            return EscalationResult(_EXIT_FALLBACK, "Max escalations reached", 0.0, True)
        prompt = self._build_exit_prompt(leg_state, state, candles_1m, candles_5m)
        return await self._call(prompt, _VALID_EXIT_ACTIONS, _EXIT_FALLBACK)

    async def _call(self, prompt: str, valid_actions: set[str],
                    fallback: str) -> EscalationResult:
        try:
            client = self._get_client()
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            data = json.loads(text)
            action = data.get("action", "").upper()
            if action not in valid_actions:
                raise ValueError(f"Invalid action: {action}")
            self._count += 1
            return EscalationResult(
                action=action,
                reasoning=data.get("reasoning", ""),
                confidence=float(data.get("confidence", 0.5)),
                fallback_used=False,
            )
        except Exception:
            logger.warning("LLM escalation failed, using fallback", exc_info=True)
            return EscalationResult(fallback, "LLM unavailable", 0.0, True)

    def _build_entry_prompt(self, leg, state: SymbolState,
                            candles_1m: list[LiveCandle],
                            candles_5m: list[LiveCandle],
                            ticker_degraded: bool = False) -> str:
        candles_1m_str = _format_candles(candles_1m[-10:])
        candles_5m_str = _format_candles(candles_5m[-5:])
        degradation_note = ""
        if ticker_degraded:
            degradation_note = "\n\nWARNING: Ticker is degraded (REST LTP only). Candle data may be stale or incomplete. Weight your decision toward caution."
        return f"""You are an execution intelligence for an intraday trading system.{degradation_note}
Make a decision based on live market data. Be decisive — ENTER, WAIT, or VETO. No hedging.

TRADE CONTEXT:
  Symbol: {leg.symbol}, Direction: {leg.direction.value}
  Plan entry: {leg.entry_price}, Stop: {leg.stop_loss}, Targets: {leg.target_1}/{leg.target_2}
  Strategy: {leg.strategy.value}, Confidence: {leg.confidence}
  Reasoning: {leg.reasoning}

LIVE CONDITIONS:
  Momentum 1min: {state.momentum_1m:.1f}, 5min: {state.momentum_5m:.1f}
  Volume ratio: {state.volume_ratio:.2f} ({state.volume_trend})
  VWAP: {state.vwap:.2f}, Position: {state.vwap_position:.2f}
  Pattern 5min: {state.last_pattern_5m}
  Trend alignment: {state.trend_alignment}, Strength: {state.strength}

Last candles (1min): {candles_1m_str}
Last candles (5min): {candles_5m_str}

Should we enter this trade given live conditions?

Respond ONLY with JSON: {{"action": "ENTER|WAIT|VETO", "confidence": 0.0-1.0, "reasoning": "one sentence"}}"""

    def _build_exit_prompt(self, leg_state, state: SymbolState,
                           candles_1m: list[LiveCandle],
                           candles_5m: list[LiveCandle]) -> str:
        candles_1m_str = _format_candles(candles_1m[-10:])
        candles_5m_str = _format_candles(candles_5m[-5:])
        return f"""You are an execution intelligence for an intraday trading system.
Make a decision based on live market data. Be decisive — EXIT or HOLD. No hedging.

POSITION:
  Symbol: {state.symbol}, Direction: {leg_state.leg.direction.value}
  Entry: {leg_state.entry_fill_price}, Current stop: {leg_state.current_stop}

LIVE CONDITIONS:
  Momentum 1min: {state.momentum_1m:.1f}, 5min: {state.momentum_5m:.1f}
  Volume ratio: {state.volume_ratio:.2f} ({state.volume_trend})
  Pattern 5min: {state.last_pattern_5m}
  Trend alignment: {state.trend_alignment}, Strength: {state.strength}

Last candles (1min): {candles_1m_str}
Last candles (5min): {candles_5m_str}

Is this momentum exhaustion or a temporary pullback? Should we exit?

Respond ONLY with JSON: {{"action": "EXIT|HOLD", "confidence": 0.0-1.0, "reasoning": "one sentence"}}"""


def _format_candles(candles: list[LiveCandle]) -> str:
    if not candles:
        return "none"
    rows = []
    for c in candles:
        t = c.timestamp.strftime("%H:%M")
        rows.append(f"{t} O={c.open:.1f} H={c.high:.1f} L={c.low:.1f} C={c.close:.1f} V={c.volume}")
    return " | ".join(rows)
