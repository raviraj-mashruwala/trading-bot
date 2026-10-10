"""Scout signal scanner — alerts only, no execution.

Scans live 1m candle data for two backtested signals:
1. RSI Divergence (PF 1.28 over 7.7 years)
2. VWAP Pullback (PF 1.24 over 7.7 years)

Produces alerts for the UI dashboard. Does not place orders.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from tradingbot.executor.candle_aggregator import LiveCandle

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScoutAlert:
    timestamp: datetime
    symbol: str
    signal: str
    direction: str
    confidence: float
    entry_price: float
    target_price: float
    stop_price: float
    reasoning: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "signal": self.signal,
            "direction": self.direction,
            "confidence": self.confidence,
            "entry_price": self.entry_price,
            "target_price": self.target_price,
            "stop_price": self.stop_price,
            "reasoning": self.reasoning,
        }


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    ag = sum(max(d, 0) for d in deltas[:period]) / period
    al = sum(max(-d, 0) for d in deltas[:period]) / period
    for i in range(period, len(deltas)):
        ag = (ag * (period - 1) + max(deltas[i], 0)) / period
        al = (al * (period - 1) + max(-deltas[i], 0)) / period
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def _vwap(candles: list[LiveCandle]) -> float:
    cum_pv = sum((c.high + c.low + c.close) / 3 * c.volume for c in candles)
    cum_vol = sum(c.volume for c in candles)
    return cum_pv / cum_vol if cum_vol > 0 else 0


@dataclass
class _PendingAlert:
    db_id: int
    symbol: str
    direction: str
    entry_price: float
    target_price: float
    stop_price: float
    fired_at: datetime
    candles_seen: int = 0

MAX_CANDLES_TO_RESOLVE = 15


class ScoutScanner:
    """Scanner with auto-grading — tracks pending alerts and resolves outcomes."""

    def __init__(self, database=None) -> None:
        self._fired: set[str] = set()
        self._pending: list[_PendingAlert] = []
        self._db = database

    def reset_day(self) -> None:
        self._fired.clear()
        self._pending.clear()

    def add_pending(self, db_id: int, alert: ScoutAlert) -> None:
        self._pending.append(_PendingAlert(
            db_id=db_id, symbol=alert.symbol, direction=alert.direction,
            entry_price=alert.entry_price, target_price=alert.target_price,
            stop_price=alert.stop_price, fired_at=alert.timestamp,
        ))

    def grade_pending(self, symbol: str, candles_1m: list[LiveCandle]) -> None:
        """Check pending alerts against latest candle data and resolve outcomes."""
        if not self._pending or not candles_1m:
            return

        resolved: list[int] = []
        for i, p in enumerate(self._pending):
            if p.symbol != symbol:
                continue

            p.candles_seen += 1
            price = candles_1m[-1].close

            if p.direction == "long":
                high_since = max(c.high for c in candles_1m[-min(p.candles_seen, len(candles_1m)):])
                low_since = min(c.low for c in candles_1m[-min(p.candles_seen, len(candles_1m)):])
                if high_since >= p.target_price:
                    self._resolve(i, "target_hit", (p.target_price - p.entry_price) / p.entry_price * 100)
                    resolved.append(i)
                elif low_since <= p.stop_price:
                    self._resolve(i, "stop_hit", (p.stop_price - p.entry_price) / p.entry_price * 100)
                    resolved.append(i)
                elif p.candles_seen >= MAX_CANDLES_TO_RESOLVE:
                    pnl_pct = (price - p.entry_price) / p.entry_price * 100
                    self._resolve(i, "timeout", pnl_pct)
                    resolved.append(i)
            else:
                high_since = max(c.high for c in candles_1m[-min(p.candles_seen, len(candles_1m)):])
                low_since = min(c.low for c in candles_1m[-min(p.candles_seen, len(candles_1m)):])
                if low_since <= p.target_price:
                    self._resolve(i, "target_hit", (p.entry_price - p.target_price) / p.entry_price * 100)
                    resolved.append(i)
                elif high_since >= p.stop_price:
                    self._resolve(i, "stop_hit", (p.entry_price - p.stop_price) / p.entry_price * 100)
                    resolved.append(i)
                elif p.candles_seen >= MAX_CANDLES_TO_RESOLVE:
                    pnl_pct = (p.entry_price - price) / p.entry_price * 100
                    self._resolve(i, "timeout", pnl_pct)
                    resolved.append(i)

        for i in sorted(resolved, reverse=True):
            self._pending.pop(i)

    def _resolve(self, idx: int, outcome: str, pnl_pct: float) -> None:
        p = self._pending[idx]
        log.info("Scout %s %s %s: %s (%.2f%%)", p.symbol, p.direction, p.db_id, outcome, pnl_pct)
        if self._db is not None:
            try:
                self._db.update_scout_outcome(p.db_id, outcome, round(pnl_pct, 4))
            except Exception:
                log.warning("Failed to update scout outcome for %d", p.db_id, exc_info=True)

    def scan(
        self,
        symbol: str,
        candles_1m: list[LiveCandle],
        now: datetime | None = None,
    ) -> list[ScoutAlert]:
        if len(candles_1m) < 25:
            return []

        now = now or datetime.now()
        if now.hour < 10:
            return []

        alerts: list[ScoutAlert] = []

        rsi_div = self._check_rsi_divergence(symbol, candles_1m, now)
        if rsi_div:
            alerts.append(rsi_div)

        vwap_pb = self._check_vwap_pullback(symbol, candles_1m, now)
        if vwap_pb:
            alerts.append(vwap_pb)

        return alerts

    def _check_rsi_divergence(
        self, symbol: str, candles: list[LiveCandle], now: datetime,
    ) -> ScoutAlert | None:
        closes = [c.close for c in candles]
        rsi = _rsi(closes)
        if rsi is None:
            return None

        lookback = 20
        if len(candles) < lookback + 5:
            return None

        price_now = closes[-1]
        price_prev = min(closes[-lookback - 1:-1]) if rsi < 50 else max(closes[-lookback - 1:-1])

        rsi_values = []
        for i in range(len(candles) - lookback, len(candles) + 1):
            r = _rsi(closes[:i])
            if r is not None:
                rsi_values.append(r)

        if len(rsi_values) < lookback:
            return None

        rsi_now = rsi_values[-1]
        rsi_at_prev_extreme = min(rsi_values[:-1]) if rsi_now < 50 else max(rsi_values[:-1])

        last_candle = candles[-1]
        body_ratio = abs(last_candle.close - last_candle.open) / max(last_candle.high - last_candle.low, 0.01)

        # Bullish divergence: price lower low, RSI higher low, green candle
        if (price_now < price_prev and rsi_now > rsi_at_prev_extreme
                and rsi_now < 35 and last_candle.close > last_candle.open and body_ratio > 0.5):
            key = f"{symbol}_rsi_div_long_{now.strftime('%H:%M')}"
            if key in self._fired:
                return None
            self._fired.add(key)
            target = price_now * 1.007
            stop = price_now * 0.996
            return ScoutAlert(
                timestamp=now, symbol=symbol, signal="RSI_DIVERGENCE",
                direction="long", confidence=0.65,
                entry_price=price_now, target_price=target, stop_price=stop,
                reasoning=f"Bullish RSI divergence: price new low but RSI higher ({rsi_now:.1f} vs {rsi_at_prev_extreme:.1f})",
            )

        # Bearish divergence: price higher high, RSI lower high, red candle
        if (price_now > price_prev and rsi_now < rsi_at_prev_extreme
                and rsi_now > 65 and last_candle.close < last_candle.open and body_ratio > 0.5):
            key = f"{symbol}_rsi_div_short_{now.strftime('%H:%M')}"
            if key in self._fired:
                return None
            self._fired.add(key)
            target = price_now * 0.993
            stop = price_now * 1.004
            return ScoutAlert(
                timestamp=now, symbol=symbol, signal="RSI_DIVERGENCE",
                direction="short", confidence=0.65,
                entry_price=price_now, target_price=target, stop_price=stop,
                reasoning=f"Bearish RSI divergence: price new high but RSI lower ({rsi_now:.1f} vs {rsi_at_prev_extreme:.1f})",
            )

        return None

    def _check_vwap_pullback(
        self, symbol: str, candles: list[LiveCandle], now: datetime,
    ) -> ScoutAlert | None:
        closes = [c.close for c in candles]
        rsi = _rsi(closes)
        if rsi is None:
            return None

        vwap = _vwap(candles)
        if vwap <= 0:
            return None

        price = closes[-1]
        vwap_dist_pct = abs(price - vwap) / vwap * 100

        if vwap_dist_pct > 0.1:
            return None

        # Determine trend: was price >1% above or below VWAP recently?
        recent_max = max(closes[-30:]) if len(closes) >= 30 else max(closes)
        recent_min = min(closes[-30:]) if len(closes) >= 30 else min(closes)
        was_above = (recent_max - vwap) / vwap * 100 > 1.0
        was_below = (vwap - recent_min) / vwap * 100 > 1.0

        if was_above and not was_below and rsi > 40:
            key = f"{symbol}_vwap_long_{now.strftime('%H:%M')}"
            if key in self._fired:
                return None
            self._fired.add(key)
            target = price * 1.005
            stop = price * 0.997
            return ScoutAlert(
                timestamp=now, symbol=symbol, signal="VWAP_PULLBACK",
                direction="long", confidence=0.55,
                entry_price=price, target_price=target, stop_price=stop,
                reasoning=f"Uptrend pullback to VWAP ({vwap:.2f}), RSI {rsi:.1f} — trend intact",
            )

        if was_below and not was_above and rsi < 60:
            key = f"{symbol}_vwap_short_{now.strftime('%H:%M')}"
            if key in self._fired:
                return None
            self._fired.add(key)
            target = price * 0.995
            stop = price * 1.003
            return ScoutAlert(
                timestamp=now, symbol=symbol, signal="VWAP_PULLBACK",
                direction="short", confidence=0.55,
                entry_price=price, target_price=target, stop_price=stop,
                reasoning=f"Downtrend rally to VWAP ({vwap:.2f}), RSI {rsi:.1f} — trend intact",
            )

        return None
