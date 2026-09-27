"""Analysis routes — start, status, cancel, daily plans."""

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


# ---------------------------------------------------------------------------
# V1: Legacy PlanGenerator path (backward compat)
# ---------------------------------------------------------------------------


async def _run_analysis_v1(state: AppState, trade_date: date) -> None:
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


# ---------------------------------------------------------------------------
# V2: New AnalysisPipeline path (opt-in via pipeline=v2)
# ---------------------------------------------------------------------------


async def _run_analysis_v2(state: AppState, trade_date: date) -> None:
    """Run the redesigned 3-tier analysis pipeline."""
    try:
        from tradingbot.analysis.pipeline import AnalysisPipeline
        from tradingbot.analysis.tier2_analyzer import Tier2Analyzer
        from tradingbot.analysis.tier3_analyzer import Tier3Analyzer
        from tradingbot.backtest.monte_carlo import MonteCarloSimulator
        from tradingbot.backtest.quality_gates import QualityGates
        from tradingbot.backtest.walk_forward import WalkForwardEngine
        from tradingbot.core.llm.anthropic_provider import build_provider
        from tradingbot.data.candle_store import CandleStore
        from tradingbot.screening.screener import Tier1Screener

        config = state.config
        log_dir = Path(state.data_dir) / "logs"

        _ensure_stores(state)

        provider = build_provider(config.llm, config.secrets, log_dir=log_dir / "llm")

        candle_db = Path(state.data_dir) / "candles.db"
        candle_store = CandleStore(candle_db)

        # data_sync=None is safe: _build_stock_metrics() returns [] (stub),
        # and the deep_fetch call is guarded by hasattr(). Real DataSync
        # needs KiteClient + InstrumentCache which require auth setup.
        pipeline = AnalysisPipeline(
            data_sync=None,
            candle_store=candle_store,
            screener=Tier1Screener(config.scanner, candle_store),
            tier2=Tier2Analyzer(provider),
            tier3=Tier3Analyzer(provider),
            backtest_engine=WalkForwardEngine(),
            monte_carlo=MonteCarloSimulator(capital=config.general.capital),
            quality_gates=QualityGates(),
            run_store=state.run_store,
            setup_store=state.setup_store,
            event_bus=state.event_bus,
            capital=config.general.capital,
        )

        await state.event_bus.emit("analysis.started", {
            "trade_date": trade_date.isoformat(),
            "pipeline": "v2",
        })

        analysis_run = await pipeline.run(trade_date)

        state.analysis_status = "complete"
        state.analysis_error = None

        await state.event_bus.emit("analysis.complete", {
            "trade_date": trade_date.isoformat(),
            "run_id": analysis_run.run_id,
            "pipeline": "v2",
        })

    except asyncio.CancelledError:
        state.analysis_status = "idle"
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("analysis v2 failed: %s", exc, exc_info=True)
        state.analysis_status = "failed"
        state.analysis_error = str(exc)
        await state.event_bus.emit("analysis.failed", {
            "error": str(exc),
            "pipeline": "v2",
        })


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

    pipeline_version = body.get("pipeline", "v1")
    if pipeline_version == "v2":
        state.analysis_task = asyncio.create_task(_run_analysis_v2(state, trade_date))
    else:
        state.analysis_task = asyncio.create_task(_run_analysis_v1(state, trade_date))

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


# ---------------------------------------------------------------------------
# Daily plan & setup endpoints
# ---------------------------------------------------------------------------


def _ensure_stores(state: AppState) -> None:
    """Lazily create persistence stores on first access."""
    if state.run_store is None:
        from tradingbot.persistence.run_store import RunStore
        from tradingbot.persistence.setup_store import SetupStore

        db_path = Path(state.data_dir) / "analysis.db"
        state.run_store = RunStore(db_path)
        state.setup_store = SetupStore(db_path)


@router.get("/plans/today")
async def get_daily_plan(request: Request):
    state: AppState = request.app.state.app_state
    _ensure_stores(state)
    from tradingbot.persistence.daily_plan import DailyPlanBuilder

    builder = DailyPlanBuilder(state.run_store, state.setup_store)
    today = date.today()
    return builder.build(today)


@router.get("/plans/runs")
async def list_runs(request: Request, trade_date: str | None = None):
    state: AppState = request.app.state.app_state
    _ensure_stores(state)
    d = date.fromisoformat(trade_date) if trade_date else date.today()
    return state.run_store.list_for_date(d)


@router.get("/plans/setups")
async def get_setups(
    request: Request,
    symbol: str | None = None,
    trade_date: str | None = None,
):
    state: AppState = request.app.state.app_state
    _ensure_stores(state)
    d = date.fromisoformat(trade_date) if trade_date else date.today()
    if symbol:
        return state.setup_store.get_for_symbol(symbol, d)
    return state.setup_store.get_active(d)


@router.patch("/setups/{setup_id}")
async def update_setup(setup_id: int, request: Request):
    state: AppState = request.app.state.app_state
    _ensure_stores(state)
    body = await request.json()
    status = body.get("status")
    reason = body.get("reason", "")
    if status not in ("approved", "rejected", "active"):
        raise HTTPException(status_code=400, detail="Invalid status")
    state.setup_store.update_status(setup_id, status, reason)
    return {"ok": True, "setup_id": setup_id, "status": status}
