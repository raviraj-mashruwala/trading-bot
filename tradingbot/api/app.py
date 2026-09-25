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
    return request.app.state.app_state
