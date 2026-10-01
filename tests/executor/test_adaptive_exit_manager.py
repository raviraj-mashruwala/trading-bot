from datetime import datetime, time
from enum import Enum

import pytest

from tradingbot.executor.adaptive_exit_manager import AdaptiveExitManager, ExitDecision
from tradingbot.executor.candle_aggregator import LiveCandle
from tradingbot.executor.momentum_scorer import SymbolState


def _state(**overrides) -> SymbolState:
    defaults = dict(
        symbol="RELIANCE", timestamp=datetime(2026, 9, 29, 10, 30),
        momentum_1m=30.0, momentum_5m=35.0,
        volume_ratio=1.2, volume_trend="stable",
        vwap=2450.0, vwap_position=0.2, price_vs_open=0.5,
        last_pattern_1m="none", last_pattern_5m="none",
        body_dominance=0.5, trend_alignment=True, strength="moderate",
    )
    defaults.update(overrides)
    return SymbolState(**defaults)


class FakeLegState:
    def __init__(self, direction="long", entry_fill_price=2450.0,
                 stop=2430.0, t1=2470.0, t2=2490.0,
                 target_1_booked=False, filled_qty=10):
        self.leg = type("Leg", (), {
            "direction": type("D", (), {"value": direction})(),
            "stop_loss": stop,
            "target_1": t1,
            "target_2": t2,
            "exit_before": time(15, 15),
        })()
        self.entry_fill_price = entry_fill_price
        self.current_stop = stop
        self.target_1_booked = target_1_booked
        self.filled_quantity = filled_qty


def test_square_off_takes_priority():
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    ls = FakeLegState()
    d = mgr.decide(ls, _state(), 2460.0, datetime(2026, 9, 29, 15, 16))
    assert d == ExitDecision.SQUARE_OFF


def test_stop_hit_long():
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    ls = FakeLegState(stop=2430.0)
    d = mgr.decide(ls, _state(), 2429.0, datetime(2026, 9, 29, 10, 30))
    assert d == ExitDecision.STOP_HIT


def test_stop_hit_short():
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    ls = FakeLegState(direction="short", entry_fill_price=2450.0, stop=2470.0)
    d = mgr.decide(ls, _state(), 2471.0, datetime(2026, 9, 29, 10, 30))
    assert d == ExitDecision.STOP_HIT


def test_target_2_hit():
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    ls = FakeLegState(target_1_booked=True, t2=2490.0)
    d = mgr.decide(ls, _state(), 2491.0, datetime(2026, 9, 29, 10, 30))
    assert d == ExitDecision.BOOK_TARGET_2


def test_target_1_hit():
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    ls = FakeLegState(t1=2470.0)
    d = mgr.decide(ls, _state(), 2471.0, datetime(2026, 9, 29, 10, 30))
    assert d == ExitDecision.BOOK_TARGET_1


def test_momentum_exit_long():
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    ls = FakeLegState(entry_fill_price=2450.0)
    # Record peak momentum
    mgr.track_peak_momentum("RELIANCE", 55.0)
    # Now momentum flipped
    st = _state(momentum_5m=-25.0, momentum_1m=-45.0, volume_ratio=1.3)
    d = mgr.decide(ls, st, 2465.0, datetime(2026, 9, 29, 10, 30))
    assert d == ExitDecision.MOMENTUM_EXIT


def test_momentum_exit_requires_profit():
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    ls = FakeLegState(entry_fill_price=2450.0)
    mgr.track_peak_momentum("RELIANCE", 55.0)
    st = _state(momentum_5m=-25.0, momentum_1m=-45.0, volume_ratio=1.3)
    # Price below entry — not profitable, so no momentum exit
    d = mgr.decide(ls, st, 2440.0, datetime(2026, 9, 29, 10, 30))
    assert d != ExitDecision.MOMENTUM_EXIT


def test_pattern_exit_long():
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    ls = FakeLegState(entry_fill_price=2450.0)
    st = _state(last_pattern_5m="bearish_engulf", volume_ratio=1.8)
    d = mgr.decide(ls, st, 2465.0, datetime(2026, 9, 29, 10, 30))
    assert d == ExitDecision.PATTERN_EXIT


