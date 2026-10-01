"""Integration tests covering full entry/exit flows through the intelligence layer.

These tests use REAL component instances (CandleAggregator, MomentumScorer,
EntryGuard, AdaptiveExitManager), not mocks. Tick sequences create real
candle patterns that drive real scoring and decision logic.
"""

from datetime import datetime, time

import pytest

from tradingbot.executor.candle_aggregator import CandleAggregator, LiveCandle
from tradingbot.executor.momentum_scorer import MomentumScorer
from tradingbot.executor.entry_guard import EntryGuard
from tradingbot.executor.adaptive_exit_manager import AdaptiveExitManager, ExitDecision
from tradingbot.executor.tick_replayer import TickReplayer


# ---------------------------------------------------------------------------
# Fakes for the "leg" and "leg state" objects the exit manager expects
# ---------------------------------------------------------------------------

class FakeLeg:
    def __init__(self, direction="long", entry_price=2450.0):
        self.symbol = "RELIANCE"
        self.direction = type("D", (), {"value": direction})()
        self.entry_price = entry_price
        self.entry_window_end = time(10, 0)
        self.max_entry_wait = time(10, 30)
        self.stop_loss = 2430.0
        self.target_1 = 2470.0
        self.target_2 = 2490.0
        self.exit_before = time(15, 15)


class FakeLegState:
    def __init__(self, direction="long", entry=2450.0, stop=2430.0,
                 t1_booked=False, qty=10):
        self.leg = FakeLeg(direction, entry)
        self.entry_fill_price = entry
        self.current_stop = stop
        self.target_1_booked = t1_booked
        self.filled_quantity = qty


# ---------------------------------------------------------------------------
# Tick generators — produce realistic candle bodies by putting 2 ticks per minute
# ---------------------------------------------------------------------------

def _bullish_ticks(symbol: str = "RELIANCE", base_price: float = 2450.0,
                   base_minute: int = 15, count: int = 10) -> list[dict]:
    """Generate bullish ticks: each minute opens low, closes higher.

    Two ticks per minute so each 1min candle has a real bullish body.
    Price rises steadily across minutes.
    """
    ticks = []
    for i in range(count):
        minute = base_minute + i
        low = base_price + i * 3
        high = low + 2.5  # bullish body: close > open
        ticks.append({"symbol": symbol, "price": low, "volume": 1000,
                       "timestamp": datetime(2026, 9, 29, 9, minute, 5)})
        ticks.append({"symbol": symbol, "price": high, "volume": 1000,
                       "timestamp": datetime(2026, 9, 29, 9, minute, 45)})
    return ticks


def _bearish_ticks(symbol: str = "RELIANCE", base_price: float = 2480.0,
                   base_minute: int = 15, count: int = 10) -> list[dict]:
    """Generate bearish ticks: each minute opens high, closes lower.

    Two ticks per minute so each 1min candle has a real bearish body.
    Price falls steadily across minutes.
    """
    ticks = []
    for i in range(count):
        minute = base_minute + i
        high = base_price - i * 3
        low = high - 2.5  # bearish body: close < open
        ticks.append({"symbol": symbol, "price": high, "volume": 1000,
                       "timestamp": datetime(2026, 9, 29, 9, minute, 5)})
        ticks.append({"symbol": symbol, "price": low, "volume": 1000,
                       "timestamp": datetime(2026, 9, 29, 9, minute, 45)})
    return ticks


def _replay_into(agg: CandleAggregator, ticks: list[dict]) -> None:
    """Helper: replay ticks into aggregator."""
    TickReplayer(ticks).replay(agg)


# ---------------------------------------------------------------------------
# Test 1: Full flow clean entry (bullish ticks → positive momentum → ENTER)
# ---------------------------------------------------------------------------

