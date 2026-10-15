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
from tradingbot.data.ws_ticker import AsyncKiteTicker as LiveTickManager
from tradingbot.executor.decision_logger import DecisionLogger
from tradingbot.executor.execution_intelligence import ExecutionIntelligence

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

TICK_SECONDS_NORMAL = 5
TICK_SECONDS_FAST = 1
FAST_TICK_START = (9, 10)
FAST_TICK_END = (9, 25)


def _tick_interval() -> int:
    from tradingbot.core.models import now_ist
    now = now_ist()
    h, m = now.hour, now.minute
    if (h, m) >= FAST_TICK_START and (h, m) < FAST_TICK_END:
        return TICK_SECONDS_FAST
    return TICK_SECONDS_NORMAL


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

        margin_fetcher = None
        # Ensure kite_auth is initialized from saved token if not already
        if state.kite_auth is None:
            from tradingbot.api.analysis_routes import _ensure_kite_auth
            try:
                _ensure_kite_auth(state)
            except Exception:
                pass
        if state.kite_auth and state.kite_auth.is_authenticated():
            kite_for_margin = state.kite_auth.kite

            def _fetch_margin(setup):
                tx = "SELL" if setup.direction.value == "short" else "BUY"
                result = kite_for_margin.order_margins([{
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

        from tradingbot.api.state import CapitalUnavailableError
        try:
            live_capital = state.capital
        except CapitalUnavailableError:
            raise RuntimeError(
                "Cannot start execution: Kite margin unavailable. "
                "Please check authentication and try again."
            )

        risk_manager = RiskManager(
            config.risk, config.strategy, capital=live_capital,
            plan_max_age_hours=config.execution.plan_max_age_hours,
            max_entry_price_drift_pct=config.execution.max_entry_price_drift_pct,
            margin_fetcher=margin_fetcher,
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

        regime_monitor = None
        if config.jev and config.jev.enabled:
            from tradingbot.core.jev_client import JevClient
            from tradingbot.executor.regime_monitor import RegimeMonitor
            try:
                jev_client = JevClient(config.jev)
                if jev_client.available:
                    regime_monitor = RegimeMonitor(jev_client, check_interval_seconds=300)
                    logger.info("Regime monitor enabled (every 5min)")
            except Exception:
                logger.warning("Regime monitor setup failed", exc_info=True)

        executor = Executor(
            broker=broker,
            plan=plan,
            risk_manager=risk_manager,
            database=state.database,
            execution_config=config.execution,
            mode=mode,
            intelligence=intelligence,
            regime_monitor=regime_monitor,
            telegram=getattr(state, "_telegram", None),
        )

        state.executor_ref = executor
        await state.event_bus.emit("exec.started", {
            "trade_date": plan.trade_date,
            "mode": mode.value,
            "legs": [leg.to_dict() for leg in plan.legs],
        })

        executor.start()

        # Late-start catch-up: if market open > 15 min, fetch morning context
        from tradingbot.executor.session_catchup import SessionCatchup, apply_catchup_decisions
        from tradingbot.core.models import now_ist
        catchup = SessionCatchup(
            kite_client=data_kite_client,
            instrument_cache=instrument_cache,
        )
        current_time = now_ist().time()
        if catchup.should_run(current_time):
            logger.info("Late start detected (%s) — running morning catch-up", current_time.strftime("%H:%M"))
            symbols = [leg.symbol for leg in plan.legs]
            contexts = catchup.fetch_morning_context(symbols)
            decisions = catchup.evaluate(contexts, plan.legs)
            apply_catchup_decisions(executor.states, decisions)

            telegram = getattr(state, "_telegram", None)
            if telegram:
                telegram.notify_catchup_summary(decisions)

            await state.event_bus.emit("exec.catchup", {
                "decisions": {s: d.action for s, d in decisions.items()},
            })
        else:
            logger.info("On-time start (%s) — skipping catch-up", current_time.strftime("%H:%M"))

        ws_mgr: ConnectionManager | None = getattr(state, "ws_manager", None)
        last_decision_count = 0

        while not executor.is_done:
            executor.tick()

            # Watchdog: force-reconnect ticker if ticks are stale
            if intelligence is not None:
                try:
                    intelligence.check_and_reconnect()
                except Exception:
                    pass

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

            # Periodic Telegram summary every 5 minutes
            tg = getattr(state, "_telegram", None)
            if tg and tg.enabled and hasattr(executor, "states"):
                if not hasattr(executor, "_last_tg_summary"):
                    executor._last_tg_summary = 0
                import time as _time
                now_mono = _time.monotonic()
                if now_mono - executor._last_tg_summary >= 300:
                    executor._last_tg_summary = now_mono
                    from tradingbot.core.models import now_ist
                    ist_now = now_ist()
                    lines = [
                        f"📊 <b>{ist_now.strftime('%H:%M')} IST</b>",
                        f"",
                    ]
                    for st in executor.states:
                        sym = st.leg.symbol
                        d_emoji = "📉" if st.leg.direction.value == "short" else "📈"
                        direction = st.leg.direction.value.upper()
                        if st.filled_quantity > 0:
                            try:
                                price = executor.broker.get_ltp(sym)
                                delta = price - st.entry_fill_price
                                if st.leg.direction.value == "short":
                                    delta = -delta
                                pnl = delta * st.filled_quantity
                                pnl_emoji = "\U0001f7e2" if pnl >= 0 else "\U0001f534"
                                sign = "+" if pnl >= 0 else ""
                                lines.append(
                                    f"{d_emoji} <b>{sym}</b> {direction}\n"
                                    f"   <code>@ {st.entry_fill_price:.2f}  →  ₹{price:.2f}</code>\n"
                                    f"   {pnl_emoji} {sign}₹{pnl:,.0f}"
                                )
                            except Exception:
                                lines.append(f"{d_emoji} <b>{sym}</b> {direction}  •  <code>@ {st.entry_fill_price:.2f}</code>")
                        elif st.cancelled or st.skipped_reason:
                            reason = st.skipped_reason or "cancelled"
                            lines.append(f"⏭️ <b>{sym}</b>  •  <i>{reason[:50]}</i>")
                        elif st.waiting:
                            lines.append(f"⏳ <b>{sym}</b> {direction}  •  <i>waiting</i>")
                        else:
                            lines.append(f"🔄 <b>{sym}</b> {direction}  •  <i>evaluating</i>")
                    if intelligence:
                        h = intelligence.health
                        t_dot = "\U0001f7e2" if h.status == "healthy" else "\U0001f534"
                        lines.append(f"\n⚡ Ticker {t_dot} {h.status}  •  {h.reconnect_count} reconnects")
                    try:
                        tg.send_sync("\n".join(lines))
                    except Exception:
                        pass

            await asyncio.sleep(_tick_interval())

        state.executor_status = "done"
        await state.event_bus.emit("exec.session_done", {
            "total_pnl": state.database.realised_pnl_for_date(plan.trade_date),
            "trades_count": len(state.database.trades_for_date(plan.trade_date)),
            "mode": mode.value,
        })

        # EOD square-off verification — only near market close
        from tradingbot.core.models import now_ist
        from datetime import time as dt_time
        ist_now = now_ist().time()
        if mode is Mode.LIVE and ist_now >= dt_time(15, 5):
            await _verify_squareoff(state, broker, plan)

    except asyncio.CancelledError:
        state.executor_status = "idle"
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("execution failed: %s", exc, exc_info=True)
        state.executor_status = "idle"


async def _verify_squareoff(state: AppState, broker, plan) -> None:
    """Wait 60s after session done, then verify all positions are flat."""
    try:
        await asyncio.sleep(60)
        plan_symbols = {leg.symbol for leg in plan.legs}
        positions = broker.get_positions()
        still_open = [p for p in positions if p.symbol in plan_symbols and p.quantity != 0]
        if not still_open:
            logger.info("Square-off verification: all positions flat")
            return

        for pos in still_open:
            logger.error("CRITICAL: %s still open after square-off! qty=%d", pos.symbol, pos.quantity)
            try:
                from tradingbot.core.broker import OrderSide, OrderType
                side = OrderSide.BUY if pos.quantity < 0 else OrderSide.SELL
                # Use LIMIT with 1% slippage — Kite rejects naked MARKET orders via API
                ltp = broker.get_ltp(pos.symbol)
                slippage = ltp * 0.01
                limit_price = round(ltp + slippage, 2) if side == OrderSide.BUY else round(ltp - slippage, 2)
                broker.place_order(
                    symbol=pos.symbol, side=side,
                    order_type=OrderType.LIMIT, quantity=abs(pos.quantity),
                    price=limit_price,
                )
                logger.info("Emergency limit order placed for %s x%d @ %.2f", pos.symbol, abs(pos.quantity), limit_price)
            except Exception:
                logger.error("Emergency exit FAILED for %s", pos.symbol, exc_info=True)

        tg = getattr(state, "_telegram", None)
        if tg:
            symbols = ", ".join(p.symbol for p in still_open)
            tg.notify_squareoff_failed(symbols)
    except Exception:
        logger.error("Square-off verification failed", exc_info=True)


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

    # Scout alerts (observation only — no execution)
    scout_alerts: list[dict] = []
    if intel is not None:
        try:
            scanner = getattr(state, "_scout_scanner", None)
            if scanner is None:
                from tradingbot.executor.scout_scanner import ScoutScanner
                scanner = ScoutScanner(database=state.database)
                state._scout_scanner = scanner
            for leg_state in (executor.states if executor and hasattr(executor, "states") else []):
                sym = leg_state.leg.symbol
                candles = intel.aggregator.get_candles(sym, "1min")
                if candles:
                    scanner.grade_pending(sym, candles)
                    alerts = scanner.scan(sym, candles)
                    for a in alerts:
                        alert_dict = a.to_dict()
                        if state.database is not None:
                            from tradingbot.core.models import now_ist
                            alert_dict["trade_date"] = now_ist().strftime("%Y-%m-%d")
                            try:
                                db_id = state.database.save_scout_alert(alert_dict)
                                scanner.add_pending(db_id, a)
                            except Exception:
                                pass
                        scout_alerts.append(alert_dict)
        except Exception:
            pass

    # Include persisted alerts for today
    if state.database is not None and not scout_alerts:
        try:
            from tradingbot.core.models import now_ist
            today = now_ist().strftime("%Y-%m-%d")
            scout_alerts = state.database.get_scout_alerts(trade_date=today)
        except Exception:
            pass

    return {
        "status": state.executor_status,
        "mode": state.executor_mode,
        "positions": positions,
        "ticker_health": ticker_health,
        "decision_log": decision_log,
        "scout_alerts": scout_alerts,
    }


@router.get("/decisions")
async def get_decisions(request: Request, date: str | None = None):
    state: AppState = request.app.state.app_state
    if state.database is None:
        return []
    if date:
        return state.database.get_decisions_for_date(date)
    from tradingbot.core.models import now_ist
    today = now_ist().strftime("%Y-%m-%d")
    return state.database.get_decisions_for_date(today)


@router.get("/scout/stats")
async def scout_stats(request: Request):
    state: AppState = request.app.state.app_state
    if state.database is None:
        return {"total": 0, "wins": 0, "losses": 0, "timeouts": 0, "win_rate": 0, "avg_pnl_pct": 0}
    return state.database.scout_alert_stats()


@router.get("/scout/alerts")
async def scout_alerts_history(request: Request, date: str | None = None, limit: int = 50):
    state: AppState = request.app.state.app_state
    if state.database is None:
        return []
    return state.database.get_scout_alerts(trade_date=date, limit=limit)
