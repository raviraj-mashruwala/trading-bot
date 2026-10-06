"""API routes for data sync — trigger initial fill, check status, cancel."""

from __future__ import annotations

import asyncio
import logging
import time as _time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from tradingbot.api.app import get_state
from tradingbot.api.state import AppState

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sync", tags=["sync"])


async def _run_sync(state: AppState, force_full: bool = False) -> None:
    """Background task: run initial fill or daily sync."""
    try:
        config = state.config
        candle_store = state.candle_store
        if candle_store is None:
            state.sync_status = {"status": "error", "error": "CandleStore not initialized"}
            return

        from tradingbot.data.kite_data_sync import KiteDataSync
        from tradingbot.data.kite_client import KiteClient
        from tradingbot.data.instrument_cache import InstrumentCache
        from kiteconnect import KiteConnect

        kite = KiteConnect(api_key=config.secrets.kite_api_key)
        token_path = Path.home() / ".tradingbot" / "kite_token"
        if not token_path.exists():
            state.sync_status = {"status": "error", "error": "Kite not authenticated — run tradingbot auth first"}
            return
        kite.set_access_token(token_path.read_text().strip())

        kite_client = KiteClient(kite, rate_limit_per_sec=config.kite.rate_limit_per_sec)
        inst_cache = InstrumentCache(Path(state.data_dir) / "instruments.db")

        # Refresh instruments from Kite
        raw_instruments = kite_client.fetch_instruments("NSE")
        inst_cache.refresh(raw_instruments)

        sync = KiteDataSync(kite_client, candle_store, inst_cache, config.screening)

        start = _time.monotonic()

        def progress(msg: str) -> None:
            elapsed = _time.monotonic() - start
            state.sync_status = {
                "status": "running",
                "message": msg,
                "elapsed_sec": round(elapsed),
                "rows_written": getattr(sync, '_store', candle_store).row_count(),
                "freshness": {k: v.isoformat() for k, v in candle_store.freshness().items()},
            }

        freshness = candle_store.freshness()
        if not freshness or force_full:
            state.sync_status = {"status": "running", "message": "Starting initial fill..."}
            report = await sync.initial_fill(progress_callback=progress)
        else:
            state.sync_status = {"status": "running", "message": "Starting daily sync..."}
            report = await sync.daily_sync(progress_callback=progress)

        elapsed = _time.monotonic() - start
        state.sync_status = {
            "status": "complete",
            "stocks_synced": report.stocks_synced,
            "rows_written": report.rows_written,
            "errors": len(report.errors),
            "error_details": report.errors[:10],
            "elapsed_sec": round(elapsed),
            "freshness": {k: v.isoformat() for k, v in candle_store.freshness().items()},
            "row_counts": candle_store.row_count(),
        }
        log.info("Sync complete: %d stocks, %d rows, %.0fs, %d errors",
                 report.stocks_synced, report.rows_written, elapsed, len(report.errors))

        inst_cache.close()

    except asyncio.CancelledError:
        state.sync_status = {"status": "cancelled"}
        log.info("Sync cancelled")
    except Exception as exc:
        state.sync_status = {"status": "error", "error": str(exc)}
        log.error("Sync failed: %s", exc, exc_info=True)


@router.post("/start")
async def start_sync(request: Request):
    state = get_state(request)
    if state.sync_task and not state.sync_task.done():
        raise HTTPException(status_code=409, detail="Sync already running")
    body = {}
    raw = await request.body()
    if raw:
        body = await request.json()
    force_full = body.get("force_full", False)
    state.sync_status = {"status": "starting"}
    state.sync_task = asyncio.create_task(_run_sync(state, force_full=force_full))
    return {"status": "started"}


@router.get("/status")
async def sync_status(request: Request):
    from datetime import date as _date
    state = get_state(request)
    result = dict(state.sync_status)
    # Always include current cache state + staleness check
    candle_store = getattr(state, "candle_store", None)
    if candle_store is not None:
        try:
            freshness = candle_store.freshness()
            if freshness:
                result["freshness"] = {k: v.isoformat() for k, v in freshness.items()}
                result["row_counts"] = candle_store.row_count()
                # Check if daily data is stale using exchange calendar
                day_date = freshness.get("day")
                if day_date is not None:
                    try:
                        from exchange_calendars import get_calendar
                        from datetime import timedelta as _td
                        cal = get_calendar("XBOM")
                        today = _date.today()
                        # Find last trading day (today or before)
                        check = today
                        for _ in range(10):
                            if cal.is_session(str(check)):
                                break
                            check -= _td(days=1)
                        last_trading = check
                        trading_days_behind = 0
                        if day_date < last_trading:
                            from exchange_calendars import get_calendar
                            cal = get_calendar("XBOM")
                            sessions = cal.sessions_in_range(
                                str(day_date), str(last_trading)
                            )
                            trading_days_behind = max(0, len(sessions) - 1)
                        result["daily_stale"] = trading_days_behind > 0
                        result["days_behind"] = trading_days_behind
                        result["last_trading_day"] = last_trading.isoformat()
                    except Exception:
                        today = _date.today()
                        days_stale = (today - day_date).days
                        result["daily_stale"] = days_stale > 1
                        result["days_behind"] = days_stale
        except Exception:
            pass
    return result


