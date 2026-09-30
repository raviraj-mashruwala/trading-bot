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
# Analysis pipeline
# ---------------------------------------------------------------------------


async def _run_analysis(state: AppState, trade_date: date) -> None:
    """Run the 3-tier analysis pipeline."""
    try:
        from tradingbot.analysis.pipeline import AnalysisPipeline
        from tradingbot.analysis.tier2_analyzer import Tier2Analyzer
        from tradingbot.analysis.tier3_analyzer import Tier3Analyzer
        from tradingbot.backtest.monte_carlo import MonteCarloSimulator
        from tradingbot.backtest.quality_gates import QualityGates
        from tradingbot.backtest.walk_forward import WalkForwardEngine
        from tradingbot.core.llm.anthropic_provider import build_provider
        from tradingbot.data.candle_store import CandleStore
        from tradingbot.data.instrument_cache import InstrumentCache
        from tradingbot.scanner.market_context import MarketContextFetcher
        from tradingbot.screening.screener import Tier1Screener

        config = state.config
        data_dir = Path(state.data_dir) if state.data_dir else Path("data")
        data_dir.mkdir(exist_ok=True)
        log_dir = data_dir / "logs"

        _ensure_stores(state)

        provider = build_provider(config.llm, config.secrets, log_dir=log_dir / "llm")

        instrument_cache = InstrumentCache(data_dir / "instruments.db")
        candle_store = CandleStore(data_dir / "candles.db")

        data_sync = None
        if state.kite_auth and state.kite_auth.is_authenticated():
            from tradingbot.data.data_sync import DataSync
            from tradingbot.data.kite_client import KiteClient

            kite_client = KiteClient(
                state.kite_auth.kite,
                rate_limit_per_sec=config.kite.rate_limit_per_sec,
            )
            data_sync = DataSync(kite_client, instrument_cache, candle_store)

            if not instrument_cache.get_all():
                logger.info("InstrumentCache empty, running initial sync...")
                data_sync.full_sync(daily_lookback=365, intraday_lookback=60)

        pipeline = AnalysisPipeline(
            data_sync=data_sync,
            candle_store=candle_store,
            screener=Tier1Screener(config.screening, candle_store),
            tier2=Tier2Analyzer(provider),
            tier3=Tier3Analyzer(provider),
            backtest_engine=WalkForwardEngine(),
            monte_carlo=MonteCarloSimulator(capital=config.general.capital),
            quality_gates=QualityGates(),
            run_store=state.run_store,
            setup_store=state.setup_store,
            event_bus=state.event_bus,
            capital=config.general.capital,
            instrument_cache=instrument_cache,
            context_fetcher=MarketContextFetcher(candle_store=candle_store),
            lookback_days=config.backtest.lookback_days,
            db_path=Path(state.data_dir) / "tradingbot.db",
        )

        await state.event_bus.emit("analysis.started", {
            "trade_date": trade_date.isoformat(),
        })

        analysis_run = await pipeline.run(trade_date)

        state.analysis_status = "complete"
        state.analysis_error = None

        await state.event_bus.emit("analysis.complete", {
            "trade_date": trade_date.isoformat(),
            "run_id": analysis_run.run_id,
        })

    except asyncio.CancelledError:
        state.analysis_status = "idle"
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("analysis failed: %s", exc, exc_info=True)
        state.analysis_status = "failed"
        state.analysis_error = str(exc)
        await state.event_bus.emit("analysis.failed", {
            "error": str(exc),
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


# ---------------------------------------------------------------------------
# Plan generation
# ---------------------------------------------------------------------------


def _build_plan_builder(state: AppState):
    """Construct a PlanBuilder from current config."""
    from tradingbot.core.config import auto_risk_config
    from tradingbot.core.plan_builder import PlanBuilder
    from tradingbot.core.risk_manager import RiskManager

    _ensure_stores(state)
    config = state.config
    risk_config = auto_risk_config(config.general.capital)
    rm = RiskManager(
        risk_config=risk_config,
        strategy_config=config.strategy,
        capital=config.general.capital,
    )
    return PlanBuilder(state.setup_store, rm)


@router.post("/plans/generate")
async def generate_plan(request: Request, date: str | None = None):
    state: AppState = request.app.state.app_state
    from tradingbot.core.models import MarketRegime

    if date:
        from datetime import date as d
        trade_date = d.fromisoformat(date)
    else:
        trade_date = next_trading_day(now_ist().date())

    builder = _build_plan_builder(state)
    plan = builder.build(trade_date, regime=MarketRegime.RANGE_BOUND)
    state.plan_store.save(plan)
    state.database.save_plan_snapshot(plan)

    await state.event_bus.emit("plan.generated", {
        "trade_date": plan.trade_date,
        "legs": len(plan.legs),
    })

    return {
        "status": "generated",
        "trade_date": plan.trade_date,
        "legs": len(plan.legs),
    }


# ---------------------------------------------------------------------------
# Kite OAuth endpoints
# ---------------------------------------------------------------------------


def _ensure_kite_auth(state: AppState) -> "KiteAuth":
    if state.kite_auth is None:
        from tradingbot.execution.kite_auth import KiteAuth

        state.kite_auth = KiteAuth(
            api_key=state.config.secrets.kite_api_key,
            api_secret=state.config.secrets.kite_api_secret,
        )
        saved_token = KiteAuth.load_saved_token()
        if saved_token:
            try:
                from kiteconnect import KiteConnect
                kite = KiteConnect(api_key=state.config.secrets.kite_api_key)
                kite.set_access_token(saved_token)
                kite.profile()
                state.kite_auth._access_token = saved_token
                state.kite_auth._kite = kite
                logger.info("Loaded saved Kite token from file")
            except Exception:
                logger.info("Saved Kite token expired or invalid")
    return state.kite_auth


@router.get("/auth/kite/login")
async def kite_login(request: Request):
    state: AppState = request.app.state.app_state
    auth = _ensure_kite_auth(state)
    return {"login_url": auth.get_login_url()}


@router.get("/auth/kite/callback")
async def kite_callback(request: Request, request_token: str | None = None):
    if not request_token:
        raise HTTPException(status_code=400, detail="request_token required")
    state: AppState = request.app.state.app_state
    auth = _ensure_kite_auth(state)
    try:
        data = auth.generate_session(request_token)
        return {"authenticated": True, "user_id": data.get("user_id", "")}
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Token exchange failed: {exc}")


@router.get("/auth/kite/status")
async def kite_status(request: Request):
    state: AppState = request.app.state.app_state
    auth = state.kite_auth
    return {"authenticated": auth.is_authenticated() if auth else False}


@router.get("/auth/kite/test")
async def kite_test(request: Request):
    state: AppState = request.app.state.app_state
    auth = _ensure_kite_auth(state)
    if not auth.is_authenticated():
        return {"ok": False, "error": "Not authenticated. Connect Kite first."}
    try:
        profile = auth.kite.profile()
        margins = auth.kite.margins("equity")
        available = margins.get("available", {})
        return {
            "ok": True,
            "user_name": profile.get("user_name", ""),
            "user_id": profile.get("user_id", ""),
            "email": profile.get("email", ""),
            "broker": profile.get("broker", ""),
            "available_cash": available.get("live_balance", 0),
            "available_margin": available.get("intraday_payin", 0),
        }
    except Exception:
        logger.exception("Kite connection test failed")
        return {"ok": False, "error": "Connection test failed. Check server logs."}


# ---------------------------------------------------------------------------
# Data sync endpoints
# ---------------------------------------------------------------------------


@router.post("/sync")
async def start_sync(request: Request):
    state: AppState = request.app.state.app_state
    if state.sync_status == "running":
        raise HTTPException(status_code=409, detail="Sync already running")

    auth = _ensure_kite_auth(state)
    if not auth.is_authenticated():
        raise HTTPException(status_code=400, detail="Kite not authenticated. Connect Kite first.")

    state.sync_status = "running"
    state.sync_progress = "Starting..."

    async def _run_sync() -> None:
        try:
            from tradingbot.data.candle_store import CandleStore
            from tradingbot.data.data_sync import DataSync
            from tradingbot.data.instrument_cache import InstrumentCache
            from tradingbot.data.kite_client import KiteClient

            data_dir = Path(state.data_dir) if state.data_dir else Path("data")
            data_dir.mkdir(exist_ok=True)

            kite_client = KiteClient(
                auth.kite,
                rate_limit_per_sec=state.config.kite.rate_limit_per_sec,
            )
            cache = InstrumentCache(data_dir / "instruments.db")
            store = CandleStore(data_dir / "candles.db")
            sync = DataSync(kite_client, cache, store)

            state.sync_progress = "Syncing instruments..."
            await state.event_bus.emit("sync.started", {})

            import asyncio as _aio

            stats = await _aio.to_thread(sync.full_sync, 365, 60)

            state.sync_status = "complete"
            state.sync_progress = (
                f"{stats['instruments']} instruments, "
                f"{stats['daily_candles']} daily, "
                f"{stats['intraday_candles']} intraday candles"
            )
            await state.event_bus.emit("sync.complete", stats)
            cache.close()
            store.close()

        except Exception as exc:
            logger.error("Sync failed: %s", exc, exc_info=True)
            state.sync_status = "failed"
            state.sync_progress = str(exc)
            await state.event_bus.emit("sync.failed", {"error": str(exc)})

    state.sync_task = asyncio.create_task(_run_sync())
    return {"status": "started"}


@router.get("/sync/status")
async def sync_status(request: Request):
    state: AppState = request.app.state.app_state
    return {"status": state.sync_status, "progress": state.sync_progress}


# ---------------------------------------------------------------------------
# Emergency stop
# ---------------------------------------------------------------------------


@router.post("/emergency-stop")
async def emergency_stop(request: Request):
    """Kill switch — cancel all pending orders and square off all positions."""
    state: AppState = request.app.state.app_state
    auth = _ensure_kite_auth(state)
    if not auth or not auth.is_authenticated():
        raise HTTPException(status_code=400, detail="Kite not authenticated")

    from tradingbot.data.kite_client import KiteClient
    from tradingbot.execution.capital_manager import CapitalManager
    from tradingbot.execution.kite_executor import KiteExecutor
    from tradingbot.execution.safety import SafetyManager

    kite_client = KiteClient(
        auth.kite, rate_limit_per_sec=state.config.kite.rate_limit_per_sec,
    )

    # Gather pending orders
    try:
        orders = kite_client.kite.orders()
        pending = [
            o["order_id"]
            for o in orders
            if o.get("status") in ("OPEN", "TRIGGER PENDING")
        ]
    except Exception:
        logger.exception("Failed to fetch orders during emergency stop")
        pending = []

    # Gather open positions
    try:
        positions = kite_client.kite.positions().get("net", [])
        open_pos = [
            {
                "symbol": p["tradingsymbol"],
                "exchange": p["exchange"],
                "direction": "long" if p["quantity"] > 0 else "short",
                "quantity": abs(p["quantity"]),
            }
            for p in positions
            if p.get("quantity", 0) != 0
        ]
    except Exception:
        logger.exception("Failed to fetch positions during emergency stop")
        open_pos = []

    cap_mgr = CapitalManager(kite_client, deployed=0)
    executor = KiteExecutor(kite_client, cap_mgr)
    safety = SafetyManager(
        capital=state.config.general.capital,
        max_daily_loss_pct=state.config.risk.max_daily_loss_pct,
    )

    result = safety.emergency_stop(executor, pending, open_pos)
    await state.event_bus.emit("emergency.stop", result)
    return result


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
