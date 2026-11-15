"""Late-start session catch-up — fetches morning data when executor starts late.

When the executor starts after market open (e.g. 10 AM instead of 9:15),
this module fetches 1m candles from 9:15 AM, computes morning-session
metrics, and uses Jev to decide whether each planned trade is still valid.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
MIN_ELAPSED_MINUTES = 15


@dataclass
class MorningContext:
    symbol: str
    prev_close: float
    open_price: float
    gap_pct: float
    high: float
    low: float
    current_price: float
    vwap: float
    volume_total: int
    volume_vs_avg: float
    trend: str
    candle_count: int
    minutes_elapsed: int


@dataclass
class CatchupDecision:
    symbol: str
    action: str
    reason: str
    confidence: float
    adjusted_entry: float | None = None


class SessionCatchup:
    def __init__(self, kite_client: Any, instrument_cache: Any, jev_client: Any | None = None) -> None:
        self._kite = kite_client
        self._cache = instrument_cache
        self._jev = jev_client

    def should_run(self, current_time: time) -> bool:
        if current_time < MARKET_OPEN or current_time >= MARKET_CLOSE:
            return False
        elapsed = (
            datetime.combine(date.today(), current_time)
            - datetime.combine(date.today(), MARKET_OPEN)
        ).total_seconds() / 60
        return elapsed >= MIN_ELAPSED_MINUTES

    def fetch_morning_context(self, symbols: list[str]) -> dict[str, MorningContext]:
        today = date.today()
        results = {}

        for sym in symbols:
            try:
                token = self._cache.get_token(sym)
                candles = self._kite.fetch_historical(
                    token, "minute", today, today,
                )
                candles = [
                    c for c in candles
                    if c["date"].time() >= MARKET_OPEN
                ]
                if not candles:
                    log.warning("%s: no morning candles available", sym)
                    continue

                yesterday = today - timedelta(days=1)
                daily = self._kite.fetch_historical(
                    token, "day", yesterday - timedelta(days=5), yesterday,
                )
                prev_close = daily[-1]["close"] if daily else candles[0]["open"]

                ctx = self._compute_context(candles, prev_close)
                if ctx is not None:
                    ctx.symbol = sym
                    results[sym] = ctx
                    log.info(
                        "%s catch-up: gap=%.1f%% trend=%s price=%.2f vwap=%.2f %d candles",
                        sym, ctx.gap_pct, ctx.trend, ctx.current_price, ctx.vwap, ctx.candle_count,
                    )
            except Exception as exc:
                log.warning("%s: morning catch-up fetch failed: %s", sym, exc)

        return results

    @staticmethod
    def _compute_context(candles: list[dict], prev_close: float) -> MorningContext | None:
        if not candles:
            return None

        open_price = candles[0]["open"]
        high = max(c["high"] for c in candles)
        low = min(c["low"] for c in candles)
        current_price = candles[-1]["close"]
        volume_total = sum(c["volume"] for c in candles)

        typical_prices = [(c["high"] + c["low"] + c["close"]) / 3 * c["volume"] for c in candles]
        vwap = sum(typical_prices) / volume_total if volume_total > 0 else current_price

        gap_pct = (open_price - prev_close) / prev_close * 100 if prev_close > 0 else 0

        n = len(candles)
        third = max(1, n // 3)
        first_avg = sum(c["close"] for c in candles[:third]) / third
        last_avg = sum(c["close"] for c in candles[-third:]) / third
        pct_change = (last_avg - first_avg) / first_avg * 100 if first_avg > 0 else 0
        if pct_change > 0.3:
            trend = "up"
        elif pct_change < -0.3:
            trend = "down"
        else:
            trend = "sideways"

        volume_vs_avg = 1.0

        return MorningContext(
            symbol="",
            prev_close=prev_close,
            open_price=open_price,
            gap_pct=gap_pct,
            high=high,
            low=low,
            current_price=current_price,
            vwap=vwap,
            volume_total=volume_total,
            volume_vs_avg=volume_vs_avg,
            trend=trend,
            candle_count=n,
            minutes_elapsed=n,
        )

    def evaluate(
        self, contexts: dict[str, MorningContext], legs: list,
    ) -> dict[str, CatchupDecision]:
        decisions = {}
        for leg in legs:
            ctx = contexts.get(leg.symbol)
            if ctx is None:
                decisions[leg.symbol] = CatchupDecision(
                    symbol=leg.symbol, action="proceed",
                    reason="no morning data — proceeding without catch-up",
                    confidence=0.5,
                )
                continue

            jev_decision = self._jev_evaluate(ctx, leg)
            if jev_decision is not None:
                decisions[leg.symbol] = jev_decision
            else:
                decisions[leg.symbol] = self._deterministic_decision(ctx, leg)

        return decisions

    def _jev_evaluate(self, ctx: MorningContext, leg: Any) -> CatchupDecision | None:
        jev = self._jev
        if jev is None or not jev.available:
            return None
        try:
            from tradingbot.core.jev_client import Noul
            if Noul is None:
                return None
            answers = jev.evaluate(
                state={
                    "symbol": ctx.symbol,
                    "direction": leg.direction.value,
                    "planned_entry": leg.entry_price,
                    "open_price": ctx.open_price,
                    "gap_pct": ctx.gap_pct,
                    "day_low": ctx.low,
                    "day_high": ctx.high,
                    "current_price": ctx.current_price,
                    "vwap": ctx.vwap,
                    "trend": ctx.trend,
                    "minutes_elapsed": ctx.minutes_elapsed,
                },
                questions={
                    "should_proceed": Noul(
                        instructions="Should this planned trade still be taken given the morning price action?",
                        criteria={
                            "true": "Morning action is consistent with the planned entry; the setup is still actionable",
                            "false": "Morning action makes the planned entry unattractive or unreachable",
                        },
                    ),
                    "invalidated": Noul(
                        instructions="Has the morning price action invalidated the original trade setup?",
                        criteria={
                            "true": "Price moved decisively through the planned levels or against the thesis",
                            "false": "Setup thesis still intact despite the morning moves",
                        },
                    ),
                },
            )
            if answers is None:
                return None
            should_proceed = answers["should_proceed"].noul
            invalidated = answers["invalidated"].noul
        except Exception as exc:
            log.warning("%s: Jev catch-up failed: %s, using deterministic fallback", ctx.symbol, exc)
            return None

        if invalidated > 0.7:
            return CatchupDecision(
                symbol=ctx.symbol, action="skip",
                reason=f"Jev: setup invalidated ({invalidated:.0%})",
                confidence=1 - invalidated,
            )
        if should_proceed >= 0.6:
            return CatchupDecision(
                symbol=ctx.symbol, action="proceed",
                reason=f"Jev: proceed ({should_proceed:.0%})",
                confidence=should_proceed,
            )
        return CatchupDecision(
            symbol=ctx.symbol, action="skip",
            reason=f"Jev: low confidence ({should_proceed:.0%})",
            confidence=should_proceed,
        )

    def _deterministic_decision(self, ctx: MorningContext, leg: Any) -> CatchupDecision:
        if abs(ctx.gap_pct) > 3.0:
            return CatchupDecision(
                symbol=ctx.symbol, action="skip",
                reason=f"Gap {ctx.gap_pct:+.1f}% exceeds 3% threshold",
                confidence=0.2,
            )

        drift = abs(ctx.current_price - leg.entry_price) / leg.entry_price * 100
        if drift > 5.0:
            return CatchupDecision(
                symbol=ctx.symbol, action="skip",
                reason=f"Price drift {drift:.1f}% from entry (current ₹{ctx.current_price:.2f} vs plan ₹{leg.entry_price:.2f})",
                confidence=0.1,
            )

        is_long = leg.direction.value == "long"
        if is_long and ctx.trend == "down" and ctx.current_price < ctx.vwap:
            return CatchupDecision(
                symbol=ctx.symbol, action="skip",
                reason="LONG into downtrend below VWAP",
                confidence=0.3,
            )
        if not is_long and ctx.trend == "up" and ctx.current_price > ctx.vwap:
            return CatchupDecision(
                symbol=ctx.symbol, action="skip",
                reason="SHORT into uptrend above VWAP",
                confidence=0.3,
            )

        return CatchupDecision(
            symbol=ctx.symbol, action="proceed",
            reason=f"Morning context OK: {ctx.trend} trend, gap {ctx.gap_pct:+.1f}%, drift {drift:.1f}%",
            confidence=0.6,
        )


def apply_catchup_decisions(
    leg_states: list, decisions: dict[str, CatchupDecision],
) -> None:
    for state in leg_states:
        decision = decisions.get(state.leg.symbol)
        if decision is None:
            continue
        if decision.action == "skip":
            state.waiting = False
            state.cancelled = True
            state.skipped_reason = f"Catch-up: {decision.reason}"
            log.info("%s: skipped by catch-up — %s", state.leg.symbol, decision.reason)
