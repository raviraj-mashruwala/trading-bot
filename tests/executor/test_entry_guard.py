from datetime import datetime, time
import pytest
from tradingbot.executor.entry_guard import EntryGuard, EntryVerdict
from tradingbot.executor.momentum_scorer import SymbolState


def _state(**overrides) -> SymbolState:
    defaults = dict(
        symbol="RELIANCE", timestamp=datetime(2026, 9, 29, 9, 20),
        momentum_1m=30.0, momentum_5m=35.0,
        volume_ratio=1.2, volume_trend="stable",
        vwap=2450.0, vwap_position=0.2, price_vs_open=0.5,
        last_pattern_1m="none", last_pattern_5m="none",
        body_dominance=0.5, trend_alignment=True, strength="moderate",
    )
    defaults.update(overrides)
    return SymbolState(**defaults)


class FakeLeg:
    def __init__(self, direction="LONG", entry_price=2450.0,
                 entry_window_end=time(10, 0),
                 max_entry_wait=time(10, 30)):
        self.direction = type("D", (), {"value": direction})()
        self.entry_price = entry_price
        self.entry_window_end = entry_window_end
        self.max_entry_wait = max_entry_wait


def test_rule1_entry_window_expired():
    guard = EntryGuard(max_drift_pct=1.0)
    leg = FakeLeg(entry_window_end=time(9, 15))
    v = guard.evaluate(leg, _state(), 2450.0, datetime(2026, 9, 29, 9, 20))
    assert v.action == "VETO"
    assert "window" in v.reason.lower()


def test_rule2_price_drifted_too_far():
    guard = EntryGuard(max_drift_pct=1.0)
    leg = FakeLeg(entry_price=2450.0)
    # Price drifted 3% from plan
    v = guard.evaluate(leg, _state(), 2525.0, datetime(2026, 9, 29, 9, 20))
    assert v.action == "VETO"
    assert "drift" in v.reason.lower()


def test_rule3_long_into_strong_selling():
    guard = EntryGuard(max_drift_pct=5.0)
    leg = FakeLeg(direction="LONG")
    v = guard.evaluate(leg, _state(momentum_5m=-65.0), 2450.0, datetime(2026, 9, 29, 9, 20))
    assert v.action == "VETO"


def test_rule4_short_into_strong_buying():
    guard = EntryGuard(max_drift_pct=5.0)
    leg = FakeLeg(direction="SHORT")
    v = guard.evaluate(leg, _state(momentum_5m=65.0), 2450.0, datetime(2026, 9, 29, 9, 20))
    assert v.action == "VETO"


def test_rule5_low_volume_waits():
    guard = EntryGuard(max_drift_pct=5.0)
    leg = FakeLeg()
    v = guard.evaluate(leg, _state(volume_ratio=0.2), 2450.0, datetime(2026, 9, 29, 9, 20))
    assert v.action == "WAIT"


def test_rule6_choppy_no_alignment():
    guard = EntryGuard(max_drift_pct=5.0)
    leg = FakeLeg()
    v = guard.evaluate(leg, _state(trend_alignment=False, body_dominance=0.2), 2450.0, datetime(2026, 9, 29, 9, 20))
    assert v.action == "WAIT"


def test_rule7_long_falling_below_vwap():
    guard = EntryGuard(max_drift_pct=5.0)
    leg = FakeLeg(direction="LONG")
    v = guard.evaluate(leg, _state(vwap_position=-0.9, momentum_1m=-35.0), 2450.0, datetime(2026, 9, 29, 9, 20))
    assert v.action == "WAIT"


def test_rule8_bearish_pattern_for_long():
    guard = EntryGuard(max_drift_pct=5.0)
    leg = FakeLeg(direction="LONG")
    v = guard.evaluate(leg, _state(last_pattern_5m="bearish_engulf"), 2450.0, datetime(2026, 9, 29, 9, 20))
    assert v.action == "WAIT"


def test_rule10_clean_entry():
    guard = EntryGuard(max_drift_pct=5.0)
    leg = FakeLeg(direction="LONG")
    v = guard.evaluate(leg, _state(momentum_1m=40.0, momentum_5m=45.0, volume_ratio=1.5, trend_alignment=True), 2450.0, datetime(2026, 9, 29, 9, 20))
    assert v.action == "ENTER"
    assert v.confidence > 0.6


def test_gray_zone_low_confidence():
    guard = EntryGuard(max_drift_pct=5.0)
    leg = FakeLeg(direction="LONG")
    # Mild positive momentum, nothing disqualifying, nothing strong
    v = guard.evaluate(leg, _state(momentum_1m=5.0, momentum_5m=8.0, volume_ratio=0.8, trend_alignment=True, body_dominance=0.4), 2450.0, datetime(2026, 9, 29, 9, 20))
    assert v.action == "ENTER"
    assert v.confidence < 0.4


def test_verdict_is_frozen():
    v = EntryVerdict(action="ENTER", reason="test", confidence=0.8, reassess_after=0)
    with pytest.raises(AttributeError):
        v.action = "VETO"


def test_max_entry_wait_auto_veto():
    guard = EntryGuard(max_drift_pct=5.0)
    leg = FakeLeg(max_entry_wait=time(9, 18))
    v = guard.evaluate(leg, _state(volume_ratio=0.2), 2450.0, datetime(2026, 9, 29, 9, 20))
    # Even though volume_ratio=0.2 would be WAIT, max_entry_wait expired -> VETO
    assert v.action == "VETO"
    assert "wait" in v.reason.lower() or "expired" in v.reason.lower()
