"""In-process pub/sub for pipeline observability.

Async modules (scanner, plan_generator) call await emit().
The synchronous executor calls emit_sync(), which queues events
for a background flush_loop() to dispatch.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable

from tradingbot.core.models import now_ist

logger = logging.getLogger(__name__)


class EventBus:
    """Publish-subscribe event bus with both async and sync emit paths."""

    def __init__(self) -> None:
        self._subscribers: dict[str, Callable] = {}
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._shutdown = False

    def subscribe(self, callback: Callable) -> str:
        sub_id = str(uuid.uuid4())
        self._subscribers[sub_id] = callback
        return sub_id

    def unsubscribe(self, sub_id: str) -> None:
        self._subscribers.pop(sub_id, None)

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        envelope = self._wrap(event_type, data)
        self._dispatch(envelope)

    def emit_sync(self, event_type: str, data: dict[str, Any]) -> None:
        envelope = self._wrap(event_type, data)
        self._queue.put_nowait(envelope)

    async def flush_loop(self) -> None:
        while not self._shutdown:
            try:
                envelope = await asyncio.wait_for(self._queue.get(), timeout=0.05)
                self._dispatch(envelope)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def shutdown(self) -> None:
        self._shutdown = True
        while not self._queue.empty():
            try:
                envelope = self._queue.get_nowait()
                self._dispatch(envelope)
            except asyncio.QueueEmpty:
                break

    def _dispatch(self, envelope: dict[str, Any]) -> None:
        for sub_id, callback in list(self._subscribers.items()):
            try:
                callback(envelope)
            except Exception:  # noqa: BLE001
                logger.warning("subscriber %s raised; skipping", sub_id, exc_info=True)

    @staticmethod
    def _wrap(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": event_type,
            "timestamp": now_ist().isoformat(),
            "data": data,
        }
