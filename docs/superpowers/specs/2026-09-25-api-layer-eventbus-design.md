# Web Dashboard Sub-project 1: API Layer + EventBus — Design Specification

## Overview

Wrap the existing trading bot modules with a FastAPI HTTP + WebSocket server so a React frontend (Sub-project 2) can drive the bot without the CLI. Add an EventBus that existing modules call at key pipeline stages, enabling the frontend to show real-time progress as analysis and execution unfold.

This sub-project is pure Python — no frontend code. The deliverable is a `tradingbot serve` command that starts a FastAPI server on port 8000, serving REST endpoints for config/plans/trades/history and a WebSocket endpoint that streams pipeline events.

### Goals

- REST API for config CRUD, plan listing, trade history, stats, health check
- POST endpoints that start analysis and execution as background tasks
- WebSocket endpoint that streams EventBus events to all connected clients
- EventBus integrated into scanner, strategy, and executor modules (optional parameter — CLI mode unaffected)
- `tradingbot serve` CLI command
- All endpoints testable without real LLM/broker calls

### Non-Goals

- React frontend (Sub-project 2)
- Authentication or multi-user support
- Cloud deployment
- Replacing the existing CLI (it stays functional alongside the API)

## Architecture

```
┌───────────────────────────────────────┐
│            FastAPI Server              │
│              Port 8000                 │
│                                        │
│  ┌────────────┐  ┌─────────────────┐  │
│  │  REST       │  │  WebSocket      │  │
│  │  Routers    │  │  /ws            │  │
│  │  /api/*     │  │  event stream   │  │
│  └─────┬──────┘  └───────┬─────────┘  │
│        │                  │            │
│  ┌─────┴──────────────────┴─────────┐ │
│  │        AppState                   │ │
│  │  - event_bus: EventBus            │ │
│  │  - analysis_task: Task | None     │ │
│  │  - executor_ref: Executor | None  │ │
│  │  - config: Config                 │ │
│  └─────────────┬─────────────────────┘ │
│                │                       │
│  ┌─────────────┴─────────────────────┐ │
│  │  Existing tradingbot modules       │ │
│  │  (scanner, strategy, executor...)  │ │
│  │  now accept optional event_bus     │ │
│  └───────────────────────────────────┘ │
└───────────────────────────────────────┘
```

## EventBus

```python
# tradingbot/core/events.py

class EventBus:
    """In-process pub/sub. Modules emit typed events; WebSocket handler relays them."""

    async def emit(self, event_type: str, data: dict) -> None:
        """Publish an event to all subscribers."""

    def subscribe(self, callback: Callable) -> str:
        """Register a callback, return a subscription ID."""

    def unsubscribe(self, sub_id: str) -> None:
        """Remove a subscription."""
```

Events are dicts with a standard envelope:

```json
{
  "type": "scan.filtered",
  "timestamp": "2026-09-25T22:30:00+05:30",
  "data": {"passed": 38, "rejected": {"volume": 8, "price": 1}}
}
```

### Analysis Events (emitted in order)

| Event Type | Emitted By | Data |
|-----------|-----------|------|
| `analysis.started` | plan_generator | `{trade_date}` |
| `scan.universe` | scanner | `{count, symbols}` |
| `scan.filtered` | scanner | `{passed_count, rejected: {reason: count}, stocks: [{symbol, price, volume}]}` |
| `scan.context` | scanner | `{nifty_level, nifty_trend, fii_net_cr, dii_net_cr, india_vix, regime}` |
| `scan.shortlist` | scanner/market_analyzer | `{count, picks: [{symbol, reasoning, strategy_bias, direction}]}` |
| `strategy.indicators` | plan_generator | `{symbol, rsi_14, macd, bb_position, atr_14, vwap, support_levels, resistance_levels}` |
| `strategy.backtest` | plan_generator | `{symbol, results: [{strategy, win_rate, trades, avg_rr}]}` |
| `strategy.setups` | plan_generator | `{count, setups: [{symbol, strategy, direction, entry, sl, t1, t2, confidence, reasoning}]}` |
| `strategy.sized` | plan_generator | `{approved: [{symbol, quantity, risk_amount}], dropped: [{symbol, reason}]}` |
| `analysis.complete` | plan_generator | `{trade_date, legs_count, plan_summary}` |
| `analysis.failed` | plan_generator | `{error}` |

### Execution Events (emitted during trading session)

