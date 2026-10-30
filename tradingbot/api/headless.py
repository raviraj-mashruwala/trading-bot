"""Build the shared AppState without FastAPI, for scripts and the CLI."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from pathlib import Path

from tradingbot.api.state import AppState
from tradingbot.core.config import Config
from tradingbot.core.database import Database
from tradingbot.core.events import EventBus
from tradingbot.core.models import now_ist
from tradingbot.core.plan_store import PlanStore
from tradingbot.scanner.calendar import MARKET_POST_CLOSE, is_trading_day, next_trading_day


def queue_dir_for(config: Config, data_dir: Path, subdir: str | None = None) -> Path:
    """The LLM queue directory: relative paths live under data_dir, plus an optional subdir."""
    queue = Path(config.llm.queue_dir)
    if not queue.is_absolute():
        queue = Path(data_dir) / queue
    return queue / subdir if subdir else queue


def build_headless_state(
    config: Config, data_dir: Path, llm_queue_subdir: str | None = None,
) -> AppState:
    """Mirror the setup in api/app.py's lifespan, minus FastAPI and Telegram."""
    data_dir = Path(data_dir)
    config = dataclasses.replace(
        config,
        llm=dataclasses.replace(
            config.llm, queue_dir=str(queue_dir_for(config, data_dir, llm_queue_subdir)),
        ),
    )

    database = Database(data_dir / "tradingbot.db")
    database.initialise()

    from tradingbot.data.candle_store import CandleStore

    return AppState(
        config=config,
        event_bus=EventBus(),
        database=database,
        plan_store=PlanStore(data_dir / "trade_plans"),
        data_dir=str(data_dir),
        candle_store=CandleStore(data_dir / "candles.duckdb"),
    )


def default_trade_date(now: datetime | None = None) -> date:
    """Today until post-close on a trading day, otherwise the next trading day."""
    now = now or now_ist()
    today = now.date()
    if is_trading_day(today) and now.time() <= MARKET_POST_CLOSE:
        return today
    return next_trading_day(today)
