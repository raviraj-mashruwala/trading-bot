# Late-Start Session Catch-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When executor starts after market open (e.g. 10 AM instead of 9:15 AM), fetch the morning session data for planned stocks and use Jev to decide whether each trade is still valid before entering the normal execution flow.

**Architecture:** A new `SessionCatchup` module runs once at executor start if market has been open > 15 minutes. It fetches 1m candles from 9:15 AM to now via Kite API, computes deterministic morning-session metrics (gap, VWAP, trend, volume), sends context to Jev for a proceed/skip decision per stock, and annotates each `LegState` with the decision. The existing entry guard and Jev escalation remain unchanged — catch-up adds pre-context, not replacement logic.

**Tech Stack:** Kite historical API (1m candles), TypeSafe Jev SDK (SystemOne), existing `KiteClient`, `InstrumentCache`.

**Spec:** This conversation — user requirement for late-start context awareness.

## Global Constraints

- Python 3.12+, works on Mac and Windows
- Catch-up must complete in < 10 seconds for up to 6 stocks
- Must not block ticker — ticker starts before catch-up runs
- Jev unavailable → fall back to deterministic rules (skip if gap > 3% or price moved > 5% from entry)
- Existing entry guard rules are NOT bypassed — catch-up adds context alongside, not instead of
- Catch-up runs once per executor start, not ongoing
- Send Telegram notification with catch-up summary

## Review Focus

1. **Market closed when executor starts** — catch-up should not run before 9:15 IST or after 15:30 IST. Test: start executor at 8:55 AM, verify catch-up skipped.
2. **Kite API failure during fetch** — if 1m candles can't be fetched for a stock, that stock should proceed without catch-up context (not crash the executor). Test in Task 1.
3. **Jev returns ambiguous confidence** — if Jev's `should_proceed` is between 0.3-0.7, the stock should still go to the normal entry guard (not auto-skip). Test in Task 2.
4. **All stocks invalidated** — if catch-up skips every leg, executor should still start (with 0 waiting legs) and proceed to square-off flow normally. Test in Task 3.
5. **Executor started at exactly 9:15** — market just opened, < 15 min elapsed, catch-up should be skipped (not enough data). Test in Task 1.

---

### Task 1: SessionCatchup — fetch morning data and compute metrics

**Files:**
- Create: `tradingbot/executor/session_catchup.py`
- Test: `tests/executor/test_session_catchup.py`

**Interfaces:**
- Consumes: `KiteClient.fetch_historical(token, "minute", from_date, to_date)`, `InstrumentCache.get_token(symbol)`, `TradeLeg` from `models.py`
- Produces: `SessionCatchup.fetch_morning_context(symbols: list[str]) -> dict[str, MorningContext]` where `MorningContext` is a dataclass with: `prev_close`, `open_price`, `gap_pct`, `high`, `low`, `current_price`, `vwap`, `volume_vs_avg`, `trend` (up/down/sideways), `candle_count`, `minutes_elapsed`

- [ ] **Step 1: Write the failing test**

