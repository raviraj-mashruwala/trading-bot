"""Analysis routes — start, status, cancel, daily plans."""

from __future__ import annotations

import asyncio
import logging
import time as _time
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


_PIPELINE_STEP_EVENTS = (
    "scan.context", "scan.universe", "scan.filtered", "scan.shortlist",
    "strategy.indicators", "strategy.deep_analysis", "strategy.backtest",
    "strategy.setups", "strategy.sized",
)


def _make_step_tracker(state: AppState):
    """Return an EventBus callback that mirrors pipeline events to AppState."""
    def _on_event(envelope: dict) -> None:
        event_type = envelope.get("type", "")
        data = envelope.get("data", {})
        if event_type == "analysis.started":
            state.pipeline_steps = {
                k: {"status": "pending", "data": None, "timestamp": None}
                for k in _PIPELINE_STEP_EVENTS
            }
            state.pipeline_started_at = _time.monotonic()
            return
        if event_type == "analysis.complete":
            state.pipeline_started_at = None
            return
        if event_type == "analysis.failed":
            state.pipeline_started_at = None
            return
        if event_type in _PIPELINE_STEP_EVENTS:
            step_status = "active" if data.get("status") == "fetching" else "complete"
            state.pipeline_steps[event_type] = {
                "status": step_status,
                "data": data,
                "timestamp": envelope.get("timestamp"),
            }
            if step_status == "complete":
                idx = _PIPELINE_STEP_EVENTS.index(event_type)
                if idx + 1 < len(_PIPELINE_STEP_EVENTS):
                    next_step = _PIPELINE_STEP_EVENTS[idx + 1]
                    if state.pipeline_steps.get(next_step, {}).get("status") == "pending":
                        state.pipeline_steps[next_step] = {
                            **state.pipeline_steps[next_step],
                            "status": "active",
                        }
    return _on_event


