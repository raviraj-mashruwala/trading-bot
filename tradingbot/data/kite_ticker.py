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
        self._full_tick_callback: Callable[[Any, list[dict]], None] | None = None
        self._on_disconnect_cb: Callable[[], None] | None = None
        self._on_reconnect_cb: Callable[[], None] | None = None

    @property
    def subscribed_tokens(self) -> set[int]:
        """Currently subscribed instrument tokens (copy)."""
        return self._subscribed.copy()

    # -- Public API ----------------------------------------------------------

    def subscribe(
        self,
        tokens: list,
        callback: Callable | None = None,
    ) -> None:
        """Register *callback* for each instrument token in *tokens*.

        Two calling patterns are supported:

        1. ``subscribe([int, ...], per_token_cb)`` — per-token (token, ltp) callback.
        2. ``subscribe([str_or_int, ...], full_tick_cb)`` — full-tick (ws, ticks)
           callback used by :class:`ExecutionIntelligence`.  String tokens are
           stored as-is; real instrument-token resolution happens at runtime.
        """
        if callback is not None and tokens and isinstance(tokens[0], str):
            # ExecutionIntelligence pattern — register as raw tick forwarder
            self._full_tick_callback = callback
            for token in tokens:
                self._subscribed.add(token)
            return

        if callback is not None:
            for token in tokens:
                self._callbacks[token] = callback
                self._subscribed.add(token)
        else:
            for token in tokens:
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

    def set_lifecycle_callbacks(
        self,
        on_disconnect: Callable[[], None] | None = None,
        on_reconnect: Callable[[], None] | None = None,
    ) -> None:
        """Register callbacks for connection lifecycle events."""
        self._on_disconnect_cb = on_disconnect
        self._on_reconnect_cb = on_reconnect

    def start(self) -> None:
        """Create a KiteTicker and connect in a daemon thread."""
        self._ticker = KiteTicker(self._api_key, self._access_token)
        self._ticker.on_ticks = self._on_ticks
        self._ticker.on_connect = self._on_connect
        self._ticker.on_close = self._on_close
        self._ticker.on_error = self._on_error
        self._ticker.on_reconnect = self._on_ws_reconnect
        self._ticker.on_noreconnect = self._on_noreconnect

        self._ticker.connect(threaded=True)
        log.info("KiteTicker started")

    def force_reconnect(self) -> None:
        """Tear down the current WebSocket and reconnect fresh."""
        log.warning("Force-reconnecting KiteTicker")
        if self._ticker:
            try:
                self._ticker.close()
            except Exception:
                log.exception("Error closing ticker during force-reconnect")
            self._ticker = None
        self.start()

    def stop(self) -> None:
        """Close the WebSocket connection."""
        if self._ticker:
            self._ticker.close()
            self._ticker = None
        log.info("KiteTicker stopped")

    # -- Internal callbacks --------------------------------------------------

    _tick_log_count: int = 0

    def _on_ticks(self, ws: Any, ticks: list[dict]) -> None:
        self._tick_log_count += 1
        if self._tick_log_count <= 3 or self._tick_log_count % 100 == 0:
            log.info("Tick received: %d ticks, first=%s", len(ticks),
                     {k: ticks[0].get(k) for k in ("instrument_token", "last_price")} if ticks else "empty")
        # Forward full tick list to ExecutionIntelligence-style callback
        if self._full_tick_callback is not None:
            try:
                self._full_tick_callback(ws, ticks)
            except Exception:
                log.exception("Full tick callback error")

        # Per-token dispatch
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
        int_tokens = [t for t in tokens if isinstance(t, int)]
        if int_tokens:
            ws.subscribe(int_tokens)
            ws.set_mode(ws.MODE_LTP, int_tokens)
        log.info("KiteTicker connected, subscribed to %d tokens: %s", len(int_tokens), int_tokens)

    def _on_close(self, ws: Any, code: int, reason: str) -> None:
        log.warning("KiteTicker closed: %s %s", code, reason)
        if self._on_disconnect_cb is not None:
            try:
                self._on_disconnect_cb()
            except Exception:
                log.exception("Disconnect callback error")

    def _on_error(self, ws: Any, code: int, reason: str) -> None:
        log.error("KiteTicker error: %s %s", code, reason)

    def _on_ws_reconnect(self, ws: Any, attempts_count: int) -> None:
        log.info("KiteTicker reconnecting, attempt %d", attempts_count)
        if self._on_reconnect_cb is not None:
            try:
                self._on_reconnect_cb()
            except Exception:
                log.exception("Reconnect callback error")

    def _on_noreconnect(self, ws: Any) -> None:
        log.error("KiteTicker exhausted all reconnect attempts")
