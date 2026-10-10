"""The single broker contract. Paper and live trading differ only in the implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from tradingbot.core.models import Position


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class BrokerError(Exception):
    """Raised when the broker rejects a request or cannot be reached."""


@dataclass
class Order:
    """One order as the broker sees it."""

    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: float | None
    trigger_price: float | None
    status: OrderStatus
    filled_price: float | None
    filled_quantity: int = 0
    placed_at: datetime = None

    @property
    def is_terminal(self) -> bool:
        """True once the order can no longer fill."""
        return self.status is not OrderStatus.OPEN


class BrokerInterface(ABC):
    """Every method the executor is allowed to call on a broker."""

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: int,
        price: float | None = None,
        trigger_price: float | None = None,
    ) -> str:
        """Submit an order and return its broker order id."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> None:
        """Cancel a resting order. Cancelling a filled order is a no-op."""

    @abstractmethod
    def get_order(self, order_id: str) -> Order | None:
        """Return the current state of an order, or None when it is unknown."""

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Return every open intraday position."""

    @abstractmethod
    def get_ltp(self, symbol: str) -> float:
        """Return the last traded price for one symbol."""

    @abstractmethod
    def available_margin(self) -> float:
        """Return the cash available to deploy."""

    @abstractmethod
    def square_off(self, symbol: str) -> None:
        """Close any open position in this symbol at market."""
