from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from tradingbot.executor.candle_aggregator import LiveCandle
from tradingbot.executor.candle_patterns import detect_pattern


@dataclass(frozen=True)
class SymbolState:
    symbol: str
    timestamp: datetime
    momentum_1m: float
    momentum_5m: float
    volume_ratio: float
    volume_trend: str
    vwap: float
    vwap_position: float
    price_vs_open: float
    last_pattern_1m: str
    last_pattern_5m: str
    body_dominance: float
    trend_alignment: bool
    strength: str


class MomentumScorer:
    def __init__(self) -> None:
        self._states: dict[str, SymbolState] = {}
        self._vwap_cum_pv: dict[str, float] = {}
        self._vwap_cum_vol: dict[str, float] = {}
        self._day_open: dict[str, float] = {}

    def update(self, symbol: str, candles_1m: list[LiveCandle],
               candles_5m: list[LiveCandle]) -> SymbolState:
        m1 = _compute_momentum(candles_1m[-5:]) if candles_1m else 0.0
        m5 = _compute_momentum(candles_5m[-5:]) if candles_5m else 0.0
        vr = _volume_ratio(candles_1m) if candles_1m else 1.0
        vt = _volume_trend(candles_1m[-5:]) if len(candles_1m) >= 2 else "stable"
        vwap = self._vwap_cum_pv.get(symbol, 0.0) / max(self._vwap_cum_vol.get(symbol, 1.0), 1.0)
        last_price = candles_1m[-1].close if candles_1m else 0.0
        atr = _atr(candles_1m[-20:]) if len(candles_1m) >= 2 else 1.0
        vwap_pos = max(-1.0, min(1.0, (last_price - vwap) / atr)) if atr > 0 else 0.0
        day_open = self._day_open.get(symbol, last_price)
        pvo = ((last_price - day_open) / day_open * 100) if day_open else 0.0
        pat_1m = detect_pattern(candles_1m[-3:]) if candles_1m else "none"
        pat_5m = detect_pattern(candles_5m[-3:]) if candles_5m else "none"
        bd = _body_dominance(candles_1m[-5:]) if candles_1m else 0.0
        aligned = (m1 > 0 and m5 > 0) or (m1 < 0 and m5 < 0) if m5 != 0 else False
        strength = _classify_strength(m1, m5, aligned)

        now = candles_1m[-1].timestamp if candles_1m else datetime.now()
        state = SymbolState(
            symbol=symbol, timestamp=now,
            momentum_1m=m1, momentum_5m=m5,
            volume_ratio=vr, volume_trend=vt,
            vwap=vwap, vwap_position=vwap_pos,
            price_vs_open=pvo,
            last_pattern_1m=pat_1m, last_pattern_5m=pat_5m,
            body_dominance=bd, trend_alignment=aligned,
            strength=strength,
        )
        self._states[symbol] = state
        return state

    def update_vwap(self, symbol: str, price: float, volume: int) -> None:
        self._vwap_cum_pv[symbol] = self._vwap_cum_pv.get(symbol, 0.0) + price * volume
        self._vwap_cum_vol[symbol] = self._vwap_cum_vol.get(symbol, 0.0) + volume
        if symbol not in self._day_open:
            self._day_open[symbol] = price

    def get_state(self, symbol: str) -> SymbolState | None:
        return self._states.get(symbol)

    def reset_day(self) -> None:
        self._vwap_cum_pv.clear()
        self._vwap_cum_vol.clear()
        self._day_open.clear()
        self._states.clear()


def _compute_momentum(candles: Sequence[LiveCandle]) -> float:
    if not candles:
        return 0.0
    # Skip gap candles -- they have no real price action data
    valid = [c for c in candles if not c.has_gap]
    if not valid:
        return 0.0
    score = 0.0
    n = len(valid)
    for i, c in enumerate(valid):
        rng = c.high - c.low
        if rng == 0:
            continue
        direction = 1.0 if c.close >= c.open else -1.0
        body_pct = abs(c.close - c.open) / rng
        close_pos = (c.close - c.low) / rng
        weight = 3.0 if i == n - 1 else 1.0
        score += direction * (body_pct * 0.6 + close_pos * 0.4) * weight
    total_weight = (n - 1) + 3.0 if n > 0 else 1.0
    return max(-100.0, min(100.0, (score / total_weight) * 100.0))


def _volume_ratio(candles: list[LiveCandle]) -> float:
    if len(candles) < 2:
        return 1.0
    lookback = candles[-21:-1] if len(candles) > 20 else candles[:-1]
    if not lookback:
        return 1.0
    avg = sum(c.volume for c in lookback) / len(lookback)
    return candles[-1].volume / avg if avg > 0 else 1.0


def _volume_trend(candles: Sequence[LiveCandle]) -> str:
    if len(candles) < 3:
        return "stable"
    vols = [c.volume for c in candles[-3:]]
    if vols[-1] > vols[0] * 1.3:
        return "rising"
    if vols[-1] < vols[0] * 0.7:
        return "falling"
    return "stable"


def _atr(candles: Sequence[LiveCandle]) -> float:
    if len(candles) < 2:
        return max(c.high - c.low for c in candles) if candles else 1.0
    ranges = [c.high - c.low for c in candles]
    return sum(ranges) / len(ranges)


def _body_dominance(candles: Sequence[LiveCandle]) -> float:
    if not candles:
        return 0.0
    ratios = []
    for c in candles:
        rng = c.high - c.low
        if rng > 0:
            ratios.append(abs(c.close - c.open) / rng)
    return sum(ratios) / len(ratios) if ratios else 0.0


def _classify_strength(m1: float, m5: float, aligned: bool) -> str:
    if not aligned:
        return "conflicting"
    avg = (abs(m1) + abs(m5)) / 2
    if avg > 50:
        return "strong"
    if avg > 25:
        return "moderate"
    return "weak"
