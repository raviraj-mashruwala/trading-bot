"""Cross-platform WebSocket ticker using asyncio + websockets.

Drop-in replacement for LiveTickManager that works on Windows, Mac, and Linux
without Twisted/autobahn dependency issues.

Uses Kite's binary WebSocket protocol directly.
"""

from __future__ import annotations

import asyncio
import logging
import struct
import threading
from datetime import datetime
from typing import Any, Callable

log = logging.getLogger(__name__)

KITE_WS_URL = "wss://ws.kite.trade"
MODE_LTP = "ltp"
MODE_QUOTE = "quote"
MODE_FULL = "full"

# Reuse KiteTicker's proven binary parser
_EXCHANGE_MAP = {
    "nse": 1, "nfo": 2, "cds": 3, "bse": 4, "bfo": 5,
    "bcd": 6, "mcx": 7, "mcxsx": 8, "indices": 9, "nco": 10,
}


def _unpack(data: bytes, start: int, end: int, fmt: str = "I") -> int:
    return struct.unpack(">" + fmt, data[start:end])[0]


def _parse_binary(data: bytes) -> list[dict]:
    """Parse Kite's binary WebSocket packet. Handles LTP, quote, and full modes."""
    if len(data) < 2:
        return []

    n_packets = _unpack(data, 0, 2, "H")
    packets = []
    j = 2
    for _ in range(n_packets):
        if j + 2 > len(data):
            break
        plen = _unpack(data, j, j + 2, "H")
        packets.append(data[j + 2:j + 2 + plen])
        j += 2 + plen

    ticks = []
    for packet in packets:
        if len(packet) < 8:
            continue
        token = _unpack(packet, 0, 4)
        segment = token & 0xff

        if segment == _EXCHANGE_MAP["cds"]:
            divisor = 10000000.0
        elif segment in (_EXCHANGE_MAP["bcd"], _EXCHANGE_MAP.get("nco", 10)):
            divisor = 10000.0
        else:
            divisor = 100.0

        tick = {
            "instrument_token": token,
            "last_price": _unpack(packet, 4, 8) / divisor,
            "exchange_timestamp": datetime.now(),
        }

        if len(packet) >= 44:
            tick["volume_traded"] = _unpack(packet, 16, 20)

        ticks.append(tick)

    return ticks


async def _noop() -> None:
    return None