def test_pattern_exit_needs_volume():
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    ls = FakeLegState(entry_fill_price=2450.0)
    st = _state(last_pattern_5m="bearish_engulf", volume_ratio=0.8)
    d = mgr.decide(ls, st, 2465.0, datetime(2026, 9, 29, 10, 30))
    assert d != ExitDecision.PATTERN_EXIT


def test_trail_phase2_uses_5min_lows():
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    candles_5m = [
        LiveCandle("RELIANCE", "5min", datetime(2026, 9, 29, 10, 15), 2460, 2470, 2455, 2468, 5000, True),
        LiveCandle("RELIANCE", "5min", datetime(2026, 9, 29, 10, 20), 2468, 2475, 2460, 2472, 5000, True),
        LiveCandle("RELIANCE", "5min", datetime(2026, 9, 29, 10, 25), 2472, 2480, 2462, 2478, 5000, True),
    ]
    ls = FakeLegState(entry_fill_price=2450.0, target_1_booked=True, stop=2450.0)
    trail = mgr.compute_trail_price(ls, _state(), candles_5m, [])
    # Should be min low of last 3 5min candles = 2455, but floor is breakeven (2450)
    assert trail == 2455.0


def test_trail_never_widens():
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    candles_5m = [
        LiveCandle("RELIANCE", "5min", datetime(2026, 9, 29, 10, 15), 2460, 2470, 2440, 2468, 5000, True),
        LiveCandle("RELIANCE", "5min", datetime(2026, 9, 29, 10, 20), 2468, 2475, 2435, 2472, 5000, True),
        LiveCandle("RELIANCE", "5min", datetime(2026, 9, 29, 10, 25), 2472, 2480, 2430, 2478, 5000, True),
    ]
    ls = FakeLegState(entry_fill_price=2450.0, target_1_booked=True, stop=2460.0)
    trail = mgr.compute_trail_price(ls, _state(), candles_5m, [])
    # Min low is 2430, but current stop is 2460 — never widen
    assert trail == 2460.0


def test_hold_default():
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    ls = FakeLegState()
    d = mgr.decide(ls, _state(), 2455.0, datetime(2026, 9, 29, 10, 30))
    assert d == ExitDecision.HOLD


def test_momentum_peak_not_overwritten_by_reversal():
    """F1: abs() peak tracking bug — violent reversal should not clobber peak."""
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    ls = FakeLegState(entry_fill_price=2450.0)
    # Peak momentum at +55 during uptrend
    mgr.track_peak_momentum("RELIANCE", 55.0)
    # Violent reversal — momentum swings to -60
    mgr.track_peak_momentum("RELIANCE", -60.0)
    # Momentum exit should still fire for LONG (peak_high was 55 > 40)
    st = _state(momentum_5m=-25.0, momentum_1m=-45.0, volume_ratio=1.3)
    d = mgr.decide(ls, st, 2465.0, datetime(2026, 9, 29, 10, 30))
    assert d == ExitDecision.MOMENTUM_EXIT


def test_momentum_exit_short():
    """F1 companion: SHORT momentum exit uses negative peak correctly."""
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    ls = FakeLegState(direction="short", entry_fill_price=2450.0, stop=2470.0,
                      t1=2430.0, t2=2410.0)
    # Peak negative momentum at -55 during downtrend
    mgr.track_peak_momentum("RELIANCE", -55.0)
    # Then positive spike — should not clobber negative peak
    mgr.track_peak_momentum("RELIANCE", 50.0)
    # Momentum reversal for SHORT
    st = _state(momentum_5m=25.0, momentum_1m=45.0, volume_ratio=1.3)
    d = mgr.decide(ls, st, 2435.0, datetime(2026, 9, 29, 10, 30))
    assert d == ExitDecision.MOMENTUM_EXIT


