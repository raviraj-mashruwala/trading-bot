import pytest
from unittest.mock import MagicMock
from tradingbot.execution.kite_executor import KiteExecutor


def test_place_entry_long():
    client = MagicMock()
    client.place_order.return_value = "ORD001"
    cap_mgr = MagicMock()
    cap_mgr.check_margin.return_value = (True, "")
    executor = KiteExecutor(client, cap_mgr, max_drift_pct=2.0)

    order_id = executor.place_entry(
        symbol="RELIANCE", exchange="NSE", direction="long",
        entry_price=2500, stop_loss=2480, quantity=10,
        order_type="LIMIT", current_price=2502,
    )
    assert order_id == "ORD001"
    client.place_order.assert_called_once()


def test_place_entry_rejects_drifted_price():
    client = MagicMock()
    cap_mgr = MagicMock()
    cap_mgr.check_margin.return_value = (True, "")
    executor = KiteExecutor(client, cap_mgr, max_drift_pct=2.0)

    order_id = executor.place_entry(
        symbol="RELIANCE", exchange="NSE", direction="long",
        entry_price=2500, stop_loss=2480, quantity=10,
        order_type="LIMIT", current_price=2600,  # 4% drift
    )
    assert order_id is None


def test_place_entry_rejects_insufficient_margin():
    client = MagicMock()
    cap_mgr = MagicMock()
    cap_mgr.check_margin.return_value = (False, "insufficient margin")
    executor = KiteExecutor(client, cap_mgr, max_drift_pct=2.0)

    order_id = executor.place_entry(
        symbol="TCS", exchange="NSE", direction="long",
        entry_price=3500, stop_loss=3470, quantity=100,
        order_type="LIMIT", current_price=3500,
    )
    assert order_id is None


def test_place_entry_short():
    client = MagicMock()
    client.place_order.return_value = "ORD002"
    cap_mgr = MagicMock()
    cap_mgr.check_margin.return_value = (True, "")
    executor = KiteExecutor(client, cap_mgr, max_drift_pct=2.0)

    order_id = executor.place_entry(
        symbol="INFY", exchange="NSE", direction="short",
        entry_price=1800, stop_loss=1820, quantity=20,
        order_type="LIMIT", current_price=1798,
    )
    assert order_id == "ORD002"
    call_kwargs = client.place_order.call_args
    assert call_kwargs.kwargs["transaction_type"] == "SELL"


def test_place_exit_long():
    client = MagicMock()
    client.place_order.return_value = "EXIT001"
    cap_mgr = MagicMock()
    executor = KiteExecutor(client, cap_mgr)

    order_id = executor.place_exit(
        symbol="RELIANCE", exchange="NSE", direction="long",
        quantity=10, price=2520, order_type="LIMIT",
    )
    assert order_id == "EXIT001"
    call_kwargs = client.place_order.call_args
    assert call_kwargs.kwargs["transaction_type"] == "SELL"


def test_cancel_order():
    client = MagicMock()
    cap_mgr = MagicMock()
    executor = KiteExecutor(client, cap_mgr)

    result = executor.cancel_order("ORD001")
    assert result is True
    client.cancel_order.assert_called_once_with("regular", "ORD001")


def test_modify_order():
    client = MagicMock()
    cap_mgr = MagicMock()
    executor = KiteExecutor(client, cap_mgr)

    result = executor.modify_order("ORD001", price=2510)
    assert result is True
    client.modify_order.assert_called_once()


def test_place_entry_handles_broker_exception():
    client = MagicMock()
    client.place_order.side_effect = Exception("Broker error")
    cap_mgr = MagicMock()
    cap_mgr.check_margin.return_value = (True, "")
    executor = KiteExecutor(client, cap_mgr, max_drift_pct=5.0)

    order_id = executor.place_entry(
        symbol="RELIANCE", exchange="NSE", direction="long",
        entry_price=2500, stop_loss=2480, quantity=10,
        order_type="LIMIT", current_price=2500,
    )
    assert order_id is None
