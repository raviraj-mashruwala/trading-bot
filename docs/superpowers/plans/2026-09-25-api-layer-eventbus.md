# API Layer + EventBus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a FastAPI server with REST endpoints, WebSocket event streaming, and an EventBus that existing modules emit into, so a React frontend can drive the trading bot.

**Architecture:** FastAPI app created via a lifespan function that initialises AppState (config, database, plan store, event bus). REST routers for config/plans/trades/analysis/execution. A single WebSocket endpoint relays all EventBus events to connected clients. Existing modules gain an optional `event_bus` keyword parameter — `None` in CLI mode, set when called from the API. The executor uses `emit_sync` (synchronous) while async modules use `await emit`.

**Tech Stack:** FastAPI, uvicorn, httpx (test client), existing tradingbot modules.

**Spec:** `docs/superpowers/specs/2026-09-25-api-layer-eventbus-design.md`

## Global Constraints

- Python 3.12+
- New dependencies: `fastapi>=0.115.0`, `uvicorn[standard]>=0.32.0`
- All existing 269 tests must keep passing — event_bus=None is the default everywhere
- EventBus has two emit paths: `async emit()` for async code, `emit_sync()` for the synchronous executor
- REST at `/api/*`, WebSocket at `/ws`
- CORS allows `http://localhost:3000`
- Secrets in GET /api/config are masked: show only last 3 chars
- POST /api/analyze and POST /api/execute return immediately, work runs in background tasks
- POST /api/analyze returns 409 if already running; POST /api/execute returns 409 if already running, 400 if no plan
- No authentication — single user, localhost

## Review Focus

1. **EventBus emit_sync called from async context** — mixing sync emit in an async function silently skips events because the flush loop may not be running. Only the executor should use emit_sync; scanner and plan_generator must use await emit. Test in Task 1.
2. **WebSocket client disconnects mid-broadcast** — broadcasting to a closed connection must not crash the server or block other clients. Test in Task 2.
3. **Two simultaneous POST /api/analyze requests** — the second must get 409, not start a second background analysis. Test in Task 4.
4. **Config PUT with invalid values** — must reject with 400 and not write partial changes to disk. Test in Task 3.
5. **Executor background task outlives a cancelled analysis** — cancelling analysis must not affect a running executor, and vice versa. Test in Tasks 4 and 5.

---

## File Structure

```
tradingbot/
├── api/                          # NEW — Tasks 2-7
│   ├── __init__.py               # Task 2
│   ├── app.py                    # Task 2 — FastAPI app, CORS, lifespan
│   ├── state.py                  # Task 2 — AppState dataclass
│   ├── websocket.py              # Task 2 — ConnectionManager, WS endpoint
│   ├── config_routes.py          # Task 3
│   ├── plan_routes.py            # Task 3
│   ├── trade_routes.py           # Task 3
│   ├── health_routes.py          # Task 3
│   ├── analysis_routes.py        # Task 4
│   └── execution_routes.py       # Task 5
├── core/
│   ├── events.py                 # Task 1 — NEW
│   └── config.py                 # Task 3 — add config write helpers
├── scanner/
│   ├── scanner.py                # Task 6 — add event_bus emit calls
│   └── market_analyzer.py        # Task 6 — add event_bus emit calls
├── strategy/
│   └── plan_generator.py         # Task 6 — add event_bus emit calls
├── executor/
│   └── executor.py               # Task 7 — add event_bus emit_sync calls
├── cli.py                        # Task 8 — add serve command
└── pyproject.toml                # Task 2 — add fastapi, uvicorn deps
```

---

## Task 1: EventBus

**Files:**
- Create: `tradingbot/core/events.py`
- Test: `tests/core/test_events.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `EventBus()` with `async emit(event_type: str, data: dict) -> None`, `emit_sync(event_type: str, data: dict) -> None`, `subscribe(callback: Callable) -> str`, `unsubscribe(sub_id: str) -> None`, `async flush_loop() -> None`, `async shutdown() -> None`.
  - Every emitted event is wrapped in `{"type": event_type, "timestamp": ISO-8601, "data": data}`.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_events.py`:

```python
import asyncio
import json

import pytest

from tradingbot.core.events import EventBus


async def test_emit_delivers_to_a_subscriber():
    bus = EventBus()
    received = []
    bus.subscribe(lambda event: received.append(event))

    await bus.emit("scan.universe", {"count": 50})

    assert len(received) == 1
    assert received[0]["type"] == "scan.universe"
    assert received[0]["data"] == {"count": 50}
    assert "timestamp" in received[0]


async def test_emit_delivers_to_multiple_subscribers():
    bus = EventBus()
    a, b = [], []
    bus.subscribe(lambda event: a.append(event))
    bus.subscribe(lambda event: b.append(event))

    await bus.emit("scan.filtered", {"passed": 38})

    assert len(a) == 1
    assert len(b) == 1


async def test_unsubscribe_stops_delivery():
    bus = EventBus()
    received = []
    sub_id = bus.subscribe(lambda event: received.append(event))

    await bus.emit("scan.universe", {"count": 50})
    bus.unsubscribe(sub_id)
    await bus.emit("scan.filtered", {"passed": 38})

    assert len(received) == 1
    assert received[0]["type"] == "scan.universe"


async def test_unsubscribe_unknown_id_is_a_noop():
    bus = EventBus()

    bus.unsubscribe("nonexistent")


async def test_emit_with_no_subscribers_does_not_raise():
    bus = EventBus()

    await bus.emit("scan.universe", {"count": 50})


async def test_emit_sync_queues_for_later_delivery():
    bus = EventBus()
    received = []
    bus.subscribe(lambda event: received.append(event))

    bus.emit_sync("exec.price_tick", {"symbol": "RELIANCE", "price": 100.0})

    assert len(received) == 0

    flush_task = asyncio.create_task(bus.flush_loop())
    await asyncio.sleep(0.1)
    await bus.shutdown()
    flush_task.cancel()
    try:
        await flush_task
    except asyncio.CancelledError:
        pass

    assert len(received) == 1
    assert received[0]["type"] == "exec.price_tick"
    assert received[0]["data"]["symbol"] == "RELIANCE"


async def test_emit_sync_multiple_events_all_flushed():
    bus = EventBus()
    received = []
    bus.subscribe(lambda event: received.append(event))

    bus.emit_sync("exec.entry_placed", {"symbol": "A"})
    bus.emit_sync("exec.entry_filled", {"symbol": "A"})
    bus.emit_sync("exec.stop_hit", {"symbol": "A"})

    flush_task = asyncio.create_task(bus.flush_loop())
    await asyncio.sleep(0.1)
    await bus.shutdown()
    flush_task.cancel()
    try:
        await flush_task
    except asyncio.CancelledError:
        pass

    assert [e["type"] for e in received] == [
        "exec.entry_placed",
        "exec.entry_filled",
        "exec.stop_hit",
    ]


async def test_event_envelope_has_iso_timestamp():
    bus = EventBus()
    received = []
    bus.subscribe(lambda event: received.append(event))

    await bus.emit("test.event", {"key": "value"})

    ts = received[0]["timestamp"]
    assert "T" in ts
    assert "+" in ts or "Z" in ts


async def test_a_failing_subscriber_does_not_block_others():
    bus = EventBus()
    good = []

    def bad_subscriber(event):
        raise RuntimeError("I crash")

    bus.subscribe(bad_subscriber)
    bus.subscribe(lambda event: good.append(event))

    await bus.emit("test.event", {"key": "value"})

    assert len(good) == 1


async def test_subscribe_returns_unique_ids():
    bus = EventBus()

    id_a = bus.subscribe(lambda e: None)
    id_b = bus.subscribe(lambda e: None)

    assert id_a != id_b
    assert isinstance(id_a, str)
    assert isinstance(id_b, str)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_events.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.core.events'`

- [ ] **Step 3: Implement the EventBus**

Create `tradingbot/core/events.py`:

```python
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
        """Register a callback. Returns a subscription ID for later removal."""
        sub_id = str(uuid.uuid4())
        self._subscribers[sub_id] = callback
        return sub_id

    def unsubscribe(self, sub_id: str) -> None:
        """Remove a subscription. Unknown IDs are silently ignored."""
        self._subscribers.pop(sub_id, None)

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Async emit — dispatches to all subscribers immediately."""
        envelope = self._wrap(event_type, data)
        self._dispatch(envelope)

    def emit_sync(self, event_type: str, data: dict[str, Any]) -> None:
        """Synchronous emit — queues for the flush loop to dispatch."""
        envelope = self._wrap(event_type, data)
        self._queue.put_nowait(envelope)

    async def flush_loop(self) -> None:
        """Background task: drain the sync queue and dispatch each event."""
        while not self._shutdown:
            try:
                envelope = await asyncio.wait_for(self._queue.get(), timeout=0.05)
                self._dispatch(envelope)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def shutdown(self) -> None:
        """Drain remaining queued events and stop the flush loop."""
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
            except Exception:  # noqa: BLE001 — one bad subscriber must not block others
                logger.warning("subscriber %s raised; skipping", sub_id, exc_info=True)

    @staticmethod
    def _wrap(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": event_type,
            "timestamp": now_ist().isoformat(),
            "data": data,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_events.py -v`
Expected: PASS — 10 tests.

- [ ] **Step 5: Run full suite to verify no regressions**

Run: `pytest tests/ -q --tb=short`
Expected: 279 passed (269 existing + 10 new).

- [ ] **Step 6: Commit**

```bash
git add tradingbot/core/events.py tests/core/test_events.py
git commit -m "feat: add EventBus with async and sync emit paths"
```

---

## Task 2: FastAPI App Shell, AppState, WebSocket, Dependencies

**Files:**
- Create: `tradingbot/api/__init__.py`, `tradingbot/api/app.py`, `tradingbot/api/state.py`, `tradingbot/api/websocket.py`
- Modify: `pyproject.toml` (add fastapi, uvicorn)
- Test: `tests/api/__init__.py`, `tests/api/test_websocket.py`, `tests/api/test_app.py`

**Interfaces:**
- Consumes: `EventBus` (Task 1); `Config`, `load_config` from config; `Database` from database; `PlanStore` from plan_store.
- Produces:
  - `AppState` dataclass with `config`, `event_bus`, `database`, `plan_store`, status fields.
  - `create_app(config_path=None, data_dir=None) -> FastAPI` with lifespan that initialises AppState.
  - `ConnectionManager` with `async connect(ws)`, `disconnect(ws)`, `async broadcast(message: dict)`.
  - WebSocket endpoint at `/ws` that relays EventBus events.
  - `get_state(request) -> AppState` dependency.

- [ ] **Step 1: Add dependencies to pyproject.toml**

Add to the `dependencies` list in `pyproject.toml`:

```
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
```

Run: `pip install -e ".[dev]"`

- [ ] **Step 2: Write the failing test for the app and WebSocket**

Create `tests/api/__init__.py` (empty) and `tests/api/test_app.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient

from tradingbot.api.app import create_app


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("KITE_API_KEY", "kite-key")
    monkeypatch.setenv("KITE_API_SECRET", "kite-secret")

    config_path = tmp_path / "config.toml"
    config_path.write_text("""\
[general]
mode = "paper"
capital = 400000
log_level = "INFO"

[scanner]
min_volume = 500000
min_price = 50
max_price = 5000
min_market_cap_cr = 5000
min_atr_pct = 0.5
max_stocks_to_llm = 100
llm_pick_count = 15

[strategy]
backtest_days = 30
candle_interval = "15minute"
min_confidence = 0.5
min_reward_risk = 1.5
max_trades_per_day = 2

[risk]
max_risk_per_trade_pct = 0.01
max_daily_loss_pct = 0.02
max_capital_deployed_pct = 0.50
max_concurrent_positions = 2

[execution]
entry_slippage_pct = 0.05
square_off_time = "15:10"
connection_timeout_sec = 30
heartbeat_interval_sec = 60
plan_max_age_hours = 14
max_entry_price_drift_pct = 2.0

[llm]
provider = "anthropic"
model = "claude-sonnet-5"
timeout_sec = 60
max_retries = 1
base_url = ""

[paper]
slippage_pct = 0.05
initial_capital = 400000
""")

    return create_app(config_path=config_path, data_dir=tmp_path)


@pytest.fixture()
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_health_endpoint_returns_ok(client):
    response = await client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["api"] == "ok"
    assert "database" in body


async def test_cors_headers_present_for_localhost_3000(client):
    response = await client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


async def test_unknown_route_returns_404(client):
    response = await client.get("/api/nonexistent")

    assert response.status_code == 404
```

Create `tests/api/test_websocket.py`:

```python
import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient

from tradingbot.api.app import create_app
from tradingbot.api.websocket import ConnectionManager


async def test_connection_manager_tracks_connections():
    manager = ConnectionManager()

    assert manager.active_count == 0


async def test_connection_manager_broadcast_delivers_to_all(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("KITE_API_KEY", "kite-key")
    monkeypatch.setenv("KITE_API_SECRET", "kite-secret")

    config_path = tmp_path / "config.toml"
    config_path.write_text("""\
[general]
mode = "paper"
capital = 400000
log_level = "INFO"

[scanner]
min_volume = 500000
min_price = 50
max_price = 5000
min_market_cap_cr = 5000
min_atr_pct = 0.5
max_stocks_to_llm = 100
llm_pick_count = 15

[strategy]
backtest_days = 30
candle_interval = "15minute"
min_confidence = 0.5
min_reward_risk = 1.5
max_trades_per_day = 2

[risk]
max_risk_per_trade_pct = 0.01
max_daily_loss_pct = 0.02
max_capital_deployed_pct = 0.50
max_concurrent_positions = 2

[execution]
entry_slippage_pct = 0.05
square_off_time = "15:10"
connection_timeout_sec = 30
heartbeat_interval_sec = 60
plan_max_age_hours = 14
max_entry_price_drift_pct = 2.0

[llm]
provider = "anthropic"
model = "claude-sonnet-5"
timeout_sec = 60
max_retries = 1
base_url = ""

[paper]
slippage_pct = 0.05
initial_capital = 400000
""")

    app = create_app(config_path=config_path, data_dir=tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/health")
        assert response.status_code == 200
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/api/ -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.api'`

- [ ] **Step 4: Implement AppState**

Create `tradingbot/api/__init__.py` (empty) and `tradingbot/api/state.py`:

```python
"""Shared application state for the FastAPI server."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from tradingbot.core.config import Config
from tradingbot.core.database import Database
from tradingbot.core.events import EventBus
from tradingbot.core.plan_store import PlanStore
from tradingbot.executor.executor import Executor


@dataclass
class AppState:
    """Created once at server startup, shared across all routes."""

    config: Config
    event_bus: EventBus
    database: Database
    plan_store: PlanStore
    config_path: str = ""
    data_dir: str = ""

    analysis_status: str = "idle"
    analysis_task: asyncio.Task | None = None
    analysis_error: str | None = None
    analysis_trade_date: str | None = None

    executor_status: str = "idle"
    executor_ref: Executor | None = None
    executor_task: asyncio.Task | None = None
    executor_mode: str | None = None
```

- [ ] **Step 5: Implement the ConnectionManager and WebSocket endpoint**

Create `tradingbot/api/websocket.py`:

```python
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
        """Send a JSON message to every connected client. Disconnected clients are removed."""
        payload = json.dumps(message)
        dead: list[WebSocket] = []

        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:  # noqa: BLE001 — one bad connection must not block others
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws)


async def websocket_endpoint(websocket: WebSocket, manager: ConnectionManager) -> None:
    """The /ws endpoint handler. Relays events; accepts control messages."""
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
```

- [ ] **Step 6: Implement the FastAPI app with lifespan**

Create `tradingbot/api/app.py`:

```python
"""FastAPI application factory. One app per server process."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from tradingbot.api.state import AppState
from tradingbot.api.websocket import ConnectionManager, websocket_endpoint
from tradingbot.core.config import load_config
from tradingbot.core.database import Database
from tradingbot.core.events import EventBus
from tradingbot.core.plan_store import PlanStore

DEFAULT_DATA_DIR = Path(".")


def create_app(
    config_path: Path | None = None,
    data_dir: Path | None = None,
) -> FastAPI:
    """Build and return the FastAPI application."""
    resolved_data_dir = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    manager = ConnectionManager()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = load_config(config_path)
        event_bus = EventBus()

        database = Database(resolved_data_dir / "tradingbot.db")
        database.initialise()

        plan_store = PlanStore(resolved_data_dir / "trade_plans")

        event_bus.subscribe(lambda event: asyncio.ensure_future(manager.broadcast(event)))

        flush_task = asyncio.create_task(event_bus.flush_loop())

        app.state.app_state = AppState(
            config=config,
            event_bus=event_bus,
            database=database,
            plan_store=plan_store,
            config_path=str(config_path or "config.toml"),
            data_dir=str(resolved_data_dir),
        )

        yield

        await event_bus.shutdown()
        flush_task.cancel()
        try:
            await flush_task
        except asyncio.CancelledError:
            pass
        database.close()

    app = FastAPI(title="Trading Bot API", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.websocket("/ws")
    async def ws_endpoint(websocket):
        await websocket_endpoint(websocket, manager)

    @app.get("/api/health")
    async def health(request: Request):
        state: AppState = request.app.state.app_state
        db_ok = True
        try:
            state.database.connection.execute("SELECT 1")
        except Exception:  # noqa: BLE001
            db_ok = False

        return {
            "api": "ok",
            "database": "ok" if db_ok else "error",
            "llm": "unconfigured",
        }

    return app


def get_state(request: Request) -> AppState:
    """FastAPI dependency to access the shared AppState."""
    return request.app.state.app_state
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/api/ -v`
Expected: PASS — 4 tests.

