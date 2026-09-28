"""Tests for SafetyManager.emergency_stop() — cancel orders + square off positions."""

import pytest
from unittest.mock import MagicMock

from tradingbot.execution.safety import SafetyManager


def test_emergency_stop_cancels_and_exits():
    executor = MagicMock()
    executor.cancel_order.return_value = True
    executor.place_exit.return_value = "EXIT001"

    mgr = SafetyManager(capital=400000, max_daily_loss_pct=2.0)
    pending_orders = ["ORD001", "ORD002"]
    open_positions = [
        {"symbol": "RELIANCE", "direction": "long", "quantity": 10, "exchange": "NSE"},
        {"symbol": "TCS", "direction": "short", "quantity": 5, "exchange": "NSE"},
    ]

    result = mgr.emergency_stop(executor, pending_orders, open_positions)

    assert executor.cancel_order.call_count == 2
    assert executor.place_exit.call_count == 2
    assert result["cancelled"] == 2
    assert result["squared_off"] == 2
    assert result["errors"] == 0


def test_emergency_stop_with_no_positions():
    executor = MagicMock()
    mgr = SafetyManager(capital=400000, max_daily_loss_pct=2.0)

    result = mgr.emergency_stop(executor, [], [])
    assert result["cancelled"] == 0
    assert result["squared_off"] == 0
    assert result["errors"] == 0
    executor.cancel_order.assert_not_called()
    executor.place_exit.assert_not_called()


def test_emergency_stop_handles_cancel_failure():
    executor = MagicMock()
    executor.cancel_order.side_effect = [True, Exception("API error")]
    executor.place_exit.return_value = "EXIT001"

    mgr = SafetyManager(capital=400000, max_daily_loss_pct=2.0)
    result = mgr.emergency_stop(executor, ["ORD1", "ORD2"], [])
    assert result["cancelled"] == 1  # one succeeded
    assert result["errors"] == 1


def test_emergency_stop_handles_exit_failure():
    executor = MagicMock()
    executor.place_exit.side_effect = Exception("Exit failed")

    mgr = SafetyManager(capital=400000, max_daily_loss_pct=2.0)
    positions = [
        {"symbol": "INFY", "direction": "long", "quantity": 20, "exchange": "NSE"},
    ]
    result = mgr.emergency_stop(executor, [], positions)
    assert result["squared_off"] == 0
    assert result["errors"] == 1


def test_emergency_stop_defaults_exchange_to_nse():
    """Position without 'exchange' key should default to NSE."""
    executor = MagicMock()
    executor.place_exit.return_value = "EXIT002"

    mgr = SafetyManager(capital=400000, max_daily_loss_pct=2.0)
    positions = [{"symbol": "SBIN", "direction": "long", "quantity": 15}]

    result = mgr.emergency_stop(executor, [], positions)
    assert result["squared_off"] == 1
    executor.place_exit.assert_called_once_with(
        symbol="SBIN", exchange="NSE", direction="long",
        quantity=15, order_type="MARKET",
    )
