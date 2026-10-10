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

        from tradingbot.core.telegram_notifier import build_notifier
        telegram = build_notifier()
        if telegram.enabled:
            import logging as _log_mod
            _log_mod.getLogger(__name__).info("Telegram notifications enabled")

            async def _telegram_handler(event: dict):
                etype = event.get("type", "")
                data = event.get("data", {})
                try:
                    if etype == "exec.started":
                        telegram.notify_session_started(data.get("mode", "?"), data.get("legs", []))
                    elif etype == "exec.entry_filled":
                        telegram.notify_entry_filled(
                            data.get("symbol", "?"), data.get("direction", "?"),
                            data.get("quantity", 0), data.get("fill_price", 0),
                        )
                    elif etype == "exec.session_done":
                        telegram.notify_session_done(
                            data.get("total_pnl", 0), data.get("trades_count", 0),
                            data.get("mode", "?"),
                        )
                    elif etype == "review.complete":
                        telegram.notify_nightly_review(
                            data.get("grade", "?"), data.get("total_pnl", 0),
                            data.get("summary", ""),
                        )
                    elif etype == "sync.complete":
                        telegram.notify_sync_complete(
                            data.get("stocks_synced", 0), data.get("rows_written", 0),
                        )
                    elif etype == "analysis.plan_generated":
                        telegram.notify_plan_generated(
                            data.get("trade_date", "?"), data.get("legs", []),
                        )
                except Exception:
                    pass

            event_bus.subscribe(lambda event: asyncio.ensure_future(_telegram_handler(event)))

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
        app.state.app_state._telegram = telegram

        # Scheduled jobs: sync at 4 PM, review at 8:30 PM (trading days only)
        from tradingbot.api.sync_routes import _run_sync
        from zoneinfo import ZoneInfo
        from datetime import datetime as _dt

        IST = ZoneInfo("Asia/Kolkata")

        async def _nightly_review(state_ref, review_date=None):
            try:
                import logging
                _log = logging.getLogger(__name__)
                _log.info("Nightly review starting for %s", review_date or "today")
                await state_ref.event_bus.emit("review.started", {"trade_date": review_date or ""})
                from tradingbot.core.llm.anthropic_provider import build_provider
                from tradingbot.analysis.nightly_reviewer import run_nightly_review
                llm = build_provider(state_ref.config.llm, state_ref.config.secrets)
                db = Database(Path(state_ref.data_dir) / "tradingbot.db")
                db.initialise()
                try:
                    jev_for_review = None
                    if state_ref.config.jev and state_ref.config.jev.enabled:
                        from tradingbot.core.jev_client import JevClient
                        try:
                            jev_for_review = JevClient(state_ref.config.jev)
                            if not jev_for_review.available:
                                jev_for_review = None
                        except Exception:
                            pass
                    result = await run_nightly_review(
                        db, llm,
                        trade_date=review_date,
                        setup_store=getattr(state_ref, "setup_store", None),
                        candle_store=getattr(state_ref, "candle_store", None),
                        jev_client=jev_for_review,
                    )
                finally:
                    db.close()
                await state_ref.event_bus.emit("review.complete", {
                    "trade_date": result.get("trade_date", ""),
                    "grade": result.get("grade", ""),
                    "skipped": result.get("skipped", False),
                })
            except Exception:
                import logging
                logging.getLogger(__name__).warning("Nightly review failed", exc_info=True)
                await state_ref.event_bus.emit("review.failed", {"error": "Review failed"})

        async def _auto_start_execution(state_ref):
            try:
                import logging
                _log = logging.getLogger(__name__)
                if state_ref.executor_status == "running":
                    _log.info("Execution already running — skipping auto-start")
                    return
                from tradingbot.scanner.calendar import next_trading_day
                from tradingbot.core.models import now_ist, Mode
                now = now_ist()
                today = now.date()
                target = today if now.hour < 16 else next_trading_day(today)
                try:
                    plan = state_ref.plan_store.load(str(target))
                except Exception:
                    _log.info("No plan for %s — skipping auto-start", target)
                    return
                if not plan.legs:
                    _log.info("Plan for %s has no legs — skipping auto-start", target)
                    return
                # Preflight checks
                preflight_errors = []
                if not state_ref.kite_auth or not state_ref.kite_auth.is_authenticated():
                    preflight_errors.append("Kite not authenticated")
                try:
                    margin = state_ref.capital
                    if margin < 10000:
                        preflight_errors.append(f"Insufficient margin: ₹{margin:,.0f}")
                except Exception as pf_exc:
                    preflight_errors.append(f"Margin check failed: {type(pf_exc).__name__}")
                if preflight_errors:
                    _log.error("Preflight failed: %s", preflight_errors)
                    tg = getattr(state_ref, "_telegram", None)
                    if tg:
                        tg.notify_auto_start_failed("Preflight: " + "; ".join(preflight_errors))
                    return

                mode_str = getattr(state_ref.config.general, "mode", "paper")
                mode = Mode.LIVE if mode_str == "live" else Mode.PAPER
                _log.info("Auto-starting %s execution for %s (%d legs)", mode.value, target, len(plan.legs))
                await state_ref.event_bus.emit("exec.auto_start", {
                    "trade_date": str(target), "mode": mode.value, "legs": len(plan.legs),
                })
                from tradingbot.api.execution_routes import _run_execution
                state_ref.executor_status = "running"
                state_ref.executor_mode = mode.value
                state_ref.execution_task = asyncio.create_task(_run_execution(state_ref, mode, plan))
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("Auto-start execution failed: %s", exc)
                tg = getattr(state_ref, "_telegram", None)
                if tg:
                    tg.notify_auto_start_failed(f"{type(exc).__name__}: check application logs")

        async def _auto_run_analysis(state_ref):
            try:
                import logging
                _log = logging.getLogger(__name__)
                from tradingbot.scanner.calendar import next_trading_day
                from tradingbot.core.models import now_ist
                now = now_ist()
                target = next_trading_day(now.date())

                # Check if plan already exists for target date
                try:
                    existing_plan = state_ref.plan_store.load(str(target))
                    if existing_plan and existing_plan.legs:
                        _log.info("Plan for %s already exists (%d legs) — skipping analysis", target, len(existing_plan.legs))
                        return
                except Exception:
                    pass

                _log.info("Auto-running analysis for %s", target)
                await state_ref.event_bus.emit("analysis.auto_start", {"trade_date": str(target)})
                from tradingbot.api.analysis_routes import _run_analysis
                await _run_analysis(state_ref, target)
            except Exception:
                import logging
                logging.getLogger(__name__).warning("Auto-analysis failed", exc_info=True)

        async def _daily_scheduler():
            from tradingbot.scheduler import (
                should_start_execution, should_sync, should_run_analysis,
                should_review, previous_day,
            )
            from tradingbot.scanner.calendar import is_trading_day
            last_exec_date = None
            last_sync_date = None
            last_analysis_date = None
            last_review_date = None
            while True:
                await asyncio.sleep(30)
                try:
                    now = _dt.now(tz=IST)
                    today = now.date()
                    trading = is_trading_day(today)
                    now_time = now.timetz().replace(tzinfo=None)

                    if should_start_execution(now_time, today, last_exec_date, trading):
                        state = app.state.app_state
                        asyncio.create_task(_auto_start_execution(state))
                        last_exec_date = today

                    if should_sync(now_time, today, last_sync_date, trading):
                        import logging
                        logging.getLogger(__name__).info("Scheduled daily sync at 4 PM IST")
                        state = app.state.app_state
                        if state.sync_task is None or state.sync_task.done():
                            async def _sync_with_events(s):
                                await s.event_bus.emit("sync.started", {})
                                await _run_sync(s)
                                status = s.sync_status or {}
                                await s.event_bus.emit("sync.complete", {
                                    "stocks_synced": status.get("stocks_synced", 0),
                                    "rows_written": status.get("rows_written", 0),
                                    "status": status.get("status", "unknown"),
                                })
                            state.sync_task = asyncio.create_task(_sync_with_events(state))
                        last_sync_date = today

                    if should_run_analysis(now_time, today, last_analysis_date, trading):
                        state = app.state.app_state
                        asyncio.create_task(_auto_run_analysis(state))
                        last_analysis_date = today

                    prev = previous_day(today)
                    prev_trading = is_trading_day(prev)
                    if should_review(now_time, today, last_review_date, prev_trading):
                        state = app.state.app_state
                        review_date = str(prev)
                        existing = Database(Path(state.data_dir) / "tradingbot.db")
                        existing.initialise()
                        already_done = existing.get_nightly_review(review_date) is not None
                        existing.close()
                        if not already_done:
                            asyncio.create_task(_nightly_review(state, review_date))
                        else:
                            import logging
                            logging.getLogger(__name__).info("Nightly review already exists for %s", review_date)
                        last_review_date = today
                except Exception:
                    pass

        scheduler_task = asyncio.create_task(_daily_scheduler())

        yield

        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
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
