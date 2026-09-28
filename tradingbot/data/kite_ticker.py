"""LiveTickManager — Kite WebSocket real-time price ticks."""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from kiteconnect import KiteTicker

log = logging.getLogger(__name__)


class LiveTickManager:
    """Manages Kite WebSocket connection for real-time price ticks.

    Parameters
    ----------
    api_key : str
        Kite Connect API key.
    access_token : str
        Session access token from :class:`KiteAuth`.
    """

    def __init__(self, api_key: str, access_token: str) -> None:
        self._api_key = api_key
        self._access_token = access_token
        self._ticker: KiteTicker | None = None
        self._callbacks: dict[int, Callable[[int, float], None]] = {}
        self._subscribed: set[int] = set()
        self._thread: threading.Thread | None = None

    @property
    def subscribed_tokens(self) -> set[int]:
        """Currently subscribed instrument tokens (copy)."""
        return self._subscribed.copy()

    # -- Public API ----------------------------------------------------------

    def subscribe(
        self,
        tokens: list[int],
        callback: Callable[[int, float], None],
    ) -> None:
        """Register *callback* for each instrument token in *tokens*."""
        for token in tokens:
            self._callbacks[token] = callback
            self._subscribed.add(token)

        if self._ticker is not None:
            self._ticker.subscribe(tokens)
            self._ticker.set_mode(self._ticker.MODE_LTP, tokens)

    def unsubscribe(self, tokens: list[int]) -> None:
        """Remove subscriptions for *tokens*."""
        for token in tokens:
            self._callbacks.pop(token, None)
            self._subscribed.discard(token)

        if self._ticker is not None:
            self._ticker.unsubscribe(tokens)

    def start(self) -> None:
        """Create a KiteTicker and connect in a daemon thread."""
        self._ticker = KiteTicker(self._api_key, self._access_token)
        self._ticker.on_ticks = self._on_ticks
        self._ticker.on_connect = self._on_connect
        self._ticker.on_close = self._on_close

        self._thread = threading.Thread(
            target=self._ticker.connect, daemon=True,
        )
        self._thread.start()
        log.info("KiteTicker started")

    def stop(self) -> None:
        """Close the WebSocket connection."""
        if self._ticker:
            self._ticker.close()
            self._ticker = None
        log.info("KiteTicker stopped")

    # -- Internal callbacks --------------------------------------------------

    def _on_ticks(self, ws: Any, ticks: list[dict]) -> None:
        for tick in ticks:
            token = tick.get("instrument_token")
            ltp = tick.get("last_price")
            if token is not None and ltp is not None and token in self._callbacks:
                try:
                    self._callbacks[token](token, ltp)
                except Exception:
                    log.exception("Tick callback error for token %s", token)

    def _on_connect(self, ws: Any, response: Any) -> None:
        tokens = list(self._subscribed)
        if tokens:
            ws.subscribe(tokens)
            ws.set_mode(ws.MODE_LTP, tokens)
        log.info("KiteTicker connected, subscribed to %d tokens", len(tokens))

    def _on_close(self, ws: Any, code: int, reason: str) -> None:
        log.warning("KiteTicker closed: %s %s", code, reason)
