"""Analysis routes — start, status, cancel."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from tradingbot.api.state import AppState
from tradingbot.core.models import now_ist
from tradingbot.scanner.calendar import NotATradingDayError, is_trading_day, next_trading_day

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


async def _run_analysis(state: AppState, trade_date: date) -> None:
    try:
        from tradingbot.core.llm.anthropic_provider import build_provider
        from tradingbot.core.risk_manager import RiskManager
        from tradingbot.scanner.data_fetcher import DataFetcher
        from tradingbot.scanner.market_analyzer import MarketAnalyzer
        from tradingbot.scanner.market_context import MarketContextFetcher
        from tradingbot.scanner.scanner import Scanner
        from tradingbot.strategy.plan_generator import PlanGenerator
        from tradingbot.strategy.strategy_selector import StrategySelector

        config = state.config
        log_dir = Path(state.data_dir) / "logs"

        provider = build_provider(config.llm, config.secrets, log_dir=log_dir / "llm")
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
        )

        generator = PlanGenerator(
            scanner=scanner,
            fetcher=fetcher,
            selector=StrategySelector(provider, config.strategy),
            risk_manager=risk_manager,
            plan_store=state.plan_store,
            strategy_config=config.strategy,
            capital=config.general.capital,
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
    body = {}
    raw = await request.body()
    if raw:
        body = await request.json()

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