- [ ] **Step 8: Run full suite**

Run: `pytest tests/ -q --tb=short`
Expected: 283 passed.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml tradingbot/api/ tests/api/
git commit -m "feat: add FastAPI app shell with WebSocket, AppState, and CORS"
```

---

## Task 3: Config, Plan, Trade, and Health REST Routes

**Files:**
- Create: `tradingbot/api/config_routes.py`, `tradingbot/api/plan_routes.py`, `tradingbot/api/trade_routes.py`, `tradingbot/api/health_routes.py`
- Modify: `tradingbot/api/app.py` (register routers)
- Test: `tests/api/test_config_routes.py`, `tests/api/test_plan_routes.py`, `tests/api/test_trade_routes.py`

**Interfaces:**
- Consumes: `AppState`, `get_state` (Task 2); `Config`, `load_config`, `ConfigError` from config; `PlanStore`, `PlanNotFoundError` from plan_store; `Database` from database; `TradePlan` from models.
- Produces:
  - Config routes: `GET /api/config` (masked secrets), `PUT /api/config` (partial update, validates), `GET /api/config/providers`, `POST /api/config/test-llm`.
  - Plan routes: `GET /api/plans` (list), `GET /api/plans/{date}` (detail), `DELETE /api/plans/{date}`.
  - Trade routes: `GET /api/trades` (history, `?days=30`), `GET /api/trades/stats` (`?days=30`).
  - Health route moved from app.py to its own router.

- [ ] **Step 1: Write the failing test for config routes**

Create `tests/api/test_config_routes.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient

from tradingbot.api.app import create_app

CONFIG_TEXT = """\
[general]
mode = "paper"
capital = 400000
log_level = "INFO"

[scanner]
min_volume = 500000
min_price = 50
max_price = 5000
min_market_cap_cr = 5000
min_atr_pct = 0.5
max_stocks_to_llm = 100
llm_pick_count = 15

[strategy]
backtest_days = 30
candle_interval = "15minute"
min_confidence = 0.5
min_reward_risk = 1.5
max_trades_per_day = 2

[risk]
max_risk_per_trade_pct = 0.01
max_daily_loss_pct = 0.02
max_capital_deployed_pct = 0.50
max_concurrent_positions = 2

[execution]
entry_slippage_pct = 0.05
square_off_time = "15:10"
connection_timeout_sec = 30
heartbeat_interval_sec = 60
plan_max_age_hours = 14
max_entry_price_drift_pct = 2.0

[llm]
provider = "anthropic"
model = "claude-sonnet-5"
timeout_sec = 60
max_retries = 1
base_url = ""

[paper]
slippage_pct = 0.05
initial_capital = 400000
"""


