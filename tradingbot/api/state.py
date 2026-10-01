"""Shared application state for the FastAPI server."""

from __future__ import annotations

import asyncio
import logging
import time as _time
from dataclasses import dataclass, field

from tradingbot.core.config import Config
from tradingbot.core.database import Database
from tradingbot.core.events import EventBus
from tradingbot.core.plan_store import PlanStore

log = logging.getLogger(__name__)

_CAPITAL_CACHE_SECONDS = 60


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

    # Kite authentication (initialised lazily)
    kite_auth: object | None = None

    # WebSocket manager (set by app.py after construction)
    ws_manager: object | None = None

    # Data sync
    sync_status: str = "idle"
    sync_task: asyncio.Task | None = None
    sync_progress: str = ""

    # Capital cache
    _cached_capital: float = 0.0
    _capital_fetched_at: float = 0.0

    @property
    def capital(self) -> float:
        """Live capital from Kite if authenticated, else config fallback."""
        if self.kite_auth and self.kite_auth.is_authenticated():
            now = _time.monotonic()
            if now - self._capital_fetched_at < _CAPITAL_CACHE_SECONDS and self._cached_capital > 0:
                return self._cached_capital
            try:
                margins = self.kite_auth.kite.margins("equity")
                available = margins.get("available", {})
                live = available.get("live_balance", 0) + available.get("intraday_payin", 0)
                if live > 0:
                    self._cached_capital = live
                    self._capital_fetched_at = now
                    return live
            except Exception:
                log.debug("Failed to fetch Kite margins, using fallback", exc_info=True)
            if self._cached_capital > 0:
                return self._cached_capital
        return self.config.general.capital
