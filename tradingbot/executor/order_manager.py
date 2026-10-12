"""Translates trade legs into broker orders. No decisions are made here."""

from __future__ import annotations

import logging

from tradingbot.core.broker import BrokerInterface, OrderSide, OrderStatus, OrderType
from tradingbot.core.models import Direction, EntryType, TradeLeg

logger = logging.getLogger(__name__)


def entry_side(direction: Direction) -> OrderSide:
    return OrderSide.BUY if direction is Direction.LONG else OrderSide.SELL


def exit_side(direction: Direction) -> OrderSide:
    return OrderSide.SELL if direction is Direction.LONG else OrderSide.BUY


class OrderManager:
    """A thin, mechanical layer between leg intent and broker calls."""

    def __init__(self, broker: BrokerInterface) -> None:
        self.broker = broker

    def submit_entry(self, leg: TradeLeg) -> str:
        side = entry_side(leg.direction)

        if leg.entry_type is EntryType.LIMIT:
            order_id = self.broker.place_order(
                symbol=leg.symbol,
                side=side,
                order_type=OrderType.LIMIT,
                quantity=leg.quantity,
                price=leg.entry_price,
            )
        else:
            order_id = self.broker.place_order(
                symbol=leg.symbol,
                side=side,
                order_type=OrderType.SL,
                quantity=leg.quantity,
                trigger_price=leg.entry_price,
            )

        logger.info(
            "submitted %s entry for %s x%d at %.2f (order %s)",
            side.value,
            leg.symbol,
            leg.quantity,
            leg.entry_price,
            order_id,
        )
        return order_id

    def submit_entry_market(self, leg: TradeLeg) -> str:
        """Place a market-like entry (LIMIT with 1% slippage)."""
        side = entry_side(leg.direction)
        ltp = self.broker.get_ltp(leg.symbol)
        slippage = ltp * 0.01
        if side == OrderSide.BUY:
            price = round(ltp + slippage, 2)
        else:
            price = round(ltp - slippage, 2)
        order_id = self.broker.place_order(
            symbol=leg.symbol,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=leg.quantity,
            price=price,
        )
        logger.info(
            "submitted %s market-like entry for %s x%d @ %.2f (order %s)",
            side.value, leg.symbol, leg.quantity, price, order_id,
        )
        return order_id

    def submit_stop(self, leg: TradeLeg, quantity: int, trigger_price: float | None = None) -> str:
        trigger = leg.stop_loss if trigger_price is None else trigger_price
        order_id = self.broker.place_order(
            symbol=leg.symbol,
            side=exit_side(leg.direction),
            order_type=OrderType.SL,
            quantity=quantity,
            trigger_price=trigger,
        )
        logger.info("submitted stop for %s x%d at %.2f (order %s)", leg.symbol, quantity, trigger, order_id)
        return order_id

    def exit_at_market(self, leg: TradeLeg, quantity: int) -> str:
        # Use LIMIT with 1% slippage — Kite rejects naked MARKET orders via API
        ltp = self.broker.get_ltp(leg.symbol)
        side = exit_side(leg.direction)
        slippage = ltp * 0.01
        if side == OrderSide.BUY:
            price = round(ltp + slippage, 2)
        else:
            price = round(ltp - slippage, 2)
        order_id = self.broker.place_order(
            symbol=leg.symbol,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=price,
        )
        logger.info("market-like exit for %s x%d @ %.2f (order %s)", leg.symbol, quantity, price, order_id)
        return order_id

    def cancel(self, order_id: str) -> None:
        self.broker.cancel_order(order_id)
        logger.info("cancelled order %s", order_id)

    def order_status(self, order_id: str) -> OrderStatus | None:
        order = self.broker.get_order(order_id)
        return order.status if order is not None else None