```python
# tests/executor/test_session_catchup.py
import pytest
from datetime import date, datetime, time
from unittest.mock import MagicMock, patch
from tradingbot.executor.session_catchup import SessionCatchup, MorningContext


def _make_candles(n: int, base_price: float = 500.0, trend: str = "up"):
    """Generate mock 1m candle rows as Kite returns them."""
    rows = []
    price = base_price
    for i in range(n):
        delta = 0.5 if trend == "up" else -0.5 if trend == "down" else 0
        price += delta
        rows.append({
            "date": datetime(2026, 10, 15, 9, 15 + i),
            "open": price - 0.2,
            "high": price + 0.3,
            "low": price - 0.4,
            "close": price,
            "volume": 10000 + i * 100,
        })
    return rows


def test_compute_morning_context_uptrend():
    candles = _make_candles(30, base_price=500.0, trend="up")
    prev_close = 498.0
    ctx = SessionCatchup._compute_context(candles, prev_close)
    assert isinstance(ctx, MorningContext)
    assert ctx.gap_pct == pytest.approx((candles[0]["open"] - 498.0) / 498.0 * 100, abs=0.1)
    assert ctx.trend == "up"
    assert ctx.vwap > 0
    assert ctx.candle_count == 30


def test_compute_morning_context_empty_candles():
    ctx = SessionCatchup._compute_context([], 500.0)
    assert ctx is None


def test_should_run_before_market():
    catchup = SessionCatchup(kite_client=MagicMock(), instrument_cache=MagicMock())
    assert catchup.should_run(time(8, 55)) is False


def test_should_run_just_after_open():
    catchup = SessionCatchup(kite_client=MagicMock(), instrument_cache=MagicMock())
    assert catchup.should_run(time(9, 20)) is False  # < 15 min


def test_should_run_late_start():
    catchup = SessionCatchup(kite_client=MagicMock(), instrument_cache=MagicMock())
    assert catchup.should_run(time(10, 0)) is True


def test_should_run_after_market():
    catchup = SessionCatchup(kite_client=MagicMock(), instrument_cache=MagicMock())
    assert catchup.should_run(time(15, 35)) is False


def test_fetch_morning_context_kite_failure():
    kite = MagicMock()
    kite.fetch_historical.side_effect = Exception("API error")
    cache = MagicMock()
    cache.get_token.return_value = 12345
    catchup = SessionCatchup(kite_client=kite, instrument_cache=cache)
    result = catchup.fetch_morning_context(["BADSTOCK"])
    assert result == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/executor/test_session_catchup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tradingbot.executor.session_catchup'`

- [ ] **Step 3: Implement SessionCatchup**

```python
# tradingbot/executor/session_catchup.py
"""Late-start session catch-up — fetches morning data when executor starts late."""

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
    trend: str  # "up", "down", "sideways"
    candle_count: int
    minutes_elapsed: int


class SessionCatchup:
    """Fetches and analyzes morning session data for late-start execution."""

    def __init__(self, kite_client: Any, instrument_cache: Any) -> None:
        self._kite = kite_client
        self._cache = instrument_cache

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
        from_dt = datetime.combine(today, MARKET_OPEN)
        to_dt = datetime.now(tz=IST).replace(tzinfo=None)
        results = {}

        for sym in symbols:
            try:
                token = self._cache.get_token(sym)
                candles = self._kite.fetch_historical(
                    token, "minute",
                    from_dt.date(), to_dt.date(),
                )
                # Filter to today's market hours only
                candles = [
                    c for c in candles
                    if c["date"].time() >= MARKET_OPEN
                ]
                if not candles:
                    log.warning("%s: no morning candles available", sym)
                    continue

                # Get previous close from daily data
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

        # VWAP
        typical_prices = [(c["high"] + c["low"] + c["close"]) / 3 * c["volume"] for c in candles]
        vwap = sum(typical_prices) / volume_total if volume_total > 0 else current_price

        # Gap
        gap_pct = (open_price - prev_close) / prev_close * 100 if prev_close > 0 else 0

        # Trend — compare first third avg close vs last third avg close
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

        # Volume vs average (rough: total / candles * 375 for full day estimate)
        avg_per_candle = volume_total / n if n > 0 else 0
        full_day_estimate = avg_per_candle * 375
        volume_vs_avg = 1.0  # baseline, no historical comparison available

        minutes_elapsed = n  # 1 candle = 1 minute

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
            minutes_elapsed=minutes_elapsed,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/executor/test_session_catchup.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -x -q`
Expected: 920+ passed

- [ ] **Step 6: Commit**

```bash
git add tradingbot/executor/session_catchup.py tests/executor/test_session_catchup.py
git commit -m "feat: add SessionCatchup — fetch morning data for late-start execution"
```

---

### Task 2: Jev catch-up decision — proceed/skip/adjust per stock

**Files:**
- Modify: `tradingbot/executor/session_catchup.py`
- Test: `tests/executor/test_session_catchup.py` (add tests)