async def _run_analysis(state: AppState, trade_date: date) -> None:
    """Run the 3-tier analysis pipeline."""
    sub_id = state.event_bus.subscribe(_make_step_tracker(state))
    state.analysis_blocked = None
    try:
        from tradingbot.analysis.pipeline import AnalysisPipeline, DataNeeded
        from tradingbot.core.llm.file_provider import AnswersNeeded
        from tradingbot.analysis.tier2_analyzer import Tier2Analyzer
        from tradingbot.analysis.tier3_analyzer import Tier3Analyzer
        from tradingbot.backtest.monte_carlo import MonteCarloSimulator
        from tradingbot.backtest.walk_forward import WalkForwardEngine
        from tradingbot.core.llm.anthropic_provider import build_provider
        from tradingbot.data.market_data_provider import MarketDataProvider
        from tradingbot.scanner.market_context import MarketContextFetcher
        from tradingbot.screening.screener import Tier1Screener

        config = state.config
        data_dir = Path(state.data_dir) if state.data_dir else Path(".")
        data_dir.mkdir(exist_ok=True)
        log_dir = data_dir / "logs"

        _ensure_stores(state)

        llm_provider = build_provider(config.llm, config.secrets, log_dir=log_dir / "llm")

        auth = _ensure_kite_auth(state)
        if not auth.is_authenticated():
            raise RuntimeError("Kite not authenticated. Connect Kite first from Settings.")

        from tradingbot.api.state import CapitalUnavailableError
        try:
            live_capital = state.capital
        except CapitalUnavailableError:
            raise RuntimeError(
                "Cannot generate plan: Kite margin unavailable. "
                "Please check authentication and try again."
            )

        from tradingbot.data.kite_client import KiteClient
        kite_for_universe = KiteClient(
            auth.kite,
            rate_limit_per_sec=config.kite.rate_limit_per_sec,
        )
        market_provider = MarketDataProvider(kite_client=kite_for_universe)

        from tradingbot.data.instrument_cache import InstrumentCache
        inst_cache = InstrumentCache(Path(state.data_dir) / "instruments.db")
        inst_cache.refresh(kite_for_universe.kite.instruments("NSE"))

        pipeline = AnalysisPipeline(
            data_sync=None,
            candle_store=None,
            duckdb_store=getattr(state, 'candle_store', None),
            screener=Tier1Screener(config.screening, candle_store=None),
            tier2=Tier2Analyzer(llm_provider),
            tier3=Tier3Analyzer(llm_provider),
            backtest_engine=WalkForwardEngine(),
            monte_carlo=MonteCarloSimulator(capital=live_capital),
            run_store=state.run_store,
            setup_store=state.setup_store,
            event_bus=state.event_bus,
            capital=live_capital,
            instrument_cache=inst_cache,
            context_fetcher=MarketContextFetcher(market_data_provider=market_provider),
            lookback_days=config.backtest.lookback_days,
            db_path=Path(state.data_dir) / "tradingbot.db",
            market_data_provider=market_provider,
            screening_config=config.screening,
            jev_config=config.jev,
            require_prefetched=state.require_prefetched,
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

        try:
            from tradingbot.core.models import MarketRegime
            builder = _build_plan_builder(state)
            regime_str = analysis_run.market_regime.value if analysis_run.market_regime else "range_bound"
            plan = builder.build(
                trade_date,
                regime=MarketRegime(regime_str),
                market_summary=f"Auto-generated after {analysis_run.run_id}",
            )
            state.plan_store.save(plan)
            state.database.save_plan_snapshot(plan)
            await state.event_bus.emit("plan.generated", {
                "trade_date": trade_date.isoformat(),
                "legs": len(plan.legs),
            })
            logger.info("Auto-generated plan for %s: %d legs", trade_date, len(plan.legs))
        except Exception as exc:  # noqa: BLE001
            logger.error("Auto plan generation failed: %s", exc, exc_info=True)

    except asyncio.CancelledError:
        state.analysis_status = "idle"
        state.pipeline_started_at = None
        raise
    except (AnswersNeeded, DataNeeded) as blocked:
        # Not a failure: the run stopped to wait for the conversation or a download.
        logger.info("analysis blocked: %s", blocked)
        state.analysis_blocked = blocked
        state.analysis_status = "blocked"
        state.pipeline_started_at = None
    except Exception as exc:  # noqa: BLE001
        logger.error("analysis failed: %s", exc, exc_info=True)
        state.analysis_status = "failed"
        state.analysis_error = str(exc)
        state.pipeline_started_at = None
        await state.event_bus.emit("analysis.failed", {
            "error": str(exc),
        })
    finally:
        state.event_bus.unsubscribe(sub_id)


@router.post("/analyze")
async def start_analysis(request: Request):
    state: AppState = request.app.state.app_state
    body = {}
    raw = await request.body()
    if raw:
        body = await request.json()

    if state.analysis_status == "running":
        raise HTTPException(status_code=409, detail="analysis already running")

    candle_store = getattr(state, "candle_store", None)
    if candle_store is None or not candle_store.freshness():
        raise HTTPException(
            status_code=400,
            detail="Data cache is empty. Go to Settings → Data Cache → Start Initial Fill before running analysis.",
        )

    if "trade_date" in body:
        trade_date = date.fromisoformat(body["trade_date"])
        if not is_trading_day(trade_date):
            raise HTTPException(status_code=400, detail=f"{trade_date} is not a trading day")
    else:
        from tradingbot.scanner.calendar import MARKET_POST_CLOSE
        now = now_ist()
        today = now.date()
        if is_trading_day(today) and now.time() <= MARKET_POST_CLOSE:
            trade_date = today
        else:
            trade_date = next_trading_day(today)

    state.analysis_status = "running"
    state.analysis_trade_date = trade_date.isoformat()
    state.analysis_error = None

    state.analysis_task = asyncio.create_task(_run_analysis(state, trade_date))

    return {"status": "started", "trade_date": trade_date.isoformat()}


@router.get("/analyze/status")
async def analysis_status(request: Request):
    state: AppState = request.app.state.app_state
    elapsed = None
    if state.pipeline_started_at is not None:
        elapsed = round(_time.monotonic() - state.pipeline_started_at, 1)
    return {
        "status": state.analysis_status,
        "trade_date": state.analysis_trade_date,
        "error": state.analysis_error,
        "steps": state.pipeline_steps,
        "elapsed_s": elapsed,
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

    from tradingbot.api.state import CapitalUnavailableError
    try:
        capital = state.capital
    except CapitalUnavailableError:
        raise RuntimeError(
            "Cannot generate plan: Kite margin unavailable. "
            "Please check authentication and try again."
        )

    risk_config = auto_risk_config(capital)

    margin_fetcher = None
    if state.kite_auth and state.kite_auth.is_authenticated():
        kite = state.kite_auth.kite

        def _fetch_margin(setup):
            tx = "SELL" if setup.direction.value == "short" else "BUY"
            result = kite.order_margins([{
                "exchange": "NSE",
                "tradingsymbol": setup.symbol,
                "transaction_type": tx,
                "quantity": 1,
                "product": "MIS",
                "order_type": "LIMIT",
                "price": setup.entry_price,
            }])
            return result[0].get("total", setup.entry_price)

        margin_fetcher = _fetch_margin

    rm = RiskManager(
        risk_config=risk_config,
        strategy_config=config.strategy,
        capital=capital,
        margin_fetcher=margin_fetcher,
    )
    return PlanBuilder(state.setup_store, rm)


@router.post("/plans/generate")
async def generate_plan(request: Request, trade_date: str | None = None):
    state: AppState = request.app.state.app_state
    from tradingbot.core.models import MarketRegime

    if trade_date:
        td = date.fromisoformat(trade_date)
    else:
        now = now_ist()
        today = now.date()
        if is_trading_day(today) and now.hour < 16:
            td = today
        else:
            td = next_trading_day(today)

    builder = _build_plan_builder(state)
    plan = builder.build(td, regime=MarketRegime.RANGE_BOUND)
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
    from fastapi.responses import RedirectResponse
    if not request_token:
        raise HTTPException(status_code=400, detail="request_token required")
    state: AppState = request.app.state.app_state
    auth = _ensure_kite_auth(state)
    try:
        data = auth.generate_session(request_token)
        await state.event_bus.emit("kite.authenticated", {
            "user_id": data.get("user_id", ""),
        })
        return RedirectResponse(url="http://localhost:3000/settings?kite=success")
    except Exception as exc:
        logger.error("Kite token exchange failed: %s", exc)
        return RedirectResponse(url="http://localhost:3000/settings?kite=error")


@router.get("/auth/kite/status")
async def kite_status(request: Request):
    state: AppState = request.app.state.app_state
    auth = _ensure_kite_auth(state)

    def _try_token(kite_obj):
        try:
            kite_obj.profile()
            return True
        except Exception:
            return False

    if auth.is_authenticated() and _try_token(auth.kite):
        return {"authenticated": True}

    from tradingbot.execution.kite_auth import KiteAuth
    saved_token = KiteAuth.load_saved_token()
    if saved_token:
        try:
            from kiteconnect import KiteConnect
            kite = KiteConnect(api_key=state.config.secrets.kite_api_key)
            kite.set_access_token(saved_token)
            if _try_token(kite):
                auth._access_token = saved_token
                auth._kite = kite
                logger.info("Refreshed Kite token from file")
                return {"authenticated": True}
        except Exception:
            pass
    return {"authenticated": False}


@router.get("/auth/kite/test")
async def kite_test(request: Request):
    state: AppState = request.app.state.app_state
    auth = _ensure_kite_auth(state)
    if not auth.is_authenticated():
        return {"ok": False, "error": "Not authenticated. Connect Kite first."}
    try:
        profile = auth.kite.profile()
        result = {
            "ok": True,
            "user_name": profile.get("user_name", ""),
            "user_id": profile.get("user_id", ""),
            "email": profile.get("email", ""),
            "broker": profile.get("broker", ""),
        }
        try:
            margins = auth.kite.margins("equity")
            available = margins.get("available", {})
            result["available_cash"] = available.get("live_balance", 0)
            result["available_margin"] = available.get("intraday_payin", 0)
        except Exception:
            result["available_cash"] = None
            result["margin_note"] = "Kite OMS/RMS unavailable (maintenance)"
        return result
    except Exception:
        logger.exception("Kite connection test failed")
        return {"ok": False, "error": "Token invalid or expired. Re-connect Kite."}


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
    emergency_capital = state.capital_or_none or state.config.general.capital
    safety = SafetyManager(
        capital=emergency_capital,
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
    try:
        state.setup_store.get_by_id(setup_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Setup {setup_id} not found")
    state.setup_store.update_status(setup_id, status, reason)
    return {"ok": True, "setup_id": setup_id, "status": status}