| Event Type | Emitted By | Data |
|-----------|-----------|------|
| `exec.started` | executor | `{trade_date, mode, legs: [{symbol, direction, entry, sl, t1, t2, quantity}]}` |
| `exec.entry_placed` | executor | `{symbol, order_id, price, order_type}` |
| `exec.entry_filled` | executor | `{symbol, fill_price, quantity}` |
| `exec.entry_cancelled` | executor | `{symbol, reason}` |
| `exec.entry_skipped` | executor | `{symbol, reason}` |
| `exec.price_tick` | executor | `{symbol, price, unrealised_pnl, current_stop}` |
| `exec.target_1_hit` | executor | `{symbol, price, booked_qty, remaining_qty, new_stop}` |
| `exec.target_2_hit` | executor | `{symbol, price, pnl}` |
| `exec.stop_hit` | executor | `{symbol, price, pnl}` |
| `exec.square_off` | executor | `{symbol, price, pnl, reason}` |
| `exec.kill_switch` | executor | `{realised_pnl, limit}` |
| `exec.session_done` | executor | `{total_pnl, trades_count, mode}` |

## REST API

### Config

```
GET  /api/config              → full config with secrets masked
PUT  /api/config              → update config.toml + .env; validates before writing
GET  /api/config/providers    → [{name, has_key, models}] for each supported provider
POST /api/config/test-llm     → health_check() the configured provider; returns {ok, error?}
```

Config PUT accepts partial updates — only the sections included in the body are overwritten. Secrets (API keys) are written to `.env`, everything else to `config.toml`.

GET /api/config masks secrets: `"sk-ant-abc123xyz"` → `"sk-ant-***xyz"` (last 3 chars visible, rest replaced).

### Analysis

```
POST /api/analyze             → {status: "started", trade_date} — kicks off background task
GET  /api/analyze/status      → {status: "idle"|"running"|"complete"|"failed", trade_date?, error?}
POST /api/analyze/cancel      → cancel a running analysis
```

POST /api/analyze accepts optional `{trade_date: "2026-09-28"}`. Defaults to next trading day. Returns 409 if analysis already running.

### Execution

```
POST /api/execute             → {status: "started", mode, trade_date}
                                body: {mode: "paper"|"live", date?: "2026-09-28"}
POST /api/execute/stop        → graceful stop: square off everything, end session
GET  /api/execute/status      → {status: "idle"|"running"|"done", positions: [...], pnl, mode}
```

POST /api/execute returns 409 if already running. Returns 400 if no plan exists for the requested date.

### Plans

```
GET    /api/plans             → [{trade_date, legs_count, regime, generated_at}]
GET    /api/plans/:date       → full TradePlan JSON
DELETE /api/plans/:date       → delete a plan file
```

### Trades & Stats

```
GET  /api/trades              → trade history; query params: days=30, date=2026-09-25
GET  /api/trades/stats        → {win_rate, total_pnl, avg_pnl, max_drawdown, trade_count, best_day, worst_day}
                                query params: days=30
```

### Health

```
GET  /api/health              → {api: "ok", llm: "ok"|"error"|"unconfigured", database: "ok"|"error"}
```

## Module Refactoring for EventBus

Each module that needs to emit events gets an optional `event_bus` parameter. When `None` (CLI mode), no events are emitted. When set, events fire at the documented points.

### Changes to existing modules

**scanner.py** — `Scanner.__init__` accepts `event_bus=None`. `scan()` emits `scan.universe`, `scan.filtered`, `scan.context` at the appropriate points. `market_analyzer.shortlist()` emits `scan.shortlist`.

**plan_generator.py** — `PlanGenerator.__init__` accepts `event_bus=None`. `generate()` emits `analysis.started`, per-stock `strategy.indicators` and `strategy.backtest`, `strategy.setups`, `strategy.sized`, `analysis.complete`/`analysis.failed`.

**executor.py** — `Executor.__init__` accepts `event_bus=None`. `start()` emits `exec.started`. `_poll_entry` emits entry events. `_manage_open_leg` emits price ticks and target/stop events. `_close` emits the appropriate close event. `_halt_everything` emits `exec.kill_switch`.

All changes are additive — a one-line `if self.event_bus: await self.event_bus.emit(...)` at each point. No existing method signatures change (the parameter is keyword-only with a default).

### Async consideration

The existing executor's `tick()` is synchronous. The EventBus `emit()` is async. Two options:

1. Make EventBus.emit synchronous (use a thread-safe queue, flush in a background coroutine)
2. Make executor tick async

