"""Kite order execution with drift + margin safety checks."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class KiteExecutor:
    """Place, modify, and cancel orders through KiteClient with pre-checks."""

    def __init__(
        self,
        client: Any,
        capital_manager: Any,
        max_drift_pct: float = 2.0,
        execution_mode: str = "live",
        shadow_fraction: float = 0.1,
    ):
        self._client = client
        self._capital = capital_manager
        self._max_drift = max_drift_pct
        self._mode = execution_mode
        self._shadow_fraction = shadow_fraction

    def place_entry(
        self,
        symbol: str,
        exchange: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        quantity: int,
        order_type: str,
        current_price: float,
    ) -> str | None:
        """Place an entry order after drift + margin checks.

        Returns order_id on success, None on rejection or error.
        """
        drift = abs(current_price - entry_price) / entry_price * 100
        if drift > self._max_drift:
            log.warning("%s: price drifted %.1f%%, skipping", symbol, drift)
            return None

        # Shadow mode: scale quantity down for low-risk validation
        actual_qty = quantity
        if self._mode == "shadow":
            actual_qty = max(1, int(quantity * self._shadow_fraction))
            log.info("%s: shadow mode, qty %d -> %d", symbol, quantity, actual_qty)

        ok, reason = self._capital.check_margin(entry_price, actual_qty)
        if not ok:
            log.warning("%s: %s", symbol, reason)
            return None

        transaction_type = "BUY" if direction == "long" else "SELL"
        try:
            order_id = self._client.place_order(
                variety="regular",
                exchange=exchange,
                tradingsymbol=symbol,
                transaction_type=transaction_type,
                quantity=actual_qty,
                product="MIS",
                order_type=order_type,
                price=entry_price,
                validity="DAY",
            )
            self._capital.add_deployed(entry_price * actual_qty)
            log.info("%s: entry order placed %s", symbol, order_id)
            return order_id
        except Exception:
            log.exception("%s: failed to place entry", symbol)
            return None

    def place_exit(
        self,
        symbol: str,
        exchange: str,
        direction: str,
        quantity: int,
        price: float | None = None,
        order_type: str = "MARKET",
    ) -> str | None:
        """Place an exit order. Returns order_id or None on failure."""
        transaction_type = "SELL" if direction == "long" else "BUY"
        try:
            kwargs: dict[str, Any] = dict(
                variety="regular",
                exchange=exchange,
                tradingsymbol=symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                product="MIS",
                order_type=order_type,
                validity="DAY",
            )
            if price and order_type != "MARKET":
                kwargs["price"] = price
            order_id = self._client.place_order(**kwargs)
            self._capital.release_deployed(price * quantity if price else 0)
            return order_id
        except Exception:
            log.exception("%s: failed to place exit", symbol)
            return None

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._client.cancel_order("regular", order_id)
            return True
        except Exception:
            log.exception("Failed to cancel order %s", order_id)
            return False

    def modify_order(self, order_id: str, price: float) -> bool:
        try:
            self._client.modify_order(
                variety="regular", order_id=order_id, price=price,
            )
            return True
        except Exception:
            log.exception("Failed to modify order %s", order_id)
            return False