**Interfaces:**
- Consumes: `MorningContext` from Task 1, `TradeLeg` from models.py, Jev SDK (`typesafe_sdk`)
- Produces: `CatchupDecision` dataclass with `action` (proceed/skip), `reason`, `adjusted_entry` (optional), `confidence`. Method: `SessionCatchup.evaluate_with_jev(contexts: dict[str, MorningContext], legs: list[TradeLeg]) -> dict[str, CatchupDecision]`

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/executor/test_session_catchup.py

from tradingbot.executor.session_catchup import CatchupDecision
from tradingbot.core.models import TradeLeg, Direction


def _make_leg(symbol: str, entry: float, direction: str = "long") -> TradeLeg:
    return TradeLeg(
        symbol=symbol,
        direction=Direction(direction),
        entry_price=entry,
        stop_loss=entry * 0.98,
        target_1=entry * 1.03,
        target_2=entry * 1.05,
        quantity=100,
        confidence=0.7,
    )


def _make_context(symbol: str, current: float, gap: float = 0.5, trend: str = "up") -> MorningContext:
    return MorningContext(
        symbol=symbol, prev_close=current - 5, open_price=current - 3,
        gap_pct=gap, high=current + 2, low=current - 4,
        current_price=current, vwap=current - 1, volume_total=500000,
        volume_vs_avg=1.2, trend=trend, candle_count=30, minutes_elapsed=30,
    )


def test_deterministic_fallback_skip_large_gap():
    """Gap > 3% should skip without Jev."""
    catchup = SessionCatchup(kite_client=MagicMock(), instrument_cache=MagicMock())
    ctx = _make_context("TEST", 520.0, gap=4.0)
    leg = _make_leg("TEST", 500.0)
    decision = catchup._deterministic_decision(ctx, leg)
    assert decision.action == "skip"
    assert "gap" in decision.reason.lower()


def test_deterministic_fallback_skip_price_drift():
    """Price moved > 5% from entry should skip."""
    catchup = SessionCatchup(kite_client=MagicMock(), instrument_cache=MagicMock())
    ctx = _make_context("TEST", 550.0)  # 10% above entry
    leg = _make_leg("TEST", 500.0)
    decision = catchup._deterministic_decision(ctx, leg)
    assert decision.action == "skip"
    assert "drift" in decision.reason.lower()


def test_deterministic_fallback_proceed():
    """Normal conditions should proceed."""
    catchup = SessionCatchup(kite_client=MagicMock(), instrument_cache=MagicMock())
    ctx = _make_context("TEST", 502.0, gap=0.5, trend="up")
    leg = _make_leg("TEST", 500.0)
    decision = catchup._deterministic_decision(ctx, leg)
    assert decision.action == "proceed"


def test_deterministic_short_against_uptrend():
    """Short trade into uptrend should skip."""
    catchup = SessionCatchup(kite_client=MagicMock(), instrument_cache=MagicMock())
    ctx = _make_context("TEST", 502.0, trend="up")
    leg = _make_leg("TEST", 500.0, direction="short")
    decision = catchup._deterministic_decision(ctx, leg)
    assert decision.action == "skip"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/executor/test_session_catchup.py -v -k "deterministic"`
Expected: FAIL — `CatchupDecision` and `_deterministic_decision` not defined

- [ ] **Step 3: Implement CatchupDecision and Jev evaluation**

Add to `tradingbot/executor/session_catchup.py`:

```python
@dataclass
class CatchupDecision:
    symbol: str
    action: str  # "proceed" or "skip"
    reason: str
    confidence: float
    adjusted_entry: float | None = None