def test_trail_stop_returned_by_decide():
    """F2: decide() should return TRAIL_STOP when trail tightens post-T1."""
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    # Post-T1, current stop at breakeven 2450
    ls = FakeLegState(entry_fill_price=2450.0, target_1_booked=True,
                      stop=2450.0, t2=2490.0)
    candles_5m = [
        LiveCandle("RELIANCE", "5min", datetime(2026, 9, 29, 10, 15), 2460, 2470, 2458, 2468, 5000, True),
        LiveCandle("RELIANCE", "5min", datetime(2026, 9, 29, 10, 20), 2468, 2475, 2462, 2472, 5000, True),
        LiveCandle("RELIANCE", "5min", datetime(2026, 9, 29, 10, 25), 2472, 2480, 2465, 2478, 5000, True),
    ]
    st = _state()
    d = mgr.decide(ls, st, 2475.0, datetime(2026, 9, 29, 10, 30),
                   candles_5m=candles_5m, candles_1m=[])
    assert d == ExitDecision.TRAIL_STOP


def test_trail_phase3_near_t2():
    """F3: Phase 3 — price within 0.3% of T2, 1min candles tighten trail."""
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    # T2 = 2490. Price at 2488 is ~0.08% away (< 0.3%)
    ls = FakeLegState(entry_fill_price=2450.0, target_1_booked=True,
                      stop=2460.0, t2=2490.0)
    candles_1m = [
        LiveCandle("RELIANCE", "1min", datetime(2026, 9, 29, 10, 28), 2485, 2489, 2483, 2487, 1000, True),
        LiveCandle("RELIANCE", "1min", datetime(2026, 9, 29, 10, 29), 2487, 2490, 2485, 2488, 1000, True),
    ]
    candles_5m = [
        LiveCandle("RELIANCE", "5min", datetime(2026, 9, 29, 10, 15), 2460, 2470, 2455, 2468, 5000, True),
        LiveCandle("RELIANCE", "5min", datetime(2026, 9, 29, 10, 20), 2468, 2475, 2460, 2472, 5000, True),
        LiveCandle("RELIANCE", "5min", datetime(2026, 9, 29, 10, 25), 2472, 2480, 2465, 2478, 5000, True),
    ]
    trail = mgr.compute_trail_price(ls, _state(), candles_5m, candles_1m)
    # Phase 3: min low of last 2 1min candles = min(2483, 2485) = 2483
    # Floor = max(2483, 2450) = 2483; never-widen = max(2483, 2460) = 2483
    assert trail == 2483.0


def test_trail_phase3_boundary_beyond_0_3_pct():
    """F3: Boundary — price >0.3% from T2 should NOT trigger phase 3, falls to phase 2."""
    mgr = AdaptiveExitManager(square_off_time=time(15, 15))
    # T2 = 2490. abs(2482 - 2490)/2490*100 = 0.321% > 0.3 — phase 3 skipped
    ls = FakeLegState(entry_fill_price=2450.0, target_1_booked=True,
                      stop=2455.0, t2=2490.0)
    candles_1m = [
        LiveCandle("RELIANCE", "1min", datetime(2026, 9, 29, 10, 28), 2480, 2484, 2478, 2481, 1000, True),
        LiveCandle("RELIANCE", "1min", datetime(2026, 9, 29, 10, 29), 2481, 2483, 2479, 2482.0, 1000, True),
    ]
    candles_5m = [
        LiveCandle("RELIANCE", "5min", datetime(2026, 9, 29, 10, 15), 2460, 2470, 2458, 2468, 5000, True),
        LiveCandle("RELIANCE", "5min", datetime(2026, 9, 29, 10, 20), 2468, 2475, 2462, 2472, 5000, True),
        LiveCandle("RELIANCE", "5min", datetime(2026, 9, 29, 10, 25), 2472, 2480, 2465, 2478, 5000, True),
    ]
    trail = mgr.compute_trail_price(ls, _state(), candles_5m, candles_1m)
    # Should fall to phase 2: min low of 5m[-3:] = min(2458,2462,2465) = 2458
    # Floor = max(2458, 2450) = 2458; never-widen = max(2458, 2455) = 2458
    assert trail == 2458.0


def test_exit_decision_has_new_variants():
    assert hasattr(ExitDecision, "TRAIL_STOP")
    assert hasattr(ExitDecision, "MOMENTUM_EXIT")
    assert hasattr(ExitDecision, "PATTERN_EXIT")
    # Old variants preserved
    assert hasattr(ExitDecision, "HOLD")
    assert hasattr(ExitDecision, "BOOK_TARGET_1")
    assert hasattr(ExitDecision, "SQUARE_OFF")
