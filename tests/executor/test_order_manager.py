from datetime import time

import pytest

from tradingbot.core.broker import OrderSide, OrderStatus, OrderType
from tradingbot.core.config import PaperConfig
from tradingbot.core.models import Direction, EntryType, StrategyName, TradeLeg
from tradingbot.executor.order_manager import OrderManager
from tradingbot.paper.virtual_broker import VirtualBroker


def make_leg(direction=Direction.LONG, entry_type=EntryType.LIMIT, quantity=10) -> TradeLeg:
    return TradeLeg(
        symbol="RELIANCE",
        exchange="NSE",
        strategy=StrategyName.BREAKOUT,
        direction=direction,
        entry_price=100.0,
        entry_type=entry_type,
        stop_loss=95.0 if direction is Direction.LONG else 105.0,
        target_1=110.0 if direction is Direction.LONG else 90.0,
        target_2=115.0 if direction is Direction.LONG else 85.0,
        quantity=quantity,
        risk_amount=50.0,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        max_entry_wait=time(11, 0),
        exit_before=time(15, 10),
        confidence=0.8,
        reasoning="Test leg.",
    )


def make_manager(price=100.0):
    prices = {"RELIANCE": price}
    broker = VirtualBroker(PaperConfig(slippage_pct=0.0, initial_capital=400000.0), lambda s: prices[s])
    return OrderManager(broker), broker, prices


def test_a_long_entry_is_submitted_as_a_buy():
    manager, broker, _ = make_manager()

    order_id = manager.submit_entry(make_leg(Direction.LONG))

    assert broker.get_order(order_id).side is OrderSide.BUY


def test_a_short_entry_is_submitted_as_a_sell():
    manager, broker, _ = make_manager()

    order_id = manager.submit_entry(make_leg(Direction.SHORT))

    assert broker.get_order(order_id).side is OrderSide.SELL


def test_a_limit_entry_uses_the_planned_entry_price():
    manager, broker, _ = make_manager(price=105.0)

    order_id = manager.submit_entry(make_leg(entry_type=EntryType.LIMIT))
    order = broker.get_order(order_id)

    assert order.order_type is OrderType.LIMIT
    assert order.price == pytest.approx(100.0)


def test_a_stop_entry_is_submitted_with_a_trigger_price():
    manager, broker, _ = make_manager(price=95.0)

    order_id = manager.submit_entry(make_leg(entry_type=EntryType.STOP))
    order = broker.get_order(order_id)

    assert order.order_type is OrderType.SL
    assert order.trigger_price == pytest.approx(100.0)


def test_a_stop_for_a_long_position_is_a_sell_with_the_stop_trigger():
    manager, broker, _ = make_manager()

    order_id = manager.submit_stop(make_leg(Direction.LONG), quantity=10)
    order = broker.get_order(order_id)

    assert order.side is OrderSide.SELL
    assert order.order_type is OrderType.SL
    assert order.trigger_price == pytest.approx(95.0)


def test_a_stop_for_a_short_position_is_a_buy():
    manager, broker, _ = make_manager()

    order_id = manager.submit_stop(make_leg(Direction.SHORT), quantity=10)

    assert broker.get_order(order_id).side is OrderSide.BUY


def test_exit_at_market_closes_a_long_with_a_sell():
    manager, broker, _ = make_manager()
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    order_id = manager.exit_at_market(make_leg(Direction.LONG), quantity=10)
    order = broker.get_order(order_id)

    assert order.side is OrderSide.SELL
    assert order.order_type is OrderType.MARKET
    assert broker.get_positions() == []


def test_exit_at_market_can_close_part_of_a_position():
    manager, broker, _ = make_manager()
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    manager.exit_at_market(make_leg(Direction.LONG), quantity=5)

    assert broker.get_positions()[0].quantity == 5


def test_cancel_marks_a_resting_order_cancelled():
    manager, broker, _ = make_manager(price=105.0)
    order_id = manager.submit_entry(make_leg())

    manager.cancel(order_id)

    assert broker.get_order(order_id).status is OrderStatus.CANCELLED


def test_order_status_reports_the_current_status():
    manager, broker, prices = make_manager(price=105.0)
    order_id = manager.submit_entry(make_leg())

    assert manager.order_status(order_id) is OrderStatus.OPEN

    prices["RELIANCE"] = 99.0
    broker.advance()

    assert manager.order_status(order_id) is OrderStatus.COMPLETE


def test_order_status_for_an_unknown_id_is_none():
    manager, _, _ = make_manager()

    assert manager.order_status("nope") is None