**Decision:** Option 1 — synchronous `emit()` with an internal async queue. The executor stays synchronous. The EventBus accepts sync calls, buffers them, and a background coroutine flushes to subscribers. This avoids refactoring the entire executor to async.

```python
class EventBus:
    def emit_sync(self, event_type: str, data: dict) -> None:
        """Synchronous emit for use in non-async code (executor)."""
        self._queue.put_nowait({"type": event_type, "data": data})

    async def emit(self, event_type: str, data: dict) -> None:
        """Async emit for use in async code (scanner, plan_generator)."""
        # Direct dispatch to subscribers

    async def flush_loop(self) -> None:
        """Background task that drains the sync queue and dispatches."""
```

## AppState

```python
# tradingbot/api/state.py

@dataclass
class AppState:
    config: Config
    event_bus: EventBus
    database: Database
    plan_store: PlanStore
    analysis_status: str = "idle"       # idle | running | complete | failed
    analysis_task: asyncio.Task | None = None
    analysis_error: str | None = None
    executor_status: str = "idle"       # idle | running | done
    executor_ref: Executor | None = None
    executor_task: asyncio.Task | None = None
```

Created once at server startup (FastAPI lifespan), shared across all routes via `request.app.state`.

## WebSocket Protocol

Single endpoint: `ws://localhost:8000/ws`

### Server → Client

Every message is a JSON event envelope:

```json
{"type": "scan.filtered", "timestamp": "...", "data": {...}}
```

The client subscribes by connecting — all events stream to all connections. No per-topic subscription needed (the frontend filters client-side).

### Client → Server

Control messages (optional, for future use):

```json
{"action": "ping"}
{"action": "cancel_analysis"}
{"action": "stop_execution"}
```

### Connection Management

- Server tracks connected clients in a `ConnectionManager`
- On disconnect, client is removed
- Reconnection from frontend: automatic via `useWebSocket` hook with exponential backoff
- No message history — a client that reconnects mid-analysis misses past events (it can poll `/api/analyze/status` to catch up)

## CLI Addition

```bash
tradingbot serve                    # start on 0.0.0.0:8000
tradingbot serve --port 9000        # custom port
tradingbot serve --reload           # uvicorn reload for development
```

Added as a new click command in `cli.py`. Uses `uvicorn.run()` to start the FastAPI app.

## New Dependencies

```toml
# In pyproject.toml
"fastapi>=0.115.0",
"uvicorn[standard]>=0.32.0",
```

No new frontend dependencies in this sub-project.

## File Structure

```
tradingbot/
├── api/                          # NEW
│   ├── __init__.py
│   ├── app.py                    # FastAPI app creation, CORS, lifespan
│   ├── state.py                  # AppState dataclass
│   ├── websocket.py              # ConnectionManager, WS endpoint
│   ├── config_routes.py          # /api/config endpoints
│   ├── analysis_routes.py        # /api/analyze endpoints
│   ├── execution_routes.py       # /api/execute endpoints
│   ├── plan_routes.py            # /api/plans endpoints
│   ├── trade_routes.py           # /api/trades endpoints
│   └── health_routes.py          # /api/health endpoint
├── core/
│   ├── events.py                 # NEW — EventBus
│   └── (existing files unchanged except event_bus parameter additions)
├── scanner/
│   └── (scanner.py, market_analyzer.py — add event_bus emit calls)
├── strategy/
│   └── (plan_generator.py — add event_bus emit calls)
├── executor/
│   └── (executor.py — add event_bus emit_sync calls)
└── cli.py                        # Add `serve` command

tests/
├── api/                          # NEW
│   ├── __init__.py
│   ├── test_config_routes.py
│   ├── test_analysis_routes.py
│   ├── test_execution_routes.py
│   ├── test_plan_routes.py
│   ├── test_trade_routes.py
│   ├── test_health_routes.py
│   └── test_websocket.py
└── core/
    └── test_events.py            # NEW
```

## Testing Strategy

- FastAPI routes tested with `httpx.AsyncClient` (FastAPI's test client)
- WebSocket tested with `httpx` WebSocket support or `websockets` test client
- EventBus tested in isolation: emit → subscribe → verify callback fired
- Background tasks (analysis, execution) tested with mocked modules — no real LLM/broker calls
- Existing 269 tests must continue passing (event_bus=None path)

## Configuration for CORS

The frontend will run on `localhost:3000` during development. CORS allows:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Open Questions

None — all design decisions resolved during brainstorming.
