import inspect

import pytest

from tradingbot.core.broker import (
    BrokerError,
    BrokerInterface,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)


def test_broker_interface_cannot_be_instantiated():
    with pytest.raises(TypeError):
        BrokerInterface()


def test_broker_interface_declares_every_required_method():
    required = {
        "place_order",
        "cancel_order",
        "get_order",
        "get_positions",
        "get_ltp",
        "available_margin",
        "square_off",
    }

    assert required <= set(BrokerInterface.__abstractmethods__)


def test_place_order_signature_is_stable():
    params = list(inspect.signature(BrokerInterface.place_order).parameters)

    assert params == ["self", "symbol", "side", "order_type", "quantity", "price", "trigger_price"]


def test_order_side_and_type_values_are_stable_strings():
    assert OrderSide.BUY.value == "BUY"
    assert OrderSide.SELL.value == "SELL"
    assert OrderType.MARKET.value == "MARKET"
    assert OrderType.LIMIT.value == "LIMIT"
    assert OrderType.SL.value == "SL"


def test_order_status_values_are_stable_strings():
    assert OrderStatus.OPEN.value == "OPEN"
    assert OrderStatus.COMPLETE.value == "COMPLETE"
    assert OrderStatus.CANCELLED.value == "CANCELLED"
    assert OrderStatus.REJECTED.value == "REJECTED"


def test_order_is_terminal_only_once_it_stops_resting():
    from tradingbot.core.models import now_ist

    def make(status):
        return Order(
            order_id="1",
            symbol="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            price=100.0,
            trigger_price=None,
            status=status,
            filled_price=None,
            placed_at=now_ist(),
        )

    assert make(OrderStatus.OPEN).is_terminal is False
    assert make(OrderStatus.COMPLETE).is_terminal is True
    assert make(OrderStatus.CANCELLED).is_terminal is True
    assert make(OrderStatus.REJECTED).is_terminal is True


def test_broker_error_is_an_exception():
    assert issubclass(BrokerError, Exception)


def test_a_concrete_broker_can_be_instantiated():
    class StubBroker(BrokerInterface):
        def place_order(self, symbol, side, order_type, quantity, price=None, trigger_price=None):
            return "order-1"

        def cancel_order(self, order_id):
            return None

        def get_order(self, order_id):
            return None

        def get_positions(self):
            return []

        def get_ltp(self, symbol):
            return 100.0

        def available_margin(self):
            return 400000.0

        def square_off(self, symbol):
            return None

    assert isinstance(StubBroker(), BrokerInterface)
