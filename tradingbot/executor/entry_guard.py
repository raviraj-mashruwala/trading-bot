from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from tradingbot.executor.momentum_scorer import SymbolState

_BEARISH_PATTERNS = {"bearish_engulf", "bearish_marubozu", "evening_star", "shooting_star"}
_BULLISH_PATTERNS = {"bullish_engulf", "bullish_marubozu", "morning_star", "hammer"}


@dataclass(frozen=True)
class EntryVerdict:
    action: str
    reason: str
    confidence: float
    reassess_after: int


class EntryGuard:
    def __init__(self, max_drift_pct: float) -> None:
        self._max_drift_pct = max_drift_pct

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
        if direction == "LONG" and state.momentum_5m < -60:
            return EntryVerdict("VETO", f"Strong 5m selling (momentum {state.momentum_5m:.0f})", 0.9, 0)

        # Rule 4: SHORT into strong buying
        if direction == "SHORT" and state.momentum_5m > 60:
            return EntryVerdict("VETO", f"Strong 5m buying (momentum {state.momentum_5m:.0f})", 0.9, 0)

        # Rule 5: low volume
        if state.volume_ratio < 0.3:
            return EntryVerdict("WAIT", "Volume too low, no liquidity", 0.7, 60)

        # Rule 6: choppy, no alignment
        if not state.trend_alignment and state.body_dominance < 0.3:
            return EntryVerdict("WAIT", "Choppy, conflicting signals", 0.6, 60)

        # Rule 7: LONG falling below VWAP
        if direction == "LONG" and state.vwap_position < -0.8 and state.momentum_1m < -30:
            return EntryVerdict("WAIT", "Price falling below VWAP", 0.5, 60)

        # Rule 7b: SHORT rising above VWAP
        if direction == "SHORT" and state.vwap_position > 0.8 and state.momentum_1m > 30:
            return EntryVerdict("WAIT", "Price rising above VWAP", 0.5, 60)

        # Rule 8: adverse candle pattern
        if direction == "LONG" and state.last_pattern_5m in _BEARISH_PATTERNS:
            return EntryVerdict("WAIT", f"Bearish 5m pattern: {state.last_pattern_5m}", 0.5, 60)
        if direction == "SHORT" and state.last_pattern_5m in _BULLISH_PATTERNS:
            return EntryVerdict("WAIT", f"Bullish 5m pattern: {state.last_pattern_5m}", 0.5, 60)

        # Rule 10: clean setup — momentum aligned + volume adequate
        aligned_momentum = (
            (direction == "LONG" and state.momentum_1m > 20 and state.momentum_5m > 15)
            or (direction == "SHORT" and state.momentum_1m < -20 and state.momentum_5m < -15)
        )
        if aligned_momentum and state.volume_ratio > 0.7 and state.trend_alignment:
            return EntryVerdict("ENTER", "Momentum aligned, volume adequate", 0.8, 0)

        # Rule 9: gray zone — nothing disqualifying but nothing strong
        confidence = 0.3 + min(0.2, state.volume_ratio * 0.1) + min(0.1, state.body_dominance * 0.1)
        return EntryVerdict("ENTER", "No disqualifying signal, marginal conditions", confidence, 0)
