"""Execution routes — start, stop, status."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from tradingbot.api.state import AppState
from tradingbot.api.websocket import ConnectionManager
from tradingbot.core.models import Direction, Mode
from tradingbot.core.plan_store import PlanNotFoundError
from tradingbot.data.kite_ticker import LiveTickManager
from tradingbot.executor.decision_logger import DecisionLogger
from tradingbot.executor.execution_intelligence import ExecutionIntelligence

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

TICK_SECONDS = 5


async def _run_execution(state: AppState, mode: Mode, plan) -> None:
    try:
        config = state.config

        if mode is Mode.PAPER:
            from tradingbot.paper.virtual_broker import VirtualBroker

            from tradingbot.data.kite_client import KiteClient as DataKiteClient
            from kiteconnect import KiteConnect

            token_path = Path.home() / ".tradingbot" / "kite_token"
            kite = KiteConnect(api_key=config.secrets.kite_api_key)
            if token_path.exists():
                kite.set_access_token(token_path.read_text().strip())
            kite_client = DataKiteClient(kite, rate_limit_per_sec=config.kite.rate_limit_per_sec)

            def price_feed(symbol: str) -> float:
                ltp = kite_client.get_ltp([f"NSE:{symbol}"])
                return float(ltp[f"NSE:{symbol}"]["last_price"])

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
            config.risk, config.strategy, capital=state.capital,
            plan_max_age_hours=config.execution.plan_max_age_hours,
            max_entry_price_drift_pct=config.execution.max_entry_price_drift_pct,
        )

        # Build execution intelligence (live tick feed + momentum scoring)
        from tradingbot.data.kite_client import KiteClient as DataKiteClient
        from tradingbot.data.instrument_cache import InstrumentCache
        from kiteconnect import KiteConnect

        token_path = Path.home() / ".tradingbot" / "kite_token"
        access_token = token_path.read_text().strip() if token_path.exists() else ""
        ticker = LiveTickManager(
            api_key=config.secrets.kite_api_key,
            access_token=access_token,
        )

        instrument_cache = InstrumentCache(Path(state.data_dir) / "instruments.db")
        kite = KiteConnect(api_key=config.secrets.kite_api_key)
        if access_token:
            kite.set_access_token(access_token)
        data_kite_client = DataKiteClient(kite, rate_limit_per_sec=config.kite.rate_limit_per_sec)

        intelligence = ExecutionIntelligence(
            ticker, config.execution,
            instrument_cache=instrument_cache,
            kite_client=data_kite_client,
            jev_config=config.jev,
        )

        executor = Executor(
            broker=broker,
            plan=plan,
            risk_manager=risk_manager,
            database=state.database,
            execution_config=config.execution,
            mode=mode,
            intelligence=intelligence,
        )

        state.executor_ref = executor
        await state.event_bus.emit("exec.started", {
            "trade_date": plan.trade_date,
            "mode": mode.value,
            "legs": [leg.to_dict() for leg in plan.legs],
        })

        executor.start()

        ws_mgr: ConnectionManager | None = getattr(state, "ws_manager", None)
        last_decision_count = 0

        while not executor.is_done:
            executor.tick()

            # Broadcast ticker health on every tick
            if ws_mgr is not None and intelligence is not None:
                try:
                    health = intelligence.health
                    await ws_mgr.broadcast_ticker_health({
                        "status": health.status,
                        "last_tick_at": (
                            health.last_tick_at.isoformat()
                            if health.last_tick_at
                            else None
                        ),
                        "reconnect_count": health.reconnect_count,
                        "gap_seconds_today": health.gap_seconds_today,
                    })
                except Exception:
                    pass

            # Broadcast new decisions since last tick
            if ws_mgr is not None and state.database is not None:
                try:
                    dl = DecisionLogger(state.database)
                    recent = dl.recent(limit=5)
                    new_count = len(recent)
                    if new_count > last_decision_count:
                        for d in recent[: new_count - last_decision_count]:
                            await ws_mgr.broadcast_decision(d)
                    last_decision_count = new_count
                except Exception:
                    pass

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
                try:
                    last_price = executor.broker.get_ltp(leg_state.leg.symbol)
                    delta = last_price - leg_state.entry_fill_price
                    if leg_state.leg.direction is Direction.SHORT:
                        delta = -delta
                    unrealised = delta * leg_state.filled_quantity
                except Exception:
                    last_price = 0.0
                    unrealised = 0.0
                positions.append({
                    "symbol": leg_state.leg.symbol,
                    "direction": leg_state.leg.direction.value,
                    "quantity": leg_state.filled_quantity,
                    "entry_price": leg_state.entry_fill_price,
                    "current_stop": leg_state.current_stop,
                    "target_1_booked": leg_state.target_1_booked,
                    "pnl": leg_state.realised_pnl,
                    "last_price": last_price,
                    "unrealised_pnl": unrealised,
                })

    # Execution intelligence overlay
    intel = executor._intelligence if executor is not None else None

    ticker_health = {
        "status": intel.health.status if intel else "unknown",
        "last_tick_at": (
            intel.health.last_tick_at.isoformat()
            if intel and intel.health.last_tick_at
            else None
        ),
        "reconnect_count": intel.health.reconnect_count if intel else 0,
        "gap_seconds_today": intel.health.gap_seconds_today if intel else 0,
    }

    # Per-leg momentum scores
    for pos in positions:
        symbol = pos["symbol"]
        ss = intel.scorer.get_state(symbol) if intel else None
        if ss:
            pos["momentum"] = {
                "1m": ss.momentum_1m,
                "5m": ss.momentum_5m,
                "volume_ratio": ss.volume_ratio,
                "vwap_position": ss.vwap_position,
                "trend_alignment": ss.trend_alignment,
            }

    # Recent decision log
    decision_log: list[dict] = []
    if state.database is not None:
        try:
            dl = DecisionLogger(state.database)
            decision_log = dl.recent(limit=20)
        except Exception:
            pass

    return {
        "status": state.executor_status,
        "mode": state.executor_mode,
        "positions": positions,
        "ticker_health": ticker_health,
        "decision_log": decision_log,
    }
