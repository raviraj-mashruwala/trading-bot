"""Candle-aware exit logic with trailing stops, momentum reversal, and pattern exits."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time
from enum import Enum

from tradingbot.executor.candle_aggregator import LiveCandle
from tradingbot.executor.momentum_scorer import SymbolState

_BEARISH_PATTERNS = {"bearish_engulf", "bearish_marubozu", "evening_star", "shooting_star"}
_BULLISH_PATTERNS = {"bullish_engulf", "bullish_marubozu", "morning_star", "hammer"}


class ExitDecision(Enum):
    HOLD = "hold"
    BOOK_TARGET_1 = "book_target_1"
    BOOK_TARGET_2 = "book_target_2"
    STOP_HIT = "stop_hit"
    SQUARE_OFF = "square_off"
    TRAIL_STOP = "trail_stop"
    MOMENTUM_EXIT = "momentum_exit"
    PATTERN_EXIT = "pattern_exit"


class AdaptiveExitManager:
    """Three-phase trailing stops + momentum reversal + pattern exits.

    Priority order: square-off > stop > T2 > momentum > pattern > T1 > hold.
    Stops only tighten, never widen.
    """

    def __init__(self, square_off_time: time, jev_client=None) -> None:
        self._square_off_time = square_off_time
        self._peak_momentum_high: dict[str, float] = defaultdict(float)
        self._peak_momentum_low: dict[str, float] = defaultdict(float)
        self._jev = jev_client

    def track_peak_momentum(self, symbol: str, momentum_5m: float) -> None:
        """Record high-water marks for momentum exit detection.

        Tracks max positive and min negative separately so a violent
        reversal (-60) cannot clobber a prior bullish peak (+55).
        """
        if momentum_5m > 0:
            self._peak_momentum_high[symbol] = max(
                self._peak_momentum_high.get(symbol, 0.0), momentum_5m)
        if momentum_5m < 0:
            self._peak_momentum_low[symbol] = min(
                self._peak_momentum_low.get(symbol, 0.0), momentum_5m)

    def decide(self, state, symbol_state: SymbolState,
               price: float, now: datetime, *,
               candles_5m: list[LiveCandle] | None = None,
               candles_1m: list[LiveCandle] | None = None) -> ExitDecision:
        """Evaluate exit priority chain, return highest-priority signal."""
        now_time = now.time() if isinstance(now, datetime) else now
        direction = state.leg.direction.value
        is_long = direction == "long"

        # P1: square-off — sacred, never overridden
        if now_time >= self._square_off_time:
            return ExitDecision.SQUARE_OFF

        # P2: stop loss
        if is_long and price <= state.current_stop:
            return ExitDecision.STOP_HIT
        if not is_long and price >= state.current_stop:
            return ExitDecision.STOP_HIT

        # P3: target 2
        t1 = getattr(state, "effective_target_1", state.leg.target_1)
        t2 = getattr(state, "effective_target_2", state.leg.target_2)
        if state.target_1_booked:
            if is_long and t2 > 0 and price >= t2:
                return ExitDecision.BOOK_TARGET_2
            if not is_long and t2 > 0 and price <= t2:
                return ExitDecision.BOOK_TARGET_2

        # P4: momentum reversal exit
        if self._check_momentum_exit(state, symbol_state, price, is_long):
            return ExitDecision.MOMENTUM_EXIT

        # P5: pattern exit
        if self._check_pattern_exit(state, symbol_state, price, is_long):
            return ExitDecision.PATTERN_EXIT

        # P6: target 1
        if not state.target_1_booked:
            if is_long and price >= t1:
                return ExitDecision.BOOK_TARGET_1
            if not is_long and price <= t1:
                return ExitDecision.BOOK_TARGET_1

        # P7: trailing stop tightened
        if state.target_1_booked and candles_5m is not None:
            trail = self.compute_trail_price(
                state, symbol_state, candles_5m or [], candles_1m or [])
            if trail is not None and trail != state.current_stop:
                if is_long and trail > state.current_stop:
                    return ExitDecision.TRAIL_STOP
                if not is_long and trail < state.current_stop:
                    return ExitDecision.TRAIL_STOP

        return ExitDecision.HOLD

    def compute_trail_price(self, state, symbol_state: SymbolState,
                            candles_5m: list[LiveCandle],
                            candles_1m: list[LiveCandle]) -> float | None:
        """Compute trailing stop price using three-phase logic.

        Phase 1 (pre-T1): no trail — returns None.
        Phase 2 (post-T1): min low of last 3 x 5min candles, floor = breakeven.
        Phase 3 (near T2): last 2 x 1min candles, tighter trail.
        Invariant: trail never widens (never below current_stop for longs).
        """
        is_long = state.leg.direction.value == "long"
        breakeven = state.entry_fill_price

        # Phase 1: pre-T1 — no trailing
        if not state.target_1_booked:
            return None

        # Phase 3: near target_2 — tight 1min trail
        t2 = state.leg.target_2
        last_price = candles_1m[-1].close if candles_1m else None
        if last_price is not None:
            distance_pct = abs(last_price - t2) / t2 * 100 if t2 else 999
            if distance_pct < 0.3 and len(candles_1m) >= 2:
                if is_long:
                    trail = min(c.low for c in candles_1m[-2:])
                else:
                    trail = max(c.high for c in candles_1m[-2:])
                floor = max(trail, breakeven) if is_long else min(trail, breakeven)
                return max(floor, state.current_stop) if is_long else min(floor, state.current_stop)

        # Phase 2: post-T1, riding to T2 — 5min low trail
        if candles_5m and len(candles_5m) >= 3:
            if is_long:
                trail = min(c.low for c in candles_5m[-3:])
                floor = max(trail, breakeven)
                candle_trail = max(floor, state.current_stop)
            else:
                trail = max(c.high for c in candles_5m[-3:])
                floor = min(trail, breakeven)
                candle_trail = min(floor, state.current_stop)

            current_price = candles_5m[-1].close if candles_5m else candle_trail
            candle_trail = self._jev_tighten(candle_trail, state, symbol_state, current_price, is_long)
            return candle_trail

        return state.current_stop

    def _jev_tighten(self, candle_trail: float, state, symbol_state: SymbolState,
                     price: float, is_long: bool) -> float:
        """Ask Jev if trail should be tighter than candle geometry suggests."""
        if self._jev is None:
            return candle_trail
        try:
            from tradingbot.core.jev_client import Noul
            answers = self._jev.evaluate(
                state={
                    "symbol": symbol_state.symbol,
                    "direction": "long" if is_long else "short",
                    "price": price,
                    "candle_trail": candle_trail,
                    "current_stop": state.current_stop,
                    "entry_price": state.entry_fill_price,
                    "momentum_1m": symbol_state.momentum_1m,
                    "momentum_5m": symbol_state.momentum_5m,
                    "volume_ratio": symbol_state.volume_ratio,
                    "trend_alignment": symbol_state.trend_alignment,
                },
                questions={
                    "should_tighten": Noul(
                        instructions="Should the trailing stop be tighter than the candle-based level?",
                        criteria={
                            "true": "Non-price signals (volume divergence, momentum decay, regime shift) suggest risk is elevated — tighten",
                            "false": "Candle-based trail is appropriate for current conditions",
                        },
                    ),
                },
            )
            if answers and answers["should_tighten"].noul > 0.7:
                midpoint = (candle_trail + price) / 2
                if is_long:
                    return max(midpoint, candle_trail)
                else:
                    return min(midpoint, candle_trail)
        except Exception:
            pass
        return candle_trail

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _check_momentum_exit(self, state, ss: SymbolState,
                             price: float, is_long: bool) -> bool:
        """Momentum reversal: profitable + peak momentum decayed significantly."""
        symbol = ss.symbol
        profitable = (price > state.entry_fill_price) if is_long else (price < state.entry_fill_price)
        if not profitable:
            return False

        if is_long:
            peak = self._peak_momentum_high.get(symbol, 0.0)
            decay = (peak - ss.momentum_5m) / peak if peak > 10 else 0
        else:
            peak = self._peak_momentum_low.get(symbol, 0.0)
            decay = (ss.momentum_5m - peak) / abs(peak) if peak < -10 else 0

        if self._jev is not None and decay > 0.5:
            try:
                from tradingbot.core.jev_client import Noul
                answers = self._jev.evaluate(
                    state={
                        "symbol": symbol,
                        "direction": "long" if is_long else "short",
                        "momentum_1m": ss.momentum_1m,
                        "momentum_5m": ss.momentum_5m,
                        "peak_momentum": peak,
                        "decay_pct": decay,
                        "volume_ratio": ss.volume_ratio,
                        "vwap_position": ss.vwap_position,
                    },
                    questions={
                        "exhausted": Noul(
                            instructions="Is the momentum that drove this trade exhausted?",
                            criteria={
                                "true": "Peak momentum has decayed significantly, trend losing steam",
                                "false": "Momentum is pausing but trend structure is intact",
                            },
                        ),
                    },
                )
                if answers and answers["exhausted"].noul > 0.7:
                    return True
            except Exception:
                pass

        # Hardcoded fallback
        if is_long:
            return (peak > 40 and ss.momentum_5m < -20
                    and ss.momentum_1m < -40 and ss.volume_ratio > 1.0)
        return (peak < -40 and ss.momentum_5m > 20
                and ss.momentum_1m > 40 and ss.volume_ratio > 1.0)

    def _check_pattern_exit(self, state, ss: SymbolState,
                            price: float, is_long: bool) -> bool:
        """Pattern exit: profitable + adverse pattern on 5m + volume >1.5."""
        profitable = (price > state.entry_fill_price) if is_long else (price < state.entry_fill_price)
        if not profitable:
            return False
        if ss.volume_ratio < 1.5:
            return False
        if is_long and ss.last_pattern_5m in _BEARISH_PATTERNS:
            return True
        if not is_long and ss.last_pattern_5m in _BULLISH_PATTERNS:
            return True
        return False