@router.post("/cancel")
async def cancel_sync(request: Request):
    state = get_state(request)
    if state.sync_task and not state.sync_task.done():
        state.sync_task.cancel()
        return {"status": "cancelling"}
    return {"status": "not_running"}


@router.get("/gaps")
async def gap_report(request: Request):
    """Report interior gaps in cached intraday candle data."""
    state = get_state(request)
    candle_store = getattr(state, "candle_store", None)
    if candle_store is None:
        raise HTTPException(status_code=400, detail="CandleStore not initialized")
    interval = request.query_params.get("interval", "15m")
    symbol = request.query_params.get("symbol")
    threshold = float(request.query_params.get("threshold", "0.5"))
    if symbol:
        gaps = candle_store.find_gaps(symbol, interval, threshold)
        return {"symbol": symbol, "interval": interval, "gaps": [
            {"date": g[0].isoformat(), "count": g[1], "expected": g[2]} for g in gaps
        ]}
    summary = candle_store.gap_summary(interval, threshold)
    return {
        "interval": interval,
        "stocks_with_gaps": len(summary),
        "gaps": {
            sym: [{"date": g[0].isoformat(), "count": g[1], "expected": g[2]} for g in gaps]
            for sym, gaps in summary.items()
        },
    }


@router.post("/fill-gaps")
async def fill_gaps(request: Request):
    """Re-fetch only missing/incomplete candle data for cached stocks."""
    state = get_state(request)
    if state.sync_task and not state.sync_task.done():
        raise HTTPException(status_code=409, detail="Sync already running")
    candle_store = getattr(state, "candle_store", None)
    if candle_store is None:
        raise HTTPException(status_code=400, detail="CandleStore not initialized")

    body = {}
    raw = await request.body()
    if raw:
        body = await request.json()
    symbols = body.get("symbols")
    intervals = body.get("intervals")

    state.sync_status = {"status": "filling_gaps"}
    state.sync_task = asyncio.create_task(
        _run_gap_fill(state, symbols=symbols, intervals=intervals)
    )
    return {"status": "started"}


async def _run_gap_fill(
    state: AppState,
    symbols: list[str] | None = None,
    intervals: list[str] | None = None,
) -> None:
    try:
        from tradingbot.data.kite_data_sync import KiteDataSync
        from tradingbot.data.kite_client import KiteClient

        auth = None
        if hasattr(state, "kite_auth") and state.kite_auth:
            auth = state.kite_auth
        if not auth or not auth.is_authenticated():
            state.sync_status = {"status": "error", "error": "Kite not authenticated"}
            return

        kite_client = KiteClient(auth.kite, rate_limit_per_sec=3)
        from tradingbot.data.instrument_cache import InstrumentCache
        inst_cache = InstrumentCache(Path(state.data_dir) / "instruments.db")

        sync = KiteDataSync(kite_client, state.candle_store, inst_cache)
        start = _time.monotonic()

        def _progress(msg: str) -> None:
            state.sync_status = {"status": "filling_gaps", "message": msg}

        results = await sync.fill_gaps(
            symbols=symbols, intervals=intervals, progress_callback=_progress,
        )
        duration = _time.monotonic() - start
        total = sum(results.values())
        state.sync_status = {
            "status": "complete",
            "message": f"Gap fill done: {len(results)} stocks, {total:,} rows in {duration:.0f}s",
        }
        log.info("Gap fill complete: %d stocks, %d rows, %.0fs", len(results), total, duration)
    except Exception as exc:
        log.error("Gap fill failed: %s", exc, exc_info=True)
        state.sync_status = {"status": "error", "error": str(exc)}


@router.post("/purge-intraday")
async def purge_intraday(request: Request):
    """Delete all cached 15m/5m/1m data. Daily data is preserved."""
    state = get_state(request)
    if state.sync_task and not state.sync_task.done():
        raise HTTPException(status_code=409, detail="Sync running — cancel first")
    candle_store = getattr(state, "candle_store", None)
    if candle_store is None:
        raise HTTPException(status_code=400, detail="CandleStore not initialized")
    deleted = candle_store.purge_intervals(["15m", "5m", "1m"])
    log.info("Purged intraday data: %s", deleted)
    return {"purged": deleted, "remaining": candle_store.row_count()}