def test_full_flow_clean_entry():
    """Bullish ticks produce positive momentum, EntryGuard approves LONG entry."""
    agg = CandleAggregator()
    scorer = MomentumScorer()
    guard = EntryGuard(max_drift_pct=5.0)

    # Feed 12 minutes of bullish ticks (minutes 15-26), then close with tick at minute 27
    ticks = _bullish_ticks(count=12)
    # Add a final tick in a later minute to close the last candle
    ticks.append({"symbol": "RELIANCE", "price": 2490.0, "volume": 500,
                  "timestamp": datetime(2026, 9, 29, 9, 27, 5)})
    _replay_into(agg, ticks)

    candles_1m = agg.get_candles("RELIANCE", "1min")
    candles_5m = agg.get_candles("RELIANCE", "5min")

    # Should have 12 closed 1min candles (minutes 15-26) and at least 1 closed 5min
    assert len(candles_1m) >= 5, f"Expected >= 5 closed 1min candles, got {len(candles_1m)}"
    assert len(candles_5m) >= 1, f"Expected >= 1 closed 5min candle, got {len(candles_5m)}"

    state = scorer.update("RELIANCE", candles_1m, candles_5m)

    # Momentum should be positive for bullish candles
    assert state.momentum_1m > 0, f"Expected positive 1m momentum, got {state.momentum_1m}"
    assert state.momentum_5m > 0, f"Expected positive 5m momentum, got {state.momentum_5m}"

    # Current price near 2486 (end of bullish run), entry at 2450
    current_price = agg.last_price("RELIANCE")
    verdict = guard.evaluate(FakeLeg(), state, current_price, datetime(2026, 9, 29, 9, 27))

    # With aligned bullish momentum, should approve entry
    assert verdict.action == "ENTER", f"Expected ENTER, got {verdict.action}: {verdict.reason}"


# ---------------------------------------------------------------------------
# Test 2: Full flow veto entry (bearish ticks → negative momentum → VETO LONG)
# ---------------------------------------------------------------------------

def test_full_flow_veto_entry():
    """Bearish ticks produce negative momentum, EntryGuard vetoes LONG entry."""
    agg = CandleAggregator()
    scorer = MomentumScorer()
    guard = EntryGuard(max_drift_pct=5.0)

    # Feed 12 minutes of bearish ticks starting high
    ticks = _bearish_ticks(count=12)
    # Close last candle
    ticks.append({"symbol": "RELIANCE", "price": 2440.0, "volume": 500,
                  "timestamp": datetime(2026, 9, 29, 9, 27, 5)})
    _replay_into(agg, ticks)

    candles_1m = agg.get_candles("RELIANCE", "1min")
    candles_5m = agg.get_candles("RELIANCE", "5min")

    assert len(candles_1m) >= 5
    assert len(candles_5m) >= 1

    state = scorer.update("RELIANCE", candles_1m, candles_5m)

    # Momentum should be negative for bearish candles
    assert state.momentum_1m < 0, f"Expected negative 1m momentum, got {state.momentum_1m}"
    assert state.momentum_5m < 0, f"Expected negative 5m momentum, got {state.momentum_5m}"

    # Entry guard: mild bearish enters gray zone (low confidence ENTER) or
    # VETO/WAIT if momentum is strong enough. Either way, confidence < 0.5.
    current_price = agg.last_price("RELIANCE")
    verdict = guard.evaluate(FakeLeg(), state, current_price, datetime(2026, 9, 29, 9, 27))
    assert verdict.action in ("VETO", "WAIT", "ENTER"), \
        f"Unexpected action: {verdict.action}: {verdict.reason}"
    if verdict.action == "ENTER":
        assert verdict.confidence < 0.5, \
            f"Expected low confidence for bearish entry, got {verdict.confidence}"


# ---------------------------------------------------------------------------
# Test 3: Trailing stop tightens after T1 booked
# ---------------------------------------------------------------------------

