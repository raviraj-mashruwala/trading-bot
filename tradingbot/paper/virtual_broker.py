"""Simulated broker. Same contract as KiteClient, so the executor cannot tell them apart.

Prices come from an injected callable, which lets paper trading run either against a
live tick feed or against replayed historical candles.
"""

from __future__ import annotations

import itertools
import logging
from typing import Callable

from tradingbot.core.broker import (
    BrokerInterface,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)
from tradingbot.core.config import PaperConfig
from tradingbot.core.models import Direction, Position, now_ist

logger = logging.getLogger(__name__)


class VirtualBroker(BrokerInterface):
    """Fills orders against a price feed, applying a fixed slippage assumption."""

    def __init__(self, config: PaperConfig, price_feed: Callable[[str], float]) -> None:
        self.config = config
        self.price_feed = price_feed
        self.cash = config.initial_capital
        self.realised_pnl = 0.0
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}
        self._ids = itertools.count(1)

    # ----- BrokerInterface --------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: int,
        price: float | None = None,
        trigger_price: float | None = None,
    ) -> str:
        order = Order(
            order_id=f"paper-{next(self._ids)}",
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
            status=OrderStatus.OPEN,
            filled_price=None,
            placed_at=now_ist(),
        )
        self._orders[order.order_id] = order

        if order_type is OrderType.MARKET:
            self._fill(order, self._slipped(self.price_feed(symbol), side))
        else:
            self._try_fill(order)

        return order.order_id

    def cancel_order(self, order_id: str) -> None:
        order = self._orders.get(order_id)
        if order is None or order.is_terminal:
            return
        order.status = OrderStatus.CANCELLED

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    def get_ltp(self, symbol: str) -> float:
        return float(self.price_feed(symbol))

    def available_margin(self) -> float:
        return self.cash

    def square_off(self, symbol: str) -> None:
        position = self._positions.get(symbol)
        if position is None:
            return
        side = OrderSide.SELL if position.direction is Direction.LONG else OrderSide.BUY
        self.place_order(symbol, side, OrderType.MARKET, position.quantity)

    # ----- Simulation control -----------------------------------------------------

    def advance(self) -> None:
        """Re-evaluate every resting order against the current price."""
        for order in list(self._orders.values()):
            if not order.is_terminal:
                self._try_fill(order)

    # ----- Internals --------------------------------------------------------------

    def _slipped(self, price: float, side: OrderSide) -> float:
        adjustment = price * (self.config.slippage_pct / 100.0)
        return price + adjustment if side is OrderSide.BUY else price - adjustment

    def _try_fill(self, order: Order) -> None:
        price = self.price_feed(order.symbol)

        if order.order_type is OrderType.LIMIT:
            if order.side is OrderSide.BUY and price <= order.price:
                self._fill(order, order.price)
            elif order.side is OrderSide.SELL and price >= order.price:
                self._fill(order, order.price)
            return

        if order.order_type is OrderType.SL:
            triggered = (
                price <= order.trigger_price
                if order.side is OrderSide.SELL
                else price >= order.trigger_price
            )
            if triggered:
                self._fill(order, self._slipped(price, order.side))

    def _fill(self, order: Order, fill_price: float) -> None:
        order.status = OrderStatus.COMPLETE
        order.filled_price = fill_price
        self._apply_to_position(order, fill_price)

    def _apply_to_position(self, order: Order, fill_price: float) -> None:
        symbol = order.symbol
        existing = self._positions.get(symbol)
        signed = order.quantity if order.side is OrderSide.BUY else -order.quantity

        if existing is None:
            self._positions[symbol] = Position(
                symbol=symbol,
                direction=Direction.LONG if signed > 0 else Direction.SHORT,
                quantity=abs(signed),
                entry_price=fill_price,
                stop_loss=0.0,
                target_1=0.0,
                target_2=0.0,
                entered_at=now_ist(),
            )
            self.cash -= abs(signed) * fill_price
            return

        held = existing.quantity if existing.direction is Direction.LONG else -existing.quantity
        net = held + signed

        closing = (held > 0 and signed < 0) or (held < 0 and signed > 0)
        if closing:
            closed_quantity = min(abs(signed), abs(held))
            delta = fill_price - existing.entry_price
            if existing.direction is Direction.SHORT:
                delta = -delta
            self.realised_pnl += delta * closed_quantity
            self.cash += closed_quantity * fill_price

        if net == 0:
            del self._positions[symbol]
            return

        existing.quantity = abs(net)
        existing.direction = Direction.LONG if net > 0 else Direction.SHORT
        if not closing:
            self.cash -= abs(signed) * fill_price
