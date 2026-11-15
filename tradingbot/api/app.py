"""FastAPI application factory. One app per server process."""

from __future__ import annotations

import asyncio
import os
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
                        sync_status = data.get("status", "unknown")
                        if sync_status == "error":
                            telegram.notify_sync_failed(data.get("error", "unknown error"))
                        else:
                            telegram.notify_sync_complete(
                                data.get("stocks_synced", 0), data.get("rows_written", 0),
                            )
                    elif etype == "analysis.plan_generated":
                        telegram.notify_plan_generated(
                            data.get("trade_date", "?"), data.get("legs", []),
                        )
                    elif etype == "analysis.started":
                        telegram.notify_analysis_progress(
                            "Started", f"Run: {data.get('run_id', '?')[:12]}",
                        )
                    elif etype == "scan.context":
                        telegram.notify_analysis_progress(
                            "Market Context", f"Regime: {data.get('regime', '?')}",
                        )
                    elif etype == "scan.universe":
                        if data.get("status") != "fetching":
                            telegram.notify_analysis_progress(
                                "Universe Screened", f"Stocks: {data.get('total', 0)}",
                            )
                    elif etype == "scan.filtered":
                        telegram.notify_analysis_progress(
                            "Tier 1 Complete", f"Candidates: {data.get('candidates', 0)}",
                        )
                    elif etype == "scan.shortlist":
                        telegram.notify_analysis_progress(
                            "Tier 2 Complete", f"Shortlisted: {data.get('shortlisted', 0)}",
                        )
                    elif etype == "strategy.deep_analysis":
                        if data.get("status") == "done":
                            telegram.notify_analysis_progress(
                                "Deep Analysis Done",
                                data.get("message", f"Setups: {data.get('setups_found', 0)}"),
                            )
                    elif etype == "strategy.setups":
                        telegram.notify_analysis_progress(
                            "Strategy Complete",
                            f"Setups: {data.get('total_setups', 0)} from {data.get('symbols_analyzed', 0)} stocks",
                        )
                    elif etype == "strategy.backtest":
                        if data.get("status") in ("done", "skipped"):
                            telegram.notify_analysis_progress(
                                "Backtest", data.get("message", data.get("reason", "done")),
                            )
                    elif etype == "strategy.sized":
                        telegram.notify_analysis_progress(
                            "Portfolio Validated",
                            f"Proposed: {data.get('proposed', 0)}  Approved: {data.get('approved', 0)}",
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


        # Start Telegram command handler (polls for incoming commands).
        # Use a module-level Lock to prevent duplicate polling loops when
        # uvicorn factory=True creates multiple app objects concurrently.
        import tradingbot.core.telegram_commands as _tg_cmd_mod
        if not hasattr(_tg_cmd_mod, "_singleton_lock"):
            _tg_cmd_mod._singleton_lock = asyncio.Lock()
        telegram_cmd_task = None
        cmd_handler = None
        if telegram.enabled:
            async with _tg_cmd_mod._singleton_lock:
                if not getattr(_tg_cmd_mod, "_singleton_started", False):
                    _tg_cmd_mod._singleton_started = True
                    from tradingbot.core.telegram_commands import TelegramCommandHandler
                    cmd_handler = TelegramCommandHandler(
                        bot_token=telegram._token,
                        chat_id=telegram._chat_id,
                        app_state=app.state.app_state,
                    )
                    telegram_cmd_task = asyncio.create_task(cmd_handler.start())

        # Only execution is scheduled. Sync, analysis and review are manual.
        from zoneinfo import ZoneInfo
        from datetime import datetime as _dt

        IST = ZoneInfo("Asia/Kolkata")

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
                reviewed = state_ref.database.is_plan_reviewed(str(target)) if state_ref.database else False
                review_tag = "" if reviewed else " [UNREVIEWED]"
                _log.info("Auto-starting %s execution for %s (%d legs)%s", mode.value, target, len(plan.legs), review_tag)
                tg = getattr(state_ref, "_telegram", None)
                if tg and not reviewed:
                    leg_lines = ", ".join(l.symbol for l in plan.legs[:6])
                    tg.send_sync(
                        f"⚠️ <b>Auto-executing unreviewed plan</b>\n"
                        f"Date: {target} | Mode: {mode.value}\n"
                        f"Legs: {leg_lines}\n"
                        f"Approve at /plans/{target}/approve to dismiss this warning."
                    )
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

        async def _daily_scheduler():
            from tradingbot.scheduler import should_start_execution
            from tradingbot.scanner.calendar import is_trading_day
            last_exec_date = None
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
                except Exception:
                    pass

        scheduler_task = asyncio.create_task(_daily_scheduler())

        yield

        if telegram_cmd_task is not None:
            if cmd_handler is not None:
                cmd_handler.stop()
            telegram_cmd_task.cancel()
            try:
                await telegram_cmd_task
            except asyncio.CancelledError:
                pass
            _tg_cmd_mod._singleton_started = False
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
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            *[o for o in [os.environ.get("CORS_ALLOWED_ORIGIN")] if o],
        ],
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