class AsyncKiteTicker:
    """Async WebSocket ticker for Kite — works on all platforms."""

    def __init__(self, api_key: str, access_token: str) -> None:
        self._api_key = api_key
        self._access_token = access_token
        self._subscribed: set[int] = set()
        self._callbacks: dict[int, Callable[[int, float], None]] = {}
        self._full_tick_callback: Callable[[Any, list[dict]], None] | None = None
        self._on_disconnect_cb: Callable[[], None] | None = None
        self._on_reconnect_cb: Callable[[], None] | None = None
        self._ws = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._generation = 0
        self._tick_count = 0

    @property
    def subscribed_tokens(self) -> set[int]:
        return self._subscribed.copy()

    def subscribe(self, tokens: list, callback: Callable | None = None) -> None:
        if callback is not None and tokens and isinstance(tokens[0], str):
            self._full_tick_callback = callback
            for t in tokens:
                self._subscribed.add(t)
            return
        if callback is not None:
            for t in tokens:
                self._callbacks[t] = callback
                self._subscribed.add(t)
        else:
            for t in tokens:
                self._subscribed.add(t)
        if self._ws and self._loop:
            int_tokens = [t for t in self._subscribed if isinstance(t, int)]
            if int_tokens:
                asyncio.run_coroutine_threadsafe(self._send_subscribe(int_tokens), self._loop)

    def set_full_tick_callback(self, callback: Callable[[Any, list[dict]], None]) -> None:
        """Receive whole ticks (price and cumulative volume), not just (token, ltp)."""
        self._full_tick_callback = callback

    def unsubscribe(self, tokens: list[int]) -> None:
        for t in tokens:
            self._callbacks.pop(t, None)
            self._subscribed.discard(t)

    def set_lifecycle_callbacks(
        self,
        on_disconnect: Callable[[], None] | None = None,
        on_reconnect: Callable[[], None] | None = None,
    ) -> None:
        self._on_disconnect_cb = on_disconnect
        self._on_reconnect_cb = on_reconnect

    def start(self) -> None:
        self._running = True
        self._generation += 1
        loop = asyncio.new_event_loop()
        self._loop = loop
        self._thread = threading.Thread(
            target=self._run_loop, args=(loop, self._generation), daemon=True,
        )
        self._thread.start()
        log.info("AsyncKiteTicker started")

    def is_loop_responsive(self, timeout: float = 1.0) -> bool:
        """True if the ticker thread's event loop runs a trivial task within timeout.

        A loop blocked inside a callback never answers, which is exactly the state
        in which force_reconnect() (it schedules work on that loop) cannot help.
        """
        loop = self._loop
        if loop is None or not loop.is_running():
            return False
        try:
            future = asyncio.run_coroutine_threadsafe(_noop(), loop)
        except RuntimeError:
            return False
        try:
            future.result(timeout=timeout)
            return True
        except TimeoutError:
            future.cancel()
            return False

    def restart(self) -> None:
        """Replace the ticker thread and loop; keeps subscriptions and callbacks.

        The old thread may be stuck for good, so it is abandoned instead of closed.
        The generation bump makes it exit rather than reconnect if it ever wakes up.
        """
        log.warning("Restarting AsyncKiteTicker: replacing unresponsive loop thread")
        old_loop = self._loop
        self._ws = None
        self.start()
        if old_loop is not None:
            try:
                old_loop.call_soon_threadsafe(old_loop.stop)
            except RuntimeError:
                pass

    def force_reconnect(self) -> None:
        log.warning("Force-reconnecting AsyncKiteTicker")
        if self._ws and self._loop:
            asyncio.run_coroutine_threadsafe(self._close_ws(), self._loop)

    def stop(self) -> None:
        self._running = False
        if self._ws and self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._close_ws(), self._loop)
            try:
                future.result(timeout=3)
            except Exception:
                pass
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        log.info("AsyncKiteTicker stopped")

    def _run_loop(self, loop: asyncio.AbstractEventLoop | None = None, gen: int | None = None) -> None:
        loop = loop or self._loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._connect_loop(gen))
        except RuntimeError:
            log.debug("Ticker loop stopped", exc_info=True)

    async def _close_ws(self) -> None:
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def _connect_loop(self, gen: int | None = None) -> None:
        import websockets

        while self._running and (gen is None or gen == self._generation):
            url = (
                f"{KITE_WS_URL}?api_key={self._api_key}"
                f"&access_token={self._access_token}"
            )
            try:
                async with websockets.connect(
                    url,
                    additional_headers={"X-Kite-Version": "3"},
                    ping_interval=20,
                    ping_timeout=10,
                    max_size=2**20,
                ) as ws:
                    if gen is None or gen == self._generation:
                        self._ws = ws
                    log.info("AsyncKiteTicker connected to Kite WebSocket")

                    int_tokens = [t for t in self._subscribed if isinstance(t, int)]
                    if int_tokens:
                        await self._send_subscribe(int_tokens)
                        await self._send_set_mode(int_tokens)
                        log.info("Subscribed to %d tokens: %s", len(int_tokens), int_tokens)

                    if self._on_reconnect_cb and self._tick_count > 0:
                        try:
                            self._on_reconnect_cb()
                        except Exception:
                            pass

                    async for message in ws:
                        if gen is not None and gen != self._generation:
                            break
                        if isinstance(message, bytes) and len(message) > 2:
                            ticks = _parse_binary(message)
                            if ticks:
                                self._tick_count += 1
                                if self._tick_count <= 3 or self._tick_count % 100 == 0:
                                    log.info("Tick #%d: %d instruments, first=%s @ %.2f",
                                             self._tick_count, len(ticks),
                                             ticks[0]["instrument_token"], ticks[0]["last_price"])
                                self._dispatch_ticks(ticks)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning("WebSocket error: %s, reconnecting in 5s", type(exc).__name__)
                if self._on_disconnect_cb:
                    try:
                        self._on_disconnect_cb()
                    except Exception:
                        pass

            if gen is None or gen == self._generation:
                self._ws = None
            if self._running:
                await asyncio.sleep(5)

    async def _send_subscribe(self, tokens: list[int]) -> None:
        if self._ws:
            import json
            msg = json.dumps({"a": "subscribe", "v": tokens})
            await self._ws.send(msg)

    async def _send_set_mode(self, tokens: list[int]) -> None:
        if self._ws:
            import json
            msg = json.dumps({"a": "mode", "v": [MODE_QUOTE, tokens]})
            await self._ws.send(msg)

    @property
    def last_tick_time(self) -> datetime | None:
        return self._last_tick_time

    _last_tick_time: datetime | None = None

    def _dispatch_ticks(self, ticks: list[dict]) -> None:
        self._last_tick_time = datetime.now()
        if self._full_tick_callback is not None:
            try:
                self._full_tick_callback(None, ticks)
            except Exception:
                log.exception("Full tick callback error")

        for tick in ticks:
            token = tick.get("instrument_token")
            ltp = tick.get("last_price")
            if token is not None and ltp is not None and token in self._callbacks:
                try:
                    self._callbacks[token](token, ltp)
                except Exception:
                    log.exception("Tick callback error for token %s", token)