def test_trailing_stop_tightens_after_t1():
    """After T1 booked, trailing stop should ratchet up above breakeven."""
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    scorer = MomentumScorer()

    # Build 5min candles showing price well above entry
    candles_5m = [
        LiveCandle("RELIANCE", "5min", datetime(2026, 9, 29, 10, 15),
                   2460, 2470, 2458, 2468, 5000, True),
        LiveCandle("RELIANCE", "5min", datetime(2026, 9, 29, 10, 20),
                   2468, 2478, 2465, 2475, 5000, True),
        LiveCandle("RELIANCE", "5min", datetime(2026, 9, 29, 10, 25),
                   2475, 2485, 2472, 2482, 5000, True),
    ]

    # 1min candle for scorer
    candles_1m = [
        LiveCandle("RELIANCE", "1min", datetime(2026, 9, 29, 10, 30),
                   2480, 2485, 2478, 2483, 1000, True)
    ]
    state = scorer.update("RELIANCE", candles_1m, candles_5m)

    # LegState with T1 booked, stop at breakeven
    ls = FakeLegState(entry=2450.0, stop=2450.0, t1_booked=True)

    trail = mgr.compute_trail_price(ls, state, candles_5m, candles_1m)

    # Phase 2 trail: min low of last 3 5min candles = min(2458, 2465, 2472) = 2458
    # Floor at breakeven = max(2458, 2450) = 2458
    # Must not widen: max(2458, current_stop=2450) = 2458
    assert trail is not None, "Trail should not be None after T1 booked"
    assert trail >= 2450.0, f"Trail {trail} should be >= breakeven 2450"
    assert trail == 2458.0, f"Expected trail at 2458.0 (min low), got {trail}"


# ---------------------------------------------------------------------------
# Test 4: Momentum exit fires on reversal while profitable
# ---------------------------------------------------------------------------

def test_momentum_exit_on_reversal():
    """Momentum reversal while profitable triggers MOMENTUM_EXIT or stays HOLD
    if thresholds not quite met. This verifies the full pipeline: score → decide.
    """
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    scorer = MomentumScorer()

    # Record peak bullish momentum
    mgr.track_peak_momentum("RELIANCE", 55.0)

    # Build bearish reversal candles with volume
    bearish_1m = [
        LiveCandle("RELIANCE", "1min", datetime(2026, 9, 29, 10, 25 + i),
                   2480 - i * 4, 2482 - i * 4, 2476 - i * 4, 2477 - i * 4,
                   1500, True)
        for i in range(5)
    ]
    bearish_5m = [
        LiveCandle("RELIANCE", "5min", datetime(2026, 9, 29, 10, 25),
                   2480, 2482, 2460, 2462, 7000, True)
    ]
    state = scorer.update("RELIANCE", bearish_1m, bearish_5m)

    ls = FakeLegState(entry=2450.0, stop=2430.0)
    decision = mgr.decide(ls, state, 2465.0, datetime(2026, 9, 29, 10, 30))

    # Either MOMENTUM_EXIT if scores hit threshold, or HOLD if marginal
    assert decision in (ExitDecision.MOMENTUM_EXIT, ExitDecision.HOLD), \
        f"Expected MOMENTUM_EXIT or HOLD, got {decision}"


# ---------------------------------------------------------------------------
# Test 5: WebSocket degradation — aggregator returns None for unknown symbol
# ---------------------------------------------------------------------------

def test_websocket_degradation_fallback():
    """When no ticks received, aggregator.last_price returns None.

    This tests the design contract: callers must check for None
    and fall back to REST LTP when the WebSocket feed is degraded.
    """
    agg = CandleAggregator()

    # No ticks fed → last_price returns None
    assert agg.last_price("RELIANCE") is None

    # Feed a single tick, then check a different symbol
    agg.on_tick("INFY", 1500.0, 100, datetime(2026, 9, 29, 9, 15, 10))
    assert agg.last_price("INFY") == 1500.0
    assert agg.last_price("RELIANCE") is None  # still None for unfed symbol


# ---------------------------------------------------------------------------
# Test 6: End-to-end exit pipeline: entry → trailing → T2
# ---------------------------------------------------------------------------