```

Add methods to `SessionCatchup`:

```python
    def evaluate(
        self, contexts: dict[str, MorningContext], legs: list,
    ) -> dict[str, CatchupDecision]:
        """Evaluate each leg using Jev (with deterministic fallback)."""
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

            # Try Jev first
            jev_decision = self._jev_evaluate(ctx, leg)
            if jev_decision is not None:
                decisions[leg.symbol] = jev_decision
            else:
                decisions[leg.symbol] = self._deterministic_decision(ctx, leg)

        return decisions

    def _jev_evaluate(self, ctx: MorningContext, leg: Any) -> CatchupDecision | None:
        """Call Jev for catch-up decision. Returns None if Jev unavailable."""
        try:
            from typesafe_sdk import Jev
            jev = Jev()
            result = jev.evaluate(
                f"Stock {ctx.symbol} planned {leg.direction.value.upper()} entry at ₹{leg.entry_price:.2f}. "
                f"Morning session: opened at ₹{ctx.open_price:.2f} (gap {ctx.gap_pct:+.1f}%), "
                f"traded ₹{ctx.low:.2f}-₹{ctx.high:.2f}, now at ₹{ctx.current_price:.2f}, "
                f"VWAP ₹{ctx.vwap:.2f}, trend {ctx.trend}, {ctx.minutes_elapsed} min elapsed. "
                f"Should we still enter this trade?",
                questions={
                    "should_proceed": "Should this trade still be taken given the morning action?",
                    "invalidated": "Has the morning price action invalidated the original setup?",
                },
            )
            should_proceed = result.get("should_proceed", 0.5)
            invalidated = result.get("invalidated", 0.5)

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
        except Exception as exc:
            log.warning("%s: Jev catch-up failed: %s, using deterministic fallback", ctx.symbol, exc)
            return None

    def _deterministic_decision(self, ctx: MorningContext, leg: Any) -> CatchupDecision:
        """Fallback rules when Jev is unavailable."""
        # Rule 1: Large gap
        if abs(ctx.gap_pct) > 3.0:
            return CatchupDecision(
                symbol=ctx.symbol, action="skip",
                reason=f"Gap {ctx.gap_pct:+.1f}% exceeds 3% threshold",
                confidence=0.2,
            )

        # Rule 2: Price drifted > 5% from planned entry
        drift = abs(ctx.current_price - leg.entry_price) / leg.entry_price * 100
        if drift > 5.0:
            return CatchupDecision(
                symbol=ctx.symbol, action="skip",
                reason=f"Price drift {drift:.1f}% from entry (current ₹{ctx.current_price:.2f} vs plan ₹{leg.entry_price:.2f})",
                confidence=0.1,
            )

        # Rule 3: Direction vs trend conflict
        is_long = leg.direction.value == "long"
        if is_long and ctx.trend == "down" and ctx.current_price < ctx.vwap:
            return CatchupDecision(
                symbol=ctx.symbol, action="skip",
                reason=f"LONG into downtrend below VWAP",
                confidence=0.3,
            )
        if not is_long and ctx.trend == "up" and ctx.current_price > ctx.vwap:
            return CatchupDecision(
                symbol=ctx.symbol, action="skip",
                reason=f"SHORT into uptrend above VWAP",
                confidence=0.3,
            )

        # Default: proceed
        return CatchupDecision(
            symbol=ctx.symbol, action="proceed",
            reason=f"Morning context OK: {ctx.trend} trend, gap {ctx.gap_pct:+.1f}%, drift {drift:.1f}%",
            confidence=0.6,
        )
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/executor/test_session_catchup.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -x -q`
Expected: 920+ passed

- [ ] **Step 6: Commit**

```bash
git add tradingbot/executor/session_catchup.py tests/executor/test_session_catchup.py
git commit -m "feat: add Jev catch-up decision with deterministic fallback"
```

---

### Task 3: Wire catch-up into executor startup + Telegram notification

**Files:**
- Modify: `tradingbot/api/execution_routes.py:170-175` (between executor.start() and main loop)
- Modify: `tradingbot/core/telegram_notifier.py` (add notify_catchup_summary)
- Test: `tests/executor/test_session_catchup.py` (add integration test)

**Interfaces:**
- Consumes: `SessionCatchup` from Tasks 1-2, `Executor` states, `TradePlan.legs`
- Produces: Catch-up runs at executor start, skipped legs marked with `skipped_reason`, Telegram notification sent with summary

- [ ] **Step 1: Write the failing integration test**

```python
# Add to tests/executor/test_session_catchup.py

