"""FastAPI application factory. One app per server process."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket
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

        from tradingbot.data.candle_store import CandleStore
        candle_store = CandleStore(resolved_data_dir / "candles.duckdb")

        event_bus.subscribe(lambda event: asyncio.ensure_future(manager.broadcast(event)))
        flush_task = asyncio.create_task(event_bus.flush_loop())

        app.state.app_state = AppState(
            config=config,
            event_bus=event_bus,
            database=database,
            plan_store=plan_store,
            config_path=str(config_path or "config.toml"),
            data_dir=str(resolved_data_dir),
            ws_manager=manager,
            candle_store=candle_store,
        )

        yield

        candle_store.close()
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
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        await websocket_endpoint(websocket, manager)

    from tradingbot.api.health_routes import router as health_router
    from tradingbot.api.config_routes import router as config_router
    from tradingbot.api.plan_routes import router as plan_router
    from tradingbot.api.trade_routes import router as trade_router
    from tradingbot.api.analysis_routes import router as analysis_router
    from tradingbot.api.execution_routes import router as execution_router
    from tradingbot.api.review_routes import router as review_router
    from tradingbot.api.calendar_routes import router as calendar_router
    from tradingbot.api.sync_routes import router as sync_router

    app.include_router(health_router)
    app.include_router(config_router)
    app.include_router(plan_router)
    app.include_router(trade_router)
    app.include_router(analysis_router)
    app.include_router(execution_router)
    app.include_router(review_router)
    app.include_router(calendar_router)
    app.include_router(sync_router)

    return app


def get_state(request: Request) -> AppState:
    return request.app.state.app_state
