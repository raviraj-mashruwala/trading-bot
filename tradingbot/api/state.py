"""Shared application state for the FastAPI server."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from tradingbot.core.config import Config
from tradingbot.core.database import Database
from tradingbot.core.events import EventBus
from tradingbot.core.plan_store import PlanStore


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
    executor_ref: object | None = None
    executor_task: asyncio.Task | None = None
    executor_mode: str | None = None

    # Persistence stores (initialised lazily by plan endpoints)
    run_store: object | None = None
    setup_store: object | None = None
