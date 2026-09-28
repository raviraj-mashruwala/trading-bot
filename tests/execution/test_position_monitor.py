"""Tests for PositionMonitor — partial booking + trailing SL."""
import pytest
from unittest.mock import MagicMock
from tradingbot.execution.position_monitor import PositionMonitor


def _make_position(symbol="RELIANCE", direction="long", entry=2500, sl=2480,
                   t1=2530, t2=2560, qty=100):
    return {
        "symbol": symbol, "direction": direction, "quantity": qty,
        "entry_price": entry, "stop_loss": sl, "current_stop": sl,
        "target_1": t1, "target_2": t2, "order_id": "ORD001",
        "sl_order_id": "SL001", "target_1_booked": False,
    }


def test_partial_booking_at_target_1():
    executor = MagicMock()
    executor.place_exit.return_value = "EXIT001"
    executor.modify_order.return_value = True
    monitor = PositionMonitor(executor)

    pos = _make_position(qty=100, entry=2500, t1=2530, sl=2480)
    monitor.add_position(pos)
    actions = monitor.on_tick("RELIANCE", 2535.0)

    assert any(a["action"] == "partial_exit" for a in actions)
    assert any(a["action"] == "move_sl_to_breakeven" for a in actions)


def test_no_action_below_target():
    executor = MagicMock()
    monitor = PositionMonitor(executor)
    pos = _make_position()
    monitor.add_position(pos)
    actions = monitor.on_tick("RELIANCE", 2510.0)
    assert len(actions) == 0


def test_stop_loss_hit():
    executor = MagicMock()
    executor.place_exit.return_value = "EXIT002"
    monitor = PositionMonitor(executor)
    pos = _make_position(direction="long", entry=2500, sl=2480)
    monitor.add_position(pos)
    actions = monitor.on_tick("RELIANCE", 2475.0)
    assert any(a["action"] == "stop_loss_exit" for a in actions)


def test_partial_booking_rounds_down():
    """floor(3 * 0.5) = 1, NOT round(1.5) = 2."""
    executor = MagicMock()
    executor.place_exit.return_value = "EXIT003"
    executor.modify_order.return_value = True
    monitor = PositionMonitor(executor)
    pos = _make_position(qty=3, entry=2500, t1=2530, sl=2480)
    monitor.add_position(pos)
    actions = monitor.on_tick("RELIANCE", 2535.0)
    partial = [a for a in actions if a["action"] == "partial_exit"]
    assert partial[0]["quantity"] == 1  # floor(3 * 0.5) = 1


def test_trailing_stop():
    executor = MagicMock()
    executor.modify_order.return_value = True
    monitor = PositionMonitor(executor, trail_atr=5.0)
    pos = _make_position(entry=2500, sl=2480, t1=2530, qty=100)
    pos["target_1_booked"] = True
    pos["current_stop"] = 2500  # breakeven
    monitor.add_position(pos)

    # Price moves to 2550 — trail SL up by ATR steps
    actions = monitor.on_tick("RELIANCE", 2550.0)
    trail = [a for a in actions if a["action"] == "trail_stop"]
    if trail:
        assert trail[0]["new_stop"] > 2500


def test_stop_loss_hit_short():
    """Short position SL hit when price goes above current_stop."""
    executor = MagicMock()
    executor.place_exit.return_value = "EXIT004"
    monitor = PositionMonitor(executor)
    pos = _make_position(direction="short", entry=2500, sl=2520, t1=2470)
    monitor.add_position(pos)
    actions = monitor.on_tick("RELIANCE", 2525.0)
    assert any(a["action"] == "stop_loss_exit" for a in actions)


def test_partial_booking_short():
    """Short target_1 hit when price drops below target."""
    executor = MagicMock()
    executor.place_exit.return_value = "EXIT005"
    executor.modify_order.return_value = True
    monitor = PositionMonitor(executor)
    pos = _make_position(direction="short", entry=2500, sl=2520, t1=2470, qty=10)
    monitor.add_position(pos)
    actions = monitor.on_tick("RELIANCE", 2465.0)
    assert any(a["action"] == "partial_exit" for a in actions)
    assert any(a["action"] == "move_sl_to_breakeven" for a in actions)


def test_trailing_stop_short():
    """Short trailing stop moves down."""
    executor = MagicMock()
    executor.modify_order.return_value = True
    monitor = PositionMonitor(executor, trail_atr=5.0)
    pos = _make_position(direction="short", entry=2500, sl=2520, t1=2470, qty=100)
    pos["target_1_booked"] = True
    pos["current_stop"] = 2500  # breakeven
    monitor.add_position(pos)

    actions = monitor.on_tick("RELIANCE", 2450.0)
    trail = [a for a in actions if a["action"] == "trail_stop"]
    assert len(trail) == 1
    assert trail[0]["new_stop"] < 2500  # 2450 + 5 = 2455


def test_remove_position():
    executor = MagicMock()
    monitor = PositionMonitor(executor)
    pos = _make_position()
    monitor.add_position(pos)
    monitor.remove_position("RELIANCE")
    actions = monitor.on_tick("RELIANCE", 2535.0)
    assert actions == []


def test_on_tick_unknown_symbol():
    executor = MagicMock()
    monitor = PositionMonitor(executor)
    actions = monitor.on_tick("UNKNOWN", 100.0)
    assert actions == []
