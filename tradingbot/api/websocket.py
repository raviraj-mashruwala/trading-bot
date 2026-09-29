"""WebSocket connection manager. Relays EventBus events to all connected clients."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Track connected WebSocket clients and broadcast events to all of them."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    @property
    def active_count(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)
        logger.info("WebSocket client connected (%d total)", self.active_count)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections = [ws for ws in self._connections if ws is not websocket]
        logger.info("WebSocket client disconnected (%d remaining)", self.active_count)

    async def broadcast(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message)
        dead: list[WebSocket] = []

        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:  # noqa: BLE001
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws)

    async def broadcast_decision(self, decision_data: dict[str, Any]) -> None:
        """Push a decision event to all connected clients."""
        await self.broadcast({"type": "decision", "data": decision_data})

    async def broadcast_ticker_health(self, health_data: dict[str, Any]) -> None:
        """Push a ticker health update to all connected clients."""
        await self.broadcast({"type": "ticker_health", "data": health_data})


async def websocket_endpoint(websocket: WebSocket, manager: ConnectionManager) -> None:
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                action = msg.get("action")
                if action == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