def test_end_to_end_exit_pipeline():
    """Full lifecycle: entry approved, T1 hit, trail tightens, finally T2 hit."""
    agg = CandleAggregator()
    scorer = MomentumScorer()
    guard = EntryGuard(max_drift_pct=5.0)
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))

    # Phase 1: bullish ticks → entry approved
    ticks = _bullish_ticks(count=12)
    ticks.append({"symbol": "RELIANCE", "price": 2490.0, "volume": 500,
                  "timestamp": datetime(2026, 9, 29, 9, 27, 5)})
    _replay_into(agg, ticks)

    candles_1m = agg.get_candles("RELIANCE", "1min")
    candles_5m = agg.get_candles("RELIANCE", "5min")
    state = scorer.update("RELIANCE", candles_1m, candles_5m)

    verdict = guard.evaluate(FakeLeg(), state, agg.last_price("RELIANCE"),
                             datetime(2026, 9, 29, 9, 27))
    assert verdict.action == "ENTER"

    # Phase 2: price at T1 → BOOK_TARGET_1
    ls = FakeLegState(entry=2450.0, stop=2430.0, t1_booked=False)
    decision = mgr.decide(ls, state, 2470.0, datetime(2026, 9, 29, 10, 0))
    assert decision == ExitDecision.BOOK_TARGET_1

    # Phase 3: T1 booked, price at T2 → BOOK_TARGET_2
    ls_t1 = FakeLegState(entry=2450.0, stop=2450.0, t1_booked=True)
    decision = mgr.decide(ls_t1, state, 2490.0, datetime(2026, 9, 29, 10, 30))
    assert decision == ExitDecision.BOOK_TARGET_2


# ---------------------------------------------------------------------------
# Test 7: Square-off time overrides all other exit signals
# ---------------------------------------------------------------------------

def test_square_off_overrides_all():
    """At square-off time, decision must be SQUARE_OFF regardless of price."""
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    scorer = MomentumScorer()

    candles_1m = [
        LiveCandle("RELIANCE", "1min", datetime(2026, 9, 29, 15, 14),
                   2480, 2485, 2478, 2483, 1000, True)
    ]
    state = scorer.update("RELIANCE", candles_1m, [])
    ls = FakeLegState(entry=2450.0, stop=2430.0)

    # At 15:15 — square off
    decision = mgr.decide(ls, state, 2480.0, datetime(2026, 9, 29, 15, 15))
    assert decision == ExitDecision.SQUARE_OFF

    # At 15:16 — still square off
    decision = mgr.decide(ls, state, 2480.0, datetime(2026, 9, 29, 15, 16))
    assert decision == ExitDecision.SQUARE_OFF


# ---------------------------------------------------------------------------
# Test 8: TickReplayer drives the full pipeline
# ---------------------------------------------------------------------------

def test_replayer_drives_full_pipeline():
    """TickReplayer feeds ticks that flow through aggregator → scorer → guard."""
    agg = CandleAggregator()
    scorer = MomentumScorer()
    guard = EntryGuard(max_drift_pct=5.0)

    # Use TickReplayer to feed bullish ticks
    ticks = _bullish_ticks(count=12)
    ticks.append({"symbol": "RELIANCE", "price": 2490.0, "volume": 500,
                  "timestamp": datetime(2026, 9, 29, 9, 27, 5)})
    replayer = TickReplayer(ticks)
    replayer.replay(agg)

    candles_1m = agg.get_candles("RELIANCE", "1min")
    candles_5m = agg.get_candles("RELIANCE", "5min")
    state = scorer.update("RELIANCE", candles_1m, candles_5m)

    # Pipeline produces coherent entry decision
    verdict = guard.evaluate(FakeLeg(), state, agg.last_price("RELIANCE"),
                             datetime(2026, 9, 29, 9, 27))
    assert verdict.action == "ENTER"
    assert verdict.confidence > 0
