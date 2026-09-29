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
    def __init__(self, direction="LONG", entry_fill_price=2450.0,
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
    ls = FakeLegState(direction="SHORT", entry_fill_price=2450.0, stop=2470.0)
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


def test_exit_decision_has_new_variants():
    assert hasattr(ExitDecision, "TRAIL_STOP")
    assert hasattr(ExitDecision, "MOMENTUM_EXIT")
    assert hasattr(ExitDecision, "PATTERN_EXIT")
    # Old variants preserved
    assert hasattr(ExitDecision, "HOLD")
    assert hasattr(ExitDecision, "BOOK_TARGET_1")
    assert hasattr(ExitDecision, "SQUARE_OFF")
