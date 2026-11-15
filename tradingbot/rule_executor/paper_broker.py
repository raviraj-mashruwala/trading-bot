"""Paper broker for the rule executor.

Subclass of the shared VirtualBroker. The only change: a marketable limit order fills at
the current price plus slippage, not at its (deliberately far) limit price. The base class
fills a SELL limit placed 1% below LTP at that limit, which would book 1% of fake slippage.
"""

from __future__ import annotations

from datetime import datetime

from tradingbot.core.broker import Order, OrderSide, OrderType
from tradingbot.core.models import Direction, Position
from tradingbot.paper.virtual_broker import VirtualBroker


class RulePaperBroker(VirtualBroker):

    def _try_fill(self, order: Order) -> None:
        if order.order_type is OrderType.LIMIT:
            price = self.price_feed(order.symbol)
            if order.side is OrderSide.BUY and price <= order.price:
                self._fill(order, min(order.price, self._slipped(price, order.side)))
            elif order.side is OrderSide.SELL and price >= order.price:
                self._fill(order, max(order.price, self._slipped(price, order.side)))
            return
        super()._try_fill(order)

    def seed_position(self, symbol: str, direction: Direction, quantity: int, price: float,
                      entered_at: datetime) -> None:
        """Recreate a paper position recorded before a restart."""
        self._positions[symbol] = Position(
            symbol=symbol, direction=direction, quantity=quantity, entry_price=price,
            stop_loss=0.0, target_1=0.0, target_2=0.0, entered_at=entered_at,
        )
