"""Execution routes — start, stop, status."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from tradingbot.api.state import AppState
from tradingbot.core.models import Mode
from tradingbot.core.plan_store import PlanNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

TICK_SECONDS = 5


async def _run_execution(state: AppState, mode: Mode, plan) -> None:
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

            token_path = Path.home() / ".tradingbot" / "kite_token"
            broker = KiteClient(
                api_key=config.secrets.kite_api_key,
                api_secret=config.secrets.kite_api_secret,
                access_token=token_path.read_text().strip() if token_path.exists() else "",
            )

        from tradingbot.core.risk_manager import RiskManager
        from tradingbot.executor.executor import Executor

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
    body = {}
    raw = await request.body()
    if raw:
        body = await request.json()

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
    executor = state.executor_ref
    if executor is not None and hasattr(executor, "states"):
        for leg_state in executor.states:
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