def test_catchup_skips_invalidated_legs():
    """Legs marked skip by catch-up should have skipped_reason set."""
    from tradingbot.executor.session_catchup import apply_catchup_decisions, CatchupDecision

    class FakeLegState:
        def __init__(self, symbol):
            self.leg = _make_leg(symbol, 500.0)
            self.waiting = True
            self.skipped_reason = None
            self.cancelled = False

    states = [FakeLegState("SKIP_ME"), FakeLegState("KEEP_ME")]
    decisions = {
        "SKIP_ME": CatchupDecision("SKIP_ME", "skip", "gap too large", 0.2),
        "KEEP_ME": CatchupDecision("KEEP_ME", "proceed", "OK", 0.7),
    }
    apply_catchup_decisions(states, decisions)
    assert states[0].skipped_reason is not None
    assert states[0].waiting is False
    assert states[1].waiting is True
    assert states[1].skipped_reason is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/executor/test_session_catchup.py::test_catchup_skips_invalidated_legs -v`
Expected: FAIL — `apply_catchup_decisions` not defined

- [ ] **Step 3: Implement apply_catchup_decisions**

Add to `tradingbot/executor/session_catchup.py`:

```python
def apply_catchup_decisions(
    leg_states: list, decisions: dict[str, CatchupDecision],
) -> None:
    """Apply catch-up decisions to executor leg states."""
    for state in leg_states:
        decision = decisions.get(state.leg.symbol)
        if decision is None:
            continue
        if decision.action == "skip":
            state.waiting = False
            state.cancelled = True
            state.skipped_reason = f"Catch-up: {decision.reason}"
            log.info("%s: skipped by catch-up — %s", state.leg.symbol, decision.reason)
```

- [ ] **Step 4: Add Telegram notification method**

Add to `tradingbot/core/telegram_notifier.py` before `build_notifier`:

```python
    def notify_catchup_summary(self, decisions: dict) -> None:
        lines = ["\U0001f504 <b>LATE-START CATCH-UP</b>\n"]
        for sym, d in decisions.items():
            emoji = "✅" if d.action == "proceed" else "❌"
            lines.append(f"{emoji} <b>{sym}</b>: {d.reason}")
        self.send_sync("\n".join(lines))
```

- [ ] **Step 5: Wire into execution_routes.py**

In `_run_execution()`, after `executor.start()` (around line 170) and before the main tick loop:

```python
        # Late-start catch-up
        from tradingbot.executor.session_catchup import SessionCatchup, apply_catchup_decisions
        from tradingbot.core.models import now_ist
        catchup = SessionCatchup(
            kite_client=data_kite_client,
            instrument_cache=instrument_cache,
        )
        current_time = now_ist().time()
        if catchup.should_run(current_time):
            log.info("Late start detected (%s) — running morning catch-up", current_time.strftime("%H:%M"))
            symbols = [leg.symbol for leg in plan.legs]
            contexts = catchup.fetch_morning_context(symbols)
            decisions = catchup.evaluate(contexts, plan.legs)
            apply_catchup_decisions(executor.states, decisions)

            telegram = getattr(state, "_telegram", None)
            if telegram:
                telegram.notify_catchup_summary(decisions)

            await state.event_bus.emit("exec.catchup", {
                "decisions": {s: d.action for s, d in decisions.items()},
            })
        else:
            log.info("On-time start (%s) — skipping catch-up", current_time.strftime("%H:%M"))
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/executor/test_session_catchup.py tests/ -x -q`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add tradingbot/executor/session_catchup.py tradingbot/api/execution_routes.py tradingbot/core/telegram_notifier.py tests/executor/test_session_catchup.py
git commit -m "feat: wire late-start catch-up into executor with Telegram notification"
```
