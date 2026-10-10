"""Zerodha Kite Connect implementation of BrokerInterface."""

from __future__ import annotations

import logging

from tradingbot.core.broker import (
    BrokerError,
    BrokerInterface,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)
from tradingbot.core.models import Direction, Position, now_ist

logger = logging.getLogger(__name__)

EXCHANGE = "NSE"
PRODUCT_INTRADAY = "MIS"
VARIETY_REGULAR = "regular"

KITE_STATUS_MAP = {
    "COMPLETE": OrderStatus.COMPLETE,
    "CANCELLED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
}


class KiteClient(BrokerInterface):
    """Wraps kiteconnect. All orders are intraday (MIS) on NSE."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        access_token: str | None = None,
        kite=None,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        if kite is not None:
            self.kite = kite
        else:
            from kiteconnect import KiteConnect

            self.kite = KiteConnect(api_key=api_key)
            if access_token:
                self.kite.set_access_token(access_token)

    def login_url(self) -> str:
        """The URL the user opens to authorise this app."""
        return self.kite.login_url()

    def complete_login(self, request_token: str) -> str:
        """Exchange a request token for an access token and return it."""
        session = self.kite.generate_session(request_token, api_secret=self.api_secret)
        access_token = session["access_token"]
        self.kite.set_access_token(access_token)
        return access_token

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: int,
        price: float | None = None,
        trigger_price: float | None = None,
    ) -> str:
        try:
            return str(
                self.kite.place_order(
                    variety=VARIETY_REGULAR,
                    exchange=EXCHANGE,
                    tradingsymbol=symbol,
                    transaction_type=side.value,
                    quantity=quantity,
                    product=PRODUCT_INTRADAY,
                    order_type=order_type.value,
                    price=price,
                    trigger_price=trigger_price,
                )
            )
        except Exception as exc:  # noqa: BLE001 - normalised into BrokerError
            raise BrokerError(f"failed to place {side.value} order for {symbol}: {exc}") from exc

    def cancel_order(self, order_id: str) -> None:
        try:
            self.kite.cancel_order(variety=VARIETY_REGULAR, order_id=order_id)
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"failed to cancel order {order_id}: {exc}") from exc

    def get_order(self, order_id: str) -> Order | None:
        try:
            history = self.kite.order_history(order_id=order_id)
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"failed to fetch order {order_id}: {exc}") from exc

        if not history:
            return None

        latest = history[-1]
        return Order(
            order_id=str(latest["order_id"]),
            symbol=latest["tradingsymbol"],
            side=OrderSide(latest["transaction_type"]),
            order_type=OrderType(latest["order_type"]),
            quantity=int(latest["quantity"]),
            price=float(latest.get("price") or 0.0) or None,
            trigger_price=float(latest.get("trigger_price") or 0.0) or None,
            status=KITE_STATUS_MAP.get(latest["status"], OrderStatus.OPEN),
            filled_price=float(latest.get("average_price") or 0.0) or None,
            filled_quantity=int(latest.get("filled_quantity") or latest.get("quantity") or 0),
            placed_at=now_ist(),
        )

    def get_positions(self) -> list[Position]:
        try:
            payload = self.kite.positions()
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"failed to fetch positions: {exc}") from exc

        positions: list[Position] = []
        for row in payload.get("day", []):
            quantity = int(row["quantity"])
            if quantity == 0:
                continue
            positions.append(
                Position(
                    symbol=row["tradingsymbol"],
                    direction=Direction.LONG if quantity > 0 else Direction.SHORT,
                    quantity=abs(quantity),
                    entry_price=float(row["average_price"]),
                    stop_loss=0.0,
                    target_1=0.0,
                    target_2=0.0,
                    entered_at=now_ist(),
                )
            )
        return positions

    def get_ltp(self, symbol: str) -> float:
        key = f"{EXCHANGE}:{symbol}"
        try:
            quote = self.kite.ltp([key])
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"failed to fetch LTP for {symbol}: {exc}") from exc

        if key not in quote:
            raise BrokerError(f"no LTP returned for {symbol}")
        return float(quote[key]["last_price"])

    def available_margin(self) -> float:
        try:
            margins = self.kite.margins(segment="equity")
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"failed to fetch margins: {exc}") from exc
        return float(margins["available"]["live_balance"])

    def square_off(self, symbol: str) -> None:
        for position in self.get_positions():
            if position.symbol != symbol:
                continue
            side = OrderSide.SELL if position.direction is Direction.LONG else OrderSide.BUY
            self.place_order(
                symbol=symbol,
                side=side,
                order_type=OrderType.MARKET,
                quantity=position.quantity,
            )
