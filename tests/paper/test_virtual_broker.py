import pytest

from tradingbot.core.broker import OrderSide, OrderStatus, OrderType
from tradingbot.core.config import PaperConfig
from tradingbot.core.models import Direction
from tradingbot.paper.virtual_broker import VirtualBroker


class PriceFeed:
    """A mutable price source the test drives by hand."""

    def __init__(self, prices):
        self.prices = dict(prices)

    def set(self, symbol, price):
        self.prices[symbol] = price

    def __call__(self, symbol):
        return self.prices[symbol]


def make_broker(prices=None, slippage_pct=0.05, capital=400000.0):
    feed = PriceFeed(prices or {"RELIANCE": 100.0})
    config = PaperConfig(slippage_pct=slippage_pct, initial_capital=capital)
    return VirtualBroker(config, price_feed=feed), feed


def test_a_market_buy_fills_immediately_with_slippage():
    broker, _ = make_broker({"RELIANCE": 100.0})

    order_id = broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)
    order = broker.get_order(order_id)

    assert order.status is OrderStatus.COMPLETE
    assert order.filled_price == pytest.approx(100.05)


def test_a_market_sell_fills_immediately_with_slippage_in_the_other_direction():
    broker, _ = make_broker({"RELIANCE": 100.0})

    order_id = broker.place_order("RELIANCE", OrderSide.SELL, OrderType.MARKET, 10)

    assert broker.get_order(order_id).filled_price == pytest.approx(99.95)


def test_a_limit_buy_rests_until_the_price_trades_down_to_it():
    broker, feed = make_broker({"RELIANCE": 105.0})

    order_id = broker.place_order("RELIANCE", OrderSide.BUY, OrderType.LIMIT, 10, price=100.0)
    assert broker.get_order(order_id).status is OrderStatus.OPEN

    feed.set("RELIANCE", 99.5)
    broker.advance()

    order = broker.get_order(order_id)
    assert order.status is OrderStatus.COMPLETE
    assert order.filled_price == pytest.approx(100.0)


def test_a_limit_sell_rests_until_the_price_trades_up_to_it():
    broker, feed = make_broker({"RELIANCE": 95.0})

    order_id = broker.place_order("RELIANCE", OrderSide.SELL, OrderType.LIMIT, 10, price=100.0)
    assert broker.get_order(order_id).status is OrderStatus.OPEN

    feed.set("RELIANCE", 101.0)
    broker.advance()

    assert broker.get_order(order_id).status is OrderStatus.COMPLETE


def test_a_stop_loss_sell_triggers_when_the_price_falls_through_it():
    broker, feed = make_broker({"RELIANCE": 100.0})
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    stop_id = broker.place_order(
        "RELIANCE", OrderSide.SELL, OrderType.SL, 10, trigger_price=95.0
    )
    feed.set("RELIANCE", 94.0)
    broker.advance()

    assert broker.get_order(stop_id).status is OrderStatus.COMPLETE
    assert broker.get_positions() == []


def test_a_filled_buy_creates_a_long_position():
    broker, _ = make_broker({"RELIANCE": 100.0})

    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)
    positions = broker.get_positions()

    assert len(positions) == 1
    assert positions[0].direction is Direction.LONG
    assert positions[0].quantity == 10


def test_selling_the_full_quantity_closes_the_position():
    broker, _ = make_broker({"RELIANCE": 100.0})
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    broker.place_order("RELIANCE", OrderSide.SELL, OrderType.MARKET, 10)

    assert broker.get_positions() == []


def test_selling_part_of_the_quantity_leaves_the_remainder_open():
    broker, _ = make_broker({"RELIANCE": 100.0})
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    broker.place_order("RELIANCE", OrderSide.SELL, OrderType.MARKET, 4)

    assert broker.get_positions()[0].quantity == 6


def test_cancelling_a_resting_order_stops_it_from_filling():
    broker, feed = make_broker({"RELIANCE": 105.0})
    order_id = broker.place_order("RELIANCE", OrderSide.BUY, OrderType.LIMIT, 10, price=100.0)

    broker.cancel_order(order_id)
    feed.set("RELIANCE", 99.0)
    broker.advance()

    assert broker.get_order(order_id).status is OrderStatus.CANCELLED
    assert broker.get_positions() == []


def test_cancelling_an_already_filled_order_is_a_no_op():
    broker, _ = make_broker({"RELIANCE": 100.0})
    order_id = broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    broker.cancel_order(order_id)

    assert broker.get_order(order_id).status is OrderStatus.COMPLETE


def test_buying_reduces_the_available_margin():
    broker, _ = make_broker({"RELIANCE": 100.0}, capital=400000.0)

    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 100)

    assert broker.available_margin() < 400000.0


def test_realised_pnl_is_recorded_when_a_position_closes_at_a_profit():
    broker, feed = make_broker({"RELIANCE": 100.0}, slippage_pct=0.0)
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    feed.set("RELIANCE", 110.0)
    broker.place_order("RELIANCE", OrderSide.SELL, OrderType.MARKET, 10)

    assert broker.realised_pnl == pytest.approx(100.0)


def test_realised_pnl_is_negative_when_a_position_closes_at_a_loss():
    broker, feed = make_broker({"RELIANCE": 100.0}, slippage_pct=0.0)
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    feed.set("RELIANCE", 90.0)
    broker.place_order("RELIANCE", OrderSide.SELL, OrderType.MARKET, 10)

    assert broker.realised_pnl == pytest.approx(-100.0)


def test_square_off_closes_a_long_at_market():
    broker, _ = make_broker({"RELIANCE": 100.0})
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    broker.square_off("RELIANCE")

    assert broker.get_positions() == []


def test_square_off_closes_a_short_at_market():
    broker, _ = make_broker({"RELIANCE": 100.0})
    broker.place_order("RELIANCE", OrderSide.SELL, OrderType.MARKET, 10)
    assert broker.get_positions()[0].direction is Direction.SHORT

    broker.square_off("RELIANCE")

    assert broker.get_positions() == []


def test_square_off_on_a_symbol_with_no_position_is_a_no_op():
    broker, _ = make_broker({"RELIANCE": 100.0})

    broker.square_off("RELIANCE")

    assert broker.get_positions() == []


def test_get_ltp_returns_the_feed_price():
    broker, feed = make_broker({"RELIANCE": 100.0})

    feed.set("RELIANCE", 123.45)

    assert broker.get_ltp("RELIANCE") == pytest.approx(123.45)


def test_get_order_for_an_unknown_id_returns_none():
    broker, _ = make_broker()

    assert broker.get_order("does-not-exist") is None