@pytest.fixture()
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret123")
    monkeypatch.setenv("KITE_API_KEY", "kite-key-abc")
    monkeypatch.setenv("KITE_API_SECRET", "kite-secret-xyz")
    (tmp_path / "config.toml").write_text(CONFIG_TEXT)

    app = create_app(config_path=tmp_path / "config.toml", data_dir=tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_get_config_returns_all_sections(client):
    response = await client.get("/api/config")

    assert response.status_code == 200
    body = response.json()
    assert body["general"]["mode"] == "paper"
    assert body["general"]["capital"] == 400000
    assert body["scanner"]["min_volume"] == 500000
    assert body["llm"]["provider"] == "anthropic"


async def test_get_config_masks_secrets(client):
    response = await client.get("/api/config")

    body = response.json()
    assert body["secrets"]["anthropic_api_key"].startswith("***")
    assert body["secrets"]["anthropic_api_key"].endswith("123")
    assert "sk-ant-secret" not in body["secrets"]["anthropic_api_key"]


async def test_get_config_providers_lists_available_providers(client):
    response = await client.get("/api/config/providers")

    assert response.status_code == 200
    providers = response.json()
    names = [p["name"] for p in providers]
    assert "anthropic" in names
    assert "openai" in names


async def test_put_config_updates_a_section(client):
    response = await client.put(
        "/api/config",
        json={"general": {"capital": 500000}},
    )

    assert response.status_code == 200

    updated = await client.get("/api/config")
    assert updated.json()["general"]["capital"] == 500000


async def test_put_config_rejects_invalid_mode(client):
    response = await client.put(
        "/api/config",
        json={"general": {"mode": "turbo"}},
    )

    assert response.status_code == 400
    assert "mode" in response.json()["detail"].lower()
```

- [ ] **Step 2: Write the failing test for plan routes**

Create `tests/api/test_plan_routes.py`:

```python
import json
from datetime import datetime, time

import pytest
from httpx import ASGITransport, AsyncClient

from tradingbot.api.app import create_app
from tradingbot.core.models import (
    IST,
    Direction,
    EntryType,
    MarketRegime,
    StrategyName,
    TradeLeg,
    TradePlan,
)
from tradingbot.core.plan_store import PlanStore

CONFIG_TEXT = """\
[general]
mode = "paper"
capital = 400000
log_level = "INFO"

[scanner]
min_volume = 500000
min_price = 50
max_price = 5000
min_market_cap_cr = 5000
min_atr_pct = 0.5
max_stocks_to_llm = 100
llm_pick_count = 15

[strategy]
backtest_days = 30
candle_interval = "15minute"
min_confidence = 0.5
min_reward_risk = 1.5
max_trades_per_day = 2

[risk]
max_risk_per_trade_pct = 0.01
max_daily_loss_pct = 0.02
max_capital_deployed_pct = 0.50
max_concurrent_positions = 2

[execution]
entry_slippage_pct = 0.05
square_off_time = "15:10"
connection_timeout_sec = 30
heartbeat_interval_sec = 60
plan_max_age_hours = 14
max_entry_price_drift_pct = 2.0

[llm]
provider = "anthropic"
model = "claude-sonnet-5"
timeout_sec = 60
max_retries = 1
base_url = ""

[paper]
slippage_pct = 0.05
initial_capital = 400000
"""


def make_plan(trade_date="2026-09-28") -> TradePlan:
    leg = TradeLeg(
        symbol="RELIANCE",
        exchange="NSE",
        strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG,
        entry_price=2855.0,
        entry_type=EntryType.LIMIT,
        stop_loss=2830.0,
        target_1=2890.0,
        target_2=2920.0,
        quantity=16,
        risk_amount=4000.0,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        max_entry_wait=time(11, 0),
        exit_before=time(15, 10),
        confidence=0.72,
        reasoning="Breaking out.",
    )
    return TradePlan(
        trade_date=trade_date,
        generated_at=datetime(2026, 9, 27, 22, 30, tzinfo=IST),
        capital=400000.0,
        max_risk_per_trade_pct=0.01,
        max_daily_loss_pct=0.02,
        market_regime=MarketRegime.TRENDING,
        market_summary="Nifty bullish.",
        legs=[leg],
    )


@pytest.fixture()
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("KITE_API_KEY", "k")
    monkeypatch.setenv("KITE_API_SECRET", "s")
    (tmp_path / "config.toml").write_text(CONFIG_TEXT)

    plan_dir = tmp_path / "trade_plans"
    store = PlanStore(plan_dir)
    store.save(make_plan("2026-09-28"))
    store.save(make_plan("2026-09-26"))

    app = create_app(config_path=tmp_path / "config.toml", data_dir=tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_list_plans_returns_all_dates(client):
    response = await client.get("/api/plans")

    assert response.status_code == 200
    dates = [p["trade_date"] for p in response.json()]
    assert "2026-09-28" in dates
    assert "2026-09-26" in dates


async def test_get_plan_by_date(client):
    response = await client.get("/api/plans/2026-09-28")

    assert response.status_code == 200
    body = response.json()
    assert body["trade_date"] == "2026-09-28"
    assert len(body["legs"]) == 1
    assert body["legs"][0]["symbol"] == "RELIANCE"


async def test_get_missing_plan_returns_404(client):
    response = await client.get("/api/plans/2099-01-01")

    assert response.status_code == 404


async def test_delete_plan(client):
    response = await client.delete("/api/plans/2026-09-26")

    assert response.status_code == 200

    check = await client.get("/api/plans/2026-09-26")
    assert check.status_code == 404
```

- [ ] **Step 3: Write the failing test for trade routes**

Create `tests/api/test_trade_routes.py`:

```python
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from tradingbot.api.app import create_app
from tradingbot.core.database import Database
from tradingbot.core.models import (
    IST,
    Direction,
    ExecutedTrade,
    Mode,
    StrategyName,
    TradeStatus,
)

CONFIG_TEXT = """\
[general]
mode = "paper"
capital = 400000
log_level = "INFO"

[scanner]
min_volume = 500000
min_price = 50
max_price = 5000
min_market_cap_cr = 5000
min_atr_pct = 0.5
max_stocks_to_llm = 100
llm_pick_count = 15

[strategy]
backtest_days = 30
candle_interval = "15minute"
min_confidence = 0.5
min_reward_risk = 1.5
max_trades_per_day = 2

[risk]
max_risk_per_trade_pct = 0.01
max_daily_loss_pct = 0.02
max_capital_deployed_pct = 0.50
max_concurrent_positions = 2

[execution]
entry_slippage_pct = 0.05
square_off_time = "15:10"
connection_timeout_sec = 30
heartbeat_interval_sec = 60
plan_max_age_hours = 14
max_entry_price_drift_pct = 2.0

[llm]
provider = "anthropic"
model = "claude-sonnet-5"
timeout_sec = 60
max_retries = 1
base_url = ""

[paper]
slippage_pct = 0.05
initial_capital = 400000
"""


def make_trade(trade_date, symbol, pnl):
    return ExecutedTrade(
        trade_date=trade_date,
        symbol=symbol,
        strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG,
        quantity=10,
        entry_price=100.0,
        exit_price=100.0 + pnl / 10,
        stop_loss=95.0,
        target_1=110.0,
        target_2=115.0,
        entered_at=datetime(2026, 9, 24, 9, 45, tzinfo=IST),
        exited_at=datetime(2026, 9, 24, 13, 15, tzinfo=IST),
        pnl=pnl,
        exit_reason="target_1",
        status=TradeStatus.CLOSED,
        mode=Mode.PAPER,
    )


@pytest.fixture()
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("KITE_API_KEY", "k")
    monkeypatch.setenv("KITE_API_SECRET", "s")
    (tmp_path / "config.toml").write_text(CONFIG_TEXT)

    db = Database(tmp_path / "tradingbot.db")
    db.initialise()
    db.record_trade(make_trade("2026-09-24", "RELIANCE", 1040.0))
    db.record_trade(make_trade("2026-09-24", "TCS", -400.0))
    db.record_trade(make_trade("2026-09-23", "INFY", 500.0))
    db.close()

    app = create_app(config_path=tmp_path / "config.toml", data_dir=tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_get_trades_returns_recent_history(client):
    response = await client.get("/api/trades?days=30")

    assert response.status_code == 200
    trades = response.json()
    assert len(trades) == 3
    symbols = [t["symbol"] for t in trades]
    assert "RELIANCE" in symbols


async def test_get_trades_filters_by_date(client):
    response = await client.get("/api/trades?date=2026-09-24")

    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_get_trade_stats(client):
    response = await client.get("/api/trades/stats?days=30")

    assert response.status_code == 200
    stats = response.json()
    assert stats["trade_count"] == 3
    assert stats["total_pnl"] == pytest.approx(1140.0)
    assert stats["win_rate"] == pytest.approx(2 / 3)


async def test_get_trades_empty_database(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("KITE_API_KEY", "k")
    monkeypatch.setenv("KITE_API_SECRET", "s")
    (tmp_path / "config.toml").write_text(CONFIG_TEXT)

    app = create_app(config_path=tmp_path / "config.toml", data_dir=tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/trades?days=30")

    assert response.status_code == 200
    assert response.json() == []
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/api/ -v`
Expected: FAIL — new test files reference routes that don't exist yet.

- [ ] **Step 5: Implement the four route modules**

Create `tradingbot/api/health_routes.py`:

```python
"""GET /api/health — server and dependency status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from tradingbot.api.app import get_state
from tradingbot.api.state import AppState

router = APIRouter(prefix="/api")


@router.get("/health")
async def health(request: Request):
    state: AppState = request.app.state.app_state
    db_ok = True
    try:
        state.database.connection.execute("SELECT 1")
    except Exception:  # noqa: BLE001
        db_ok = False

    return {
        "api": "ok",
        "database": "ok" if db_ok else "error",
        "llm": "unconfigured",
    }
```

Create `tradingbot/api/config_routes.py`:

```python
"""Config CRUD routes."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from tradingbot.api.state import AppState
from tradingbot.core.config import ConfigError, load_config
from tradingbot.core.models import Mode

router = APIRouter(prefix="/api")

PROVIDERS = [
    {"name": "anthropic", "env_key": "ANTHROPIC_API_KEY", "models": ["claude-sonnet-5", "claude-haiku-4-5"]},
    {"name": "openai", "env_key": "OPENAI_API_KEY", "models": ["gpt-4o", "gpt-4o-mini", "openai/gpt-oss-120b"]},
]


def _mask_secret(value: str) -> str:
    if not value or len(value) <= 6:
        return "***"
    return "***" + value[-3:]


def _config_to_dict(state: AppState) -> dict[str, Any]:
    config = state.config
    return {
        "general": {"mode": config.general.mode.value, "capital": config.general.capital, "log_level": config.general.log_level},
        "scanner": {
            "min_volume": config.scanner.min_volume, "min_price": config.scanner.min_price,
            "max_price": config.scanner.max_price, "min_market_cap_cr": config.scanner.min_market_cap_cr,
            "min_atr_pct": config.scanner.min_atr_pct, "max_stocks_to_llm": config.scanner.max_stocks_to_llm,
            "llm_pick_count": config.scanner.llm_pick_count,
        },
        "strategy": {
            "backtest_days": config.strategy.backtest_days, "candle_interval": config.strategy.candle_interval,
            "min_confidence": config.strategy.min_confidence, "min_reward_risk": config.strategy.min_reward_risk,
            "max_trades_per_day": config.strategy.max_trades_per_day,
        },
        "risk": {
            "max_risk_per_trade_pct": config.risk.max_risk_per_trade_pct,
            "max_daily_loss_pct": config.risk.max_daily_loss_pct,
            "max_capital_deployed_pct": config.risk.max_capital_deployed_pct,
            "max_concurrent_positions": config.risk.max_concurrent_positions,
        },
        "execution": {
            "entry_slippage_pct": config.execution.entry_slippage_pct,
            "square_off_time": config.execution.square_off_time.strftime("%H:%M"),
            "connection_timeout_sec": config.execution.connection_timeout_sec,
            "heartbeat_interval_sec": config.execution.heartbeat_interval_sec,
            "plan_max_age_hours": config.execution.plan_max_age_hours,
            "max_entry_price_drift_pct": config.execution.max_entry_price_drift_pct,
        },
        "llm": {
            "provider": config.llm.provider, "model": config.llm.model,
            "timeout_sec": config.llm.timeout_sec, "max_retries": config.llm.max_retries,
            "base_url": config.llm.base_url,
        },
        "paper": {"slippage_pct": config.paper.slippage_pct, "initial_capital": config.paper.initial_capital},
        "secrets": {
            "anthropic_api_key": _mask_secret(config.secrets.anthropic_api_key),
            "kite_api_key": _mask_secret(config.secrets.kite_api_key),
            "kite_api_secret": _mask_secret(config.secrets.kite_api_secret),
            "openai_api_key": _mask_secret(config.secrets.openai_api_key),
        },
    }


@router.get("/config")
async def get_config(request: Request):
    state: AppState = request.app.state.app_state
    return _config_to_dict(state)


@router.put("/config")
async def put_config(request: Request):
    state: AppState = request.app.state.app_state
    body = await request.json()

    config_path = Path(state.config_path)
    with config_path.open("rb") as f:
        existing = tomllib.load(f)

    for section, values in body.items():
        if section == "secrets":
            continue
        if section not in existing:
            raise HTTPException(status_code=400, detail=f"unknown section: {section}")
        if isinstance(values, dict):
            existing[section].update(values)

    if "general" in body and "mode" in body["general"]:
        try:
            Mode(body["general"]["mode"])
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid mode: {body['general']['mode']!r}")

    lines = []
    for section, values in existing.items():
        lines.append(f"[{section}]")
        for key, val in values.items():
            if isinstance(val, str):
                lines.append(f'{key} = "{val}"')
            elif isinstance(val, bool):
                lines.append(f"{key} = {'true' if val else 'false'}")
            elif isinstance(val, (int, float)):
                lines.append(f"{key} = {val}")
            else:
                lines.append(f'{key} = "{val}"')
        lines.append("")
    config_path.write_text("\n".join(lines))

    if "secrets" in body:
        env_path = Path(state.data_dir) / ".env"
        env_lines = []
        if env_path.exists():
            env_lines = env_path.read_text().splitlines()
        for key, val in body["secrets"].items():
            env_key = key.upper()
            found = False
            for i, line in enumerate(env_lines):
                if line.startswith(f"{env_key}="):
                    env_lines[i] = f"{env_key}={val}"
                    found = True
                    break
            if not found:
                env_lines.append(f"{env_key}={val}")
        env_path.write_text("\n".join(env_lines) + "\n")

    try:
        state.config = load_config(config_path)
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"status": "updated"}


@router.get("/config/providers")
async def get_providers(request: Request):
    state: AppState = request.app.state.app_state
    result = []
    for p in PROVIDERS:
        key = getattr(state.config.secrets, p["env_key"].lower().replace("_api_key", "_api_key"), "")
        if p["name"] == "anthropic":
            key = state.config.secrets.anthropic_api_key
        elif p["name"] == "openai":
            key = state.config.secrets.openai_api_key
        result.append({
            "name": p["name"],
            "has_key": bool(key),
            "models": p["models"],
        })
    return result


@router.post("/config/test-llm")
async def test_llm(request: Request):
    state: AppState = request.app.state.app_state
    try:
        from tradingbot.core.llm.anthropic_provider import build_provider
        provider = build_provider(state.config.llm, state.config.secrets)
        ok = await provider.health_check()
        return {"ok": ok}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
```

Create `tradingbot/api/plan_routes.py`:

```python
"""Plan CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from tradingbot.api.state import AppState
from tradingbot.core.plan_store import PlanCorruptError, PlanNotFoundError

router = APIRouter(prefix="/api")


@router.get("/plans")
async def list_plans(request: Request):
    state: AppState = request.app.state.app_state
    plans = []
    for path in sorted(state.plan_store.plan_dir.glob("*.json")):
        try:
            plan = state.plan_store.load(path.stem)
            plans.append({
                "trade_date": plan.trade_date,
                "legs_count": len(plan.legs),
                "market_regime": plan.market_regime.value,
                "generated_at": plan.generated_at.isoformat(),
            })
        except (PlanNotFoundError, PlanCorruptError):
            continue
    return plans


@router.get("/plans/{date}")
async def get_plan(date: str, request: Request):
    state: AppState = request.app.state.app_state
    try:
        plan = state.plan_store.load(date)
        return plan.to_dict()
    except PlanNotFoundError:
        raise HTTPException(status_code=404, detail=f"no plan for {date}")
    except PlanCorruptError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/plans/{date}")
async def delete_plan(date: str, request: Request):
    state: AppState = request.app.state.app_state
    path = state.plan_store.path_for(date)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"no plan for {date}")
    path.unlink()
    return {"status": "deleted", "trade_date": date}
```

Create `tradingbot/api/trade_routes.py`:

```python
"""Trade history and stats routes."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request

from tradingbot.api.state import AppState
from tradingbot.core.models import now_ist

router = APIRouter(prefix="/api")


@router.get("/trades")
async def get_trades(request: Request, days: int = 30, date: str | None = None):
    state: AppState = request.app.state.app_state
    if date is not None:
        trades = state.database.trades_for_date(date)
    else:
        today = now_ist().date()
        trades = state.database.recent_trades(days=days, today=today)

    return [
        {
            "trade_date": t.trade_date,
            "symbol": t.symbol,
            "strategy": t.strategy.value,
            "direction": t.direction.value,
            "quantity": t.quantity,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "pnl": t.pnl,
            "exit_reason": t.exit_reason,
            "status": t.status.value,
            "mode": t.mode.value,
            "entered_at": t.entered_at.isoformat(),
            "exited_at": t.exited_at.isoformat(),
        }
        for t in trades
    ]


@router.get("/trades/stats")
async def get_trade_stats(request: Request, days: int = 30):
    state: AppState = request.app.state.app_state
    today = now_ist().date()
    trades = state.database.recent_trades(days=days, today=today)

    if not trades:
        return {
            "trade_count": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
            "max_drawdown": 0.0,
            "best_day": 0.0,
            "worst_day": 0.0,
        }

    wins = [t for t in trades if t.pnl > 0]
    total = sum(t.pnl for t in trades)

    daily_pnl: dict[str, float] = {}
    for t in trades:
        daily_pnl[t.trade_date] = daily_pnl.get(t.trade_date, 0.0) + t.pnl
    daily_values = list(daily_pnl.values())

    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for day_pnl in daily_values:
        cumulative += day_pnl
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)

    return {
        "trade_count": len(trades),
        "win_rate": len(wins) / len(trades),
        "total_pnl": total,
        "avg_pnl": total / len(trades),
        "max_drawdown": max_drawdown,
        "best_day": max(daily_values),
        "worst_day": min(daily_values),
    }
```

- [ ] **Step 6: Update app.py to register the routers and remove the inline health endpoint**

Replace the inline `/api/health` endpoint in `app.py` with router includes:

```python
# Add after app creation, before return:
from tradingbot.api.health_routes import router as health_router
from tradingbot.api.config_routes import router as config_router
from tradingbot.api.plan_routes import router as plan_router
from tradingbot.api.trade_routes import router as trade_router

app.include_router(health_router)
app.include_router(config_router)
app.include_router(plan_router)
app.include_router(trade_router)
```

Remove the inline `@app.get("/api/health")` function from `app.py`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/api/ -v`
Expected: PASS — ~18 tests.

- [ ] **Step 8: Run full suite**

Run: `pytest tests/ -q --tb=short`
Expected: ~297 passed.

- [ ] **Step 9: Commit**

```bash
git add tradingbot/api/ tests/api/
git commit -m "feat: add config, plan, trade, and health REST routes"
```

---

## Task 4: Analysis Routes (Background Task + WebSocket Events)

**Files:**
- Create: `tradingbot/api/analysis_routes.py`
- Modify: `tradingbot/api/app.py` (register analysis router)
- Test: `tests/api/test_analysis_routes.py`

**Interfaces:**
- Consumes: `AppState` (Task 2); `EventBus` (Task 1); `PlanGenerator`, `build_analysis_stack` pattern from cli.py; `next_trading_day`, `NotATradingDayError` from scanner.calendar.
- Produces:
  - `POST /api/analyze` — starts background analysis, returns 200 `{status, trade_date}` or 409 if already running.
  - `GET /api/analyze/status` — returns `{status, trade_date?, error?}`.
  - `POST /api/analyze/cancel` — cancels a running analysis.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_analysis_routes.py`:

```python
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tradingbot.api.app import create_app

CONFIG_TEXT = """\
[general]
mode = "paper"
capital = 400000
log_level = "INFO"

[scanner]
min_volume = 500000
min_price = 50
max_price = 5000
min_market_cap_cr = 5000
min_atr_pct = 0.5
max_stocks_to_llm = 100
llm_pick_count = 15

[strategy]
backtest_days = 30
candle_interval = "15minute"
min_confidence = 0.5
min_reward_risk = 1.5
max_trades_per_day = 2

[risk]
max_risk_per_trade_pct = 0.01
max_daily_loss_pct = 0.02
max_capital_deployed_pct = 0.50
max_concurrent_positions = 2

[execution]
entry_slippage_pct = 0.05
square_off_time = "15:10"
connection_timeout_sec = 30
heartbeat_interval_sec = 60
plan_max_age_hours = 14
max_entry_price_drift_pct = 2.0

[llm]
provider = "anthropic"
model = "claude-sonnet-5"
timeout_sec = 60
max_retries = 1
base_url = ""

[paper]
slippage_pct = 0.05
initial_capital = 400000
"""


@pytest.fixture()
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("KITE_API_KEY", "k")
    monkeypatch.setenv("KITE_API_SECRET", "s")
    (tmp_path / "config.toml").write_text(CONFIG_TEXT)

    app = create_app(config_path=tmp_path / "config.toml", data_dir=tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_analyze_status_is_idle_initially(client):
    response = await client.get("/api/analyze/status")

    assert response.status_code == 200
    assert response.json()["status"] == "idle"


async def test_analyze_returns_409_when_already_running(client):
    state = client._transport.app.state.app_state
    state.analysis_status = "running"
    state.analysis_task = asyncio.ensure_future(asyncio.sleep(999))

    response = await client.post("/api/analyze")

    assert response.status_code == 409

    state.analysis_task.cancel()
    try:
        await state.analysis_task
    except asyncio.CancelledError:
        pass


async def test_analyze_rejects_non_trading_day(client):
    response = await client.post("/api/analyze", json={"trade_date": "2026-09-26"})

    assert response.status_code == 400
    assert "trading day" in response.json()["detail"].lower()


async def test_analyze_cancel_when_idle_returns_ok(client):
    response = await client.post("/api/analyze/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "idle"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_analysis_routes.py -v`
Expected: FAIL — module not found or route not registered.

- [ ] **Step 3: Implement analysis routes**

Create `tradingbot/api/analysis_routes.py`:

```python
"""Analysis routes — start, status, cancel."""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Request

from tradingbot.api.state import AppState
from tradingbot.core.models import now_ist
from tradingbot.scanner.calendar import NotATradingDayError, is_trading_day, next_trading_day

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


async def _run_analysis(state: AppState, trade_date: date) -> None:
    """Background task that runs the full analysis pipeline."""
    try:
        from tradingbot.core.llm.anthropic_provider import build_provider
        from tradingbot.core.plan_store import PlanStore
        from tradingbot.core.risk_manager import RiskManager
        from tradingbot.scanner.data_fetcher import DataFetcher
        from tradingbot.scanner.market_analyzer import MarketAnalyzer
        from tradingbot.scanner.market_context import MarketContextFetcher
        from tradingbot.scanner.scanner import Scanner
        from tradingbot.strategy.backtester import Backtester
        from tradingbot.strategy.plan_generator import PlanGenerator
        from tradingbot.strategy.strategy_selector import StrategySelector

        config = state.config
        log_dir = state.data_dir + "/logs"

        provider = build_provider(config.llm, config.secrets, log_dir=log_dir + "/llm")
        fetcher = DataFetcher()
        risk_manager = RiskManager(
            config.risk, config.strategy, capital=config.general.capital,
            plan_max_age_hours=config.execution.plan_max_age_hours,
            max_entry_price_drift_pct=config.execution.max_entry_price_drift_pct,
        )

        scanner = Scanner(
            fetcher=fetcher,
            context_fetcher=MarketContextFetcher(),
            analyzer=MarketAnalyzer(provider, config.scanner),
            config=config.scanner,
            event_bus=state.event_bus,
        )

        generator = PlanGenerator(
            scanner=scanner,
            fetcher=fetcher,
            selector=StrategySelector(provider, config.strategy),
            risk_manager=risk_manager,
            plan_store=state.plan_store,
            strategy_config=config.strategy,
            capital=config.general.capital,
            event_bus=state.event_bus,
        )

        await state.event_bus.emit("analysis.started", {"trade_date": trade_date.isoformat()})
        plan = await generator.generate(trade_date)

        state.database.save_plan_snapshot(plan)
        state.analysis_status = "complete"
        state.analysis_error = None

        await state.event_bus.emit("analysis.complete", {
            "trade_date": plan.trade_date,
            "legs_count": len(plan.legs),
            "plan_summary": plan.market_summary,
        })

    except asyncio.CancelledError:
        state.analysis_status = "idle"
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("analysis failed: %s", exc, exc_info=True)
        state.analysis_status = "failed"
        state.analysis_error = str(exc)
        await state.event_bus.emit("analysis.failed", {"error": str(exc)})


@router.post("/analyze")
async def start_analysis(request: Request):
    state: AppState = request.app.state.app_state
    body = await request.json() if await request.body() else {}

    if state.analysis_status == "running":
        raise HTTPException(status_code=409, detail="analysis already running")

    if "trade_date" in body:
        trade_date = date.fromisoformat(body["trade_date"])
        if not is_trading_day(trade_date):
            raise HTTPException(status_code=400, detail=f"{trade_date} is not a trading day")
    else:
        trade_date = next_trading_day(now_ist().date())

    state.analysis_status = "running"
    state.analysis_trade_date = trade_date.isoformat()
    state.analysis_error = None
    state.analysis_task = asyncio.create_task(_run_analysis(state, trade_date))

    return {"status": "started", "trade_date": trade_date.isoformat()}


@router.get("/analyze/status")
async def analysis_status(request: Request):
    state: AppState = request.app.state.app_state
    return {
        "status": state.analysis_status,
        "trade_date": state.analysis_trade_date,
        "error": state.analysis_error,
    }


@router.post("/analyze/cancel")
async def cancel_analysis(request: Request):
    state: AppState = request.app.state.app_state
    if state.analysis_task is not None and not state.analysis_task.done():
        state.analysis_task.cancel()
        state.analysis_status = "idle"
        return {"status": "cancelled"}
    return {"status": state.analysis_status}
```

- [ ] **Step 4: Register the router in app.py**

Add to `app.py`:

```python
from tradingbot.api.analysis_routes import router as analysis_router
app.include_router(analysis_router)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/api/test_analysis_routes.py -v`
Expected: PASS — 4 tests.

- [ ] **Step 6: Commit**

```bash
git add tradingbot/api/analysis_routes.py tradingbot/api/app.py tests/api/test_analysis_routes.py
git commit -m "feat: add analysis routes with background task and event streaming"
```

---

## Task 5: Execution Routes

**Files:**
- Create: `tradingbot/api/execution_routes.py`
- Modify: `tradingbot/api/app.py` (register execution router)
- Test: `tests/api/test_execution_routes.py`

**Interfaces:**
- Consumes: `AppState` (Task 2); `EventBus` (Task 1); `Executor`, `PlanStore`, `RiskManager`, `VirtualBroker`, `Database`, `Mode`.
- Produces:
  - `POST /api/execute` — starts background execution, 200 or 409/400.
  - `POST /api/execute/stop` — graceful stop.
  - `GET /api/execute/status` — status, positions, P&L.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_execution_routes.py`:

```python
import asyncio
from datetime import datetime, time

import pytest
from httpx import ASGITransport, AsyncClient

from tradingbot.api.app import create_app
from tradingbot.core.models import (
    IST,
    Direction,
    EntryType,
    MarketRegime,
    StrategyName,
    TradeLeg,
    TradePlan,
)
from tradingbot.core.plan_store import PlanStore

CONFIG_TEXT = """\
[general]
mode = "paper"
capital = 400000
log_level = "INFO"

[scanner]
min_volume = 500000
min_price = 50
max_price = 5000
min_market_cap_cr = 5000
min_atr_pct = 0.5
max_stocks_to_llm = 100
llm_pick_count = 15

[strategy]
backtest_days = 30
candle_interval = "15minute"
min_confidence = 0.5
min_reward_risk = 1.5
max_trades_per_day = 2

[risk]
max_risk_per_trade_pct = 0.01
max_daily_loss_pct = 0.02
max_capital_deployed_pct = 0.50
max_concurrent_positions = 2

[execution]
entry_slippage_pct = 0.05
square_off_time = "15:10"
connection_timeout_sec = 30
heartbeat_interval_sec = 60
plan_max_age_hours = 14
max_entry_price_drift_pct = 2.0

[llm]
provider = "anthropic"
model = "claude-sonnet-5"
timeout_sec = 60
max_retries = 1
base_url = ""

[paper]
slippage_pct = 0.05
initial_capital = 400000
"""


@pytest.fixture()
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("KITE_API_KEY", "k")
    monkeypatch.setenv("KITE_API_SECRET", "s")
    (tmp_path / "config.toml").write_text(CONFIG_TEXT)

    app = create_app(config_path=tmp_path / "config.toml", data_dir=tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_execute_status_is_idle_initially(client):
    response = await client.get("/api/execute/status")

    assert response.status_code == 200
    assert response.json()["status"] == "idle"


async def test_execute_returns_400_when_no_plan(client):
    response = await client.post("/api/execute", json={"mode": "paper"})

    assert response.status_code == 400
    assert "no plan" in response.json()["detail"].lower()


async def test_execute_returns_409_when_already_running(client):
    state = client._transport.app.state.app_state
    state.executor_status = "running"
    state.executor_task = asyncio.ensure_future(asyncio.sleep(999))

    response = await client.post("/api/execute", json={"mode": "paper"})

    assert response.status_code == 409

    state.executor_task.cancel()
    try:
        await state.executor_task
    except asyncio.CancelledError:
        pass


async def test_execute_stop_when_idle_returns_ok(client):
    response = await client.post("/api/execute/stop")

    assert response.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_execution_routes.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement execution routes**

Create `tradingbot/api/execution_routes.py`:

```python
"""Execution routes — start, stop, status."""

from __future__ import annotations

import asyncio
import logging
import time as time_module

from fastapi import APIRouter, HTTPException, Request

from tradingbot.api.state import AppState
from tradingbot.core.config import PaperConfig
from tradingbot.core.models import Mode, now_ist
from tradingbot.core.plan_store import PlanNotFoundError
from tradingbot.core.risk_manager import RiskManager
from tradingbot.executor.executor import Executor
from tradingbot.core.database import Database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

TICK_SECONDS = 5


async def _run_execution(state: AppState, mode: Mode, plan) -> None:
    """Background task that runs the executor loop."""
    try:
        config = state.config

        if mode is Mode.PAPER:
            from tradingbot.paper.virtual_broker import VirtualBroker
            from tradingbot.scanner.data_fetcher import DataFetcher

            fetcher = DataFetcher()

            def price_feed(symbol: str) -> float:
                candles = fetcher.fetch_candles(symbol, days=1, interval="5m")
                return float(candles["close"].iloc[-1])

            broker = VirtualBroker(config.paper, price_feed=price_feed)
        else:
            from tradingbot.core.kite_client import KiteClient
            from pathlib import Path

            token_path = Path.home() / ".tradingbot" / "kite_token"
            broker = KiteClient(
                api_key=config.secrets.kite_api_key,
                api_secret=config.secrets.kite_api_secret,
                access_token=token_path.read_text().strip() if token_path.exists() else "",
            )

        risk_manager = RiskManager(
            config.risk, config.strategy, capital=config.general.capital,
            plan_max_age_hours=config.execution.plan_max_age_hours,
            max_entry_price_drift_pct=config.execution.max_entry_price_drift_pct,
        )

        executor = Executor(
            broker=broker,
            plan=plan,
            risk_manager=risk_manager,
            database=state.database,
            execution_config=config.execution,
            mode=mode,
            event_bus=state.event_bus,
        )

        state.executor_ref = executor
        await state.event_bus.emit("exec.started", {
            "trade_date": plan.trade_date,
            "mode": mode.value,
            "legs": [leg.to_dict() for leg in plan.legs],
        })

        executor.start()

        while not executor.is_done:
            executor.tick()
            await asyncio.sleep(TICK_SECONDS)

        state.executor_status = "done"
        await state.event_bus.emit("exec.session_done", {
            "total_pnl": state.database.realised_pnl_for_date(plan.trade_date),
            "trades_count": len(state.database.trades_for_date(plan.trade_date)),
            "mode": mode.value,
        })

    except asyncio.CancelledError:
        state.executor_status = "idle"
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("execution failed: %s", exc, exc_info=True)
        state.executor_status = "idle"


@router.post("/execute")
async def start_execution(request: Request):
    state: AppState = request.app.state.app_state
    body = await request.json() if await request.body() else {}

    if state.executor_status == "running":
        raise HTTPException(status_code=409, detail="executor already running")

    mode_str = body.get("mode", state.config.general.mode.value)
    mode = Mode(mode_str)
    trade_date = body.get("date")

    try:
        if trade_date:
            plan = state.plan_store.load(trade_date)
        else:
            plan = state.plan_store.load_latest()
    except PlanNotFoundError as exc:
        raise HTTPException(status_code=400, detail=f"no plan found: {exc}")

    state.executor_status = "running"
    state.executor_mode = mode.value
    state.executor_task = asyncio.create_task(_run_execution(state, mode, plan))

    return {"status": "started", "mode": mode.value, "trade_date": plan.trade_date}


@router.post("/execute/stop")
async def stop_execution(request: Request):
    state: AppState = request.app.state.app_state
    if state.executor_ref is not None:
        state.executor_ref.kill_switch_tripped = True
    if state.executor_task is not None and not state.executor_task.done():
        state.executor_task.cancel()
    state.executor_status = "idle"
    return {"status": "stopped"}


@router.get("/execute/status")
async def execution_status(request: Request):
    state: AppState = request.app.state.app_state
    positions = []
    if state.executor_ref is not None:
        for leg_state in state.executor_ref.states:
            if leg_state.filled_quantity > 0:
                positions.append({
                    "symbol": leg_state.leg.symbol,
                    "direction": leg_state.leg.direction.value,
                    "quantity": leg_state.filled_quantity,
                    "entry_price": leg_state.entry_fill_price,
                    "current_stop": leg_state.current_stop,
                    "target_1_booked": leg_state.target_1_booked,
                    "pnl": leg_state.realised_pnl,
                })

    return {
        "status": state.executor_status,
        "mode": state.executor_mode,
        "positions": positions,
    }
```

- [ ] **Step 4: Register the router in app.py**

Add to `app.py`:

```python
from tradingbot.api.execution_routes import router as execution_router
app.include_router(execution_router)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/api/test_execution_routes.py -v`
Expected: PASS — 4 tests.

- [ ] **Step 6: Commit**

```bash
git add tradingbot/api/execution_routes.py tradingbot/api/app.py tests/api/test_execution_routes.py
git commit -m "feat: add execution routes with background trading loop"
```

---

## Task 6: EventBus Integration into Scanner and Strategy Modules

**Files:**
- Modify: `tradingbot/scanner/scanner.py`
- Modify: `tradingbot/scanner/market_analyzer.py`
- Modify: `tradingbot/strategy/plan_generator.py`
- Test: `tests/scanner/test_scanner.py` (add event emission tests), `tests/strategy/test_plan_generator.py` (add event emission tests)

**Interfaces:**
- Consumes: `EventBus` (Task 1).
- Produces: existing modules now emit analysis events when `event_bus` is provided. All existing tests still pass with `event_bus=None`.

- [ ] **Step 1: Write the failing test for scanner event emission**

Add to `tests/scanner/test_scanner.py`:

```python
from tradingbot.core.events import EventBus


async def test_scan_emits_universe_and_filtered_events():
    bus = EventBus()
    events = []
    bus.subscribe(lambda e: events.append(e))

    fetcher = StubFetcher([make_stock("RELIANCE"), make_stock("ILLIQUID", avg_volume=10.0)])
    scanner = Scanner(fetcher, StubContextFetcher(), StubAnalyzer([]), make_config(), event_bus=bus)

    await scanner.scan(date(2026, 9, 24))

    types = [e["type"] for e in events]
    assert "scan.universe" in types
    assert "scan.filtered" in types
    assert "scan.context" in types
```

- [ ] **Step 2: Write the failing test for plan generator event emission**

Add to `tests/strategy/test_plan_generator.py`:

```python
from tradingbot.core.events import EventBus


async def test_generate_emits_analysis_events(tmp_path):
    bus = EventBus()
    events = []
    bus.subscribe(lambda e: events.append(e))

    generator, _ = make_generator(tmp_path, make_shortlist("RELIANCE"), [make_setup("RELIANCE")])
    generator.event_bus = bus

    await generator.generate(date(2026, 9, 24))

    types = [e["type"] for e in events]
    assert "strategy.indicators" in types or "strategy.setups" in types
    assert "strategy.sized" in types
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/scanner/test_scanner.py::test_scan_emits_universe_and_filtered_events tests/strategy/test_plan_generator.py::test_generate_emits_analysis_events -v`
Expected: FAIL — Scanner and PlanGenerator don't accept event_bus yet.

- [ ] **Step 4: Add event_bus to Scanner**

In `tradingbot/scanner/scanner.py`, modify `Scanner.__init__`:

```python
def __init__(self, fetcher, context_fetcher, analyzer, config: ScannerConfig, *, event_bus=None) -> None:
    self.fetcher = fetcher
    self.context_fetcher = context_fetcher
    self.analyzer = analyzer
    self.config = config
    self.event_bus = event_bus
```

Add emit calls in `scan()`:

```python
async def scan(self, trade_date: date) -> ScanResult:
    if not is_trading_day(trade_date):
        raise NotATradingDayError(...)

    symbols = self.fetcher.fetch_universe()
    if self.event_bus:
        await self.event_bus.emit("scan.universe", {"count": len(symbols), "symbols": symbols})

    stocks = self.fetcher.fetch_stock_metrics(symbols)
    filter_result = apply_filters(stocks, self.config)
    if self.event_bus:
        await self.event_bus.emit("scan.filtered", {
            "passed_count": len(filter_result.passed),
            "rejected": filter_result.rejected,
            "stocks": [{"symbol": s.symbol, "price": s.last_price, "volume": s.avg_volume} for s in filter_result.passed[:20]],
        })

    context = self.context_fetcher.fetch()
    if self.event_bus:
        await self.event_bus.emit("scan.context", context.to_dict())

    shortlist = await self.analyzer.shortlist(filter_result.passed, context)
    if self.event_bus:
        await self.event_bus.emit("scan.shortlist", {
            "count": len(shortlist),
            "picks": [{"symbol": s.symbol, "reasoning": s.reasoning, "strategy_bias": s.suggested_strategy.value, "direction": s.direction_bias} for s in shortlist],
        })

    return ScanResult(...)
```

- [ ] **Step 5: Add event_bus to PlanGenerator**

In `tradingbot/strategy/plan_generator.py`, add `event_bus=None` to `__init__` and emit events in `generate()`:

After computing indicators: `await self.event_bus.emit("strategy.indicators", snapshot.to_dict())`
After backtesting: `await self.event_bus.emit("strategy.backtest", {...})`
After selector returns: `await self.event_bus.emit("strategy.setups", {...})`
After risk manager: `await self.event_bus.emit("strategy.sized", {...})`

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/scanner/test_scanner.py tests/strategy/test_plan_generator.py -v`
Expected: PASS — all existing + 2 new tests.

- [ ] **Step 7: Run full suite to verify no regressions**

Run: `pytest tests/ -q --tb=short`
Expected: all passing (event_bus=None default means existing tests unchanged).

- [ ] **Step 8: Commit**

```bash
git add tradingbot/scanner/scanner.py tradingbot/strategy/plan_generator.py tests/scanner/test_scanner.py tests/strategy/test_plan_generator.py
git commit -m "feat: integrate EventBus into scanner and strategy pipeline"
```

---

## Task 7: EventBus Integration into Executor

**Files:**
- Modify: `tradingbot/executor/executor.py`
- Test: `tests/executor/test_executor.py` (add event emission test)

**Interfaces:**
- Consumes: `EventBus.emit_sync` (Task 1) — the executor is synchronous.
- Produces: executor emits `exec.*` events via `emit_sync` when `event_bus` is provided.

**IMPORTANT:** The executor uses `emit_sync`, NOT `await emit`. The executor's `tick()` is synchronous.

- [ ] **Step 1: Write the failing test**

Add to `tests/executor/test_executor.py`:

```python
from tradingbot.core.events import EventBus
import asyncio


async def test_executor_emits_events_when_event_bus_provided(tmp_path):
    bus = EventBus()
    events = []
    bus.subscribe(lambda e: events.append(e))

    flush_task = asyncio.create_task(bus.flush_loop())

    prices = {"RELIANCE": 100.0}
    broker = VirtualBroker(PaperConfig(slippage_pct=0.0, initial_capital=400000.0), lambda s: prices[s])
    database = Database(tmp_path / "exec_events.db")
    database.initialise()
    risk_manager = RiskManager(
        RiskConfig(max_risk_per_trade_pct=0.01, max_daily_loss_pct=0.02, max_capital_deployed_pct=0.50, max_concurrent_positions=2),
        StrategyConfig(backtest_days=30, candle_interval="15minute", min_confidence=0.5, min_reward_risk=1.5, max_trades_per_day=2),
        capital=400000.0,
    )
    executor = Executor(
        broker=broker,
        plan=make_plan([make_leg()]),
        risk_manager=risk_manager,
        database=database,
        execution_config=make_execution_config(),
        mode=Mode.PAPER,
        clock=Clock(),
        event_bus=bus,
    )

    executor.start()
    broker.advance()
    executor.tick()

    await asyncio.sleep(0.15)
    await bus.shutdown()
    flush_task.cancel()
    try:
        await flush_task
    except asyncio.CancelledError:
        pass

    types = [e["type"] for e in events]
    assert "exec.started" in types
    assert "exec.entry_filled" in types or "exec.entry_placed" in types

    database.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/executor/test_executor.py::test_executor_emits_events_when_event_bus_provided -v`
Expected: FAIL — Executor doesn't accept event_bus yet.

- [ ] **Step 3: Add event_bus to Executor**

In `tradingbot/executor/executor.py`, add `event_bus=None` to `Executor.__init__` and `emit_sync` calls at key points:

```python
def __init__(self, ..., event_bus=None):
    ...
    self.event_bus = event_bus

def start(self):
    ...
    if self.event_bus:
        self.event_bus.emit_sync("exec.started", {
            "trade_date": self.plan.trade_date,
            "mode": self.mode.value,
            "legs": [leg.to_dict() for leg in self.plan.legs],
        })

def _poll_entry(self, state, now):
    ...
    # After fill detected:
    if self.event_bus:
        self.event_bus.emit_sync("exec.entry_filled", {
            "symbol": state.leg.symbol,
            "fill_price": state.entry_fill_price,
            "quantity": state.filled_quantity,
        })

def _close(self, state, quantity, price, reason, now):
    ...
    if self.event_bus:
        self.event_bus.emit_sync(f"exec.{reason}", {
            "symbol": state.leg.symbol,
            "price": price,
            "pnl": pnl,
        })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/executor/ -v`
Expected: PASS — all existing + 1 new test.

- [ ] **Step 5: Verify the LLM import guard still passes**

Run: `pytest tests/executor/test_no_llm_imports.py -v`
Expected: PASS — EventBus is in `core/events.py`, not `core/llm/`.

- [ ] **Step 6: Run full suite**

Run: `pytest tests/ -q --tb=short`
Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add tradingbot/executor/executor.py tests/executor/test_executor.py
git commit -m "feat: integrate EventBus into executor with emit_sync"
```

---

## Task 8: CLI `serve` Command

**Files:**
- Modify: `tradingbot/cli.py`
- Test: `tests/test_cli.py` (add serve command test)

**Interfaces:**
- Consumes: `create_app` from `tradingbot.api.app`.
- Produces: `tradingbot serve [--port N] [--reload]` command.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
def test_serve_command_is_listed_in_help():
    result = CliRunner().invoke(cli, ["--help"])

    assert "serve" in result.output


def test_serve_help_shows_port_option():
    result = CliRunner().invoke(cli, ["serve", "--help"])

    assert result.exit_code == 0
    assert "--port" in result.output
    assert "--reload" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py::test_serve_command_is_listed_in_help tests/test_cli.py::test_serve_help_shows_port_option -v`
Expected: FAIL — serve command not defined yet.

- [ ] **Step 3: Implement the serve command**

Add to `tradingbot/cli.py`:

```python
@cli.command()
@click.option("--port", default=8000, type=int, help="Port to listen on.")
@click.option("--reload", "use_reload", is_flag=True, help="Enable auto-reload for development.")
@click.pass_obj
def serve(obj: dict, port: int, use_reload: bool) -> None:
    """Start the web API server."""
    import uvicorn
    from tradingbot.api.app import create_app

    config_path = obj["config"].general if obj else None

    click.echo(f"Starting API server on http://0.0.0.0:{port}")
    click.echo("Press Ctrl+C to stop.")

    uvicorn.run(
        "tradingbot.api.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=port,
        reload=use_reload,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: PASS — all existing CLI tests + 2 new.

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -q --tb=short`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add tradingbot/cli.py tests/test_cli.py
git commit -m "feat: add tradingbot serve command for the web API"
```

---

## Done

The API layer is complete. You can now:

```bash
tradingbot serve              # starts FastAPI on :8000
```

Then test:
- `curl http://localhost:8000/api/health`
- `curl http://localhost:8000/api/config`
- `curl http://localhost:8000/api/plans`
- `curl -X POST http://localhost:8000/api/analyze`
- Connect a WebSocket client to `ws://localhost:8000/ws` to see pipeline events stream live

The existing CLI still works alongside the API server.

Next: Sub-project 2 (React frontend) consumes these endpoints and WebSocket.
