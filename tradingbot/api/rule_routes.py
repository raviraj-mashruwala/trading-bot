"""API for the rule executor (KEC short). Separate from /api/execute; the plan executor is untouched."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, replace
from datetime import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from tradingbot.core.models import now_ist
from tradingbot.rule_executor.executor import RuleExecutor
from tradingbot.rule_executor.kec_rule import KecRuleConfig, evaluate_signal
from tradingbot.rule_executor.store import RuleStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rules/kec", tags=["rules"])

RULE_NAME = "kec_short"
LIVE_CONFIRMATION = "LIVE"
MIN_NOTIONAL, MAX_NOTIONAL = 5_000.0, 1_000_000.0


@dataclass
class RuleRuntime:
    executor: RuleExecutor | None = None
    task: asyncio.Task | None = None
    error: str | None = None
    store: RuleStore | None = None


def _runtime(request: Request) -> RuleRuntime:
    rt = getattr(request.app.state, "rule_runtime", None)
    if rt is None:
        rt = RuleRuntime()
        request.app.state.rule_runtime = rt
    if rt.store is None:
        rt.store = RuleStore(request.app.state.app_state.database.connection, RULE_NAME)
    return rt


def _kite(config):
    from kiteconnect import KiteConnect

    token_path = Path.home() / ".tradingbot" / "kite_token"
    if not token_path.exists():
        raise HTTPException(status_code=400, detail="Kite not connected. Log in from Settings first.")
    kite = KiteConnect(api_key=config.secrets.kite_api_key)
    kite.set_access_token(token_path.read_text().strip())
    try:
        kite.profile()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Kite token invalid or expired: {exc}. Log in again.") from exc
    return kite


def _is_running(rt: RuleRuntime) -> bool:
    return rt.task is not None and not rt.task.done()


def _tick_seconds() -> float:
    t = now_ist().time()
    return 2.0 if time(9, 14) <= t <= time(9, 32) else 5.0


async def _run(rt: RuleRuntime, executor: RuleExecutor) -> None:
    try:
        await asyncio.to_thread(executor.start)
        while not executor.is_done:
            await asyncio.to_thread(executor.tick)
            await asyncio.sleep(_tick_seconds())
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("rule executor crashed: %s", exc, exc_info=True)
        rt.error = str(exc)
        tg = executor._telegram
        if tg is not None:
            try:
                tg.notify_critical(f"KEC rule executor crashed: {exc}. Check any open position in Kite.")
            except Exception:  # noqa: BLE001
                pass


@router.get("/status")
async def status(request: Request):
    rt = _runtime(request)
    ex = rt.executor
    return {
        "running": _is_running(rt),
        "error": rt.error,
        "session": ex.status() if ex else None,
        "defaults": {k: (v.strftime("%H:%M") if isinstance(v, time) else v) for k, v in asdict(KecRuleConfig()).items()},
    }


@router.get("/preview")
async def preview(request: Request):
    """Today's conditions from Kite, without trading."""
    from tradingbot.rule_executor.market import KiteMarketData

    cfg = KecRuleConfig()
    market = KiteMarketData(_kite(request.app.state.app_state.config))
    now = now_ist()
    bars = await asyncio.to_thread(market.completed_daily_bars, cfg.symbol, now, cfg.adr_days + 5)
    if not bars:
        raise HTTPException(status_code=502, detail="no daily bars returned by Kite")
    prev = bars[-1]
    after_open = now.time() >= cfg.signal_time
    today_open = await asyncio.to_thread(market.today_open, cfg.symbol) if after_open else None
    signal = evaluate_signal(bars, today_open or 0.0, cfg) if today_open else None
    rng = prev.high - prev.low
    prev_pos = (prev.close - prev.low) / rng if rng > 0 else 0.5
    adr = sum((b.high - b.low) / b.close for b in bars[-cfg.adr_days:]) / min(cfg.adr_days, len(bars))
    return {
        "as_of": now.isoformat(),
        "previous_session": str(prev.day),
        "previous_close": prev.close,
        "previous_close_pos": round(prev_pos, 3),
        "weak_close_met": prev_pos <= cfg.weak_close_max,
        "gap_trigger_price": round(prev.close * (1 + cfg.gap_min), 2),
        "adr_pct": round(adr * 100, 3),
        "today_open": today_open,
        "signal": signal.to_dict() if signal else None,
    }


@router.post("/start")
async def start(request: Request):
    rt = _runtime(request)
    if _is_running(rt):
        raise HTTPException(status_code=409, detail="rule executor already running; stop it first")
    body = await request.json() if (await request.body()) else {}
    mode = body.get("mode", "paper")
    if mode not in ("paper", "live"):
        raise HTTPException(status_code=400, detail="mode must be paper or live")
    if mode == "live" and body.get("confirm") != LIVE_CONFIRMATION:
        raise HTTPException(status_code=400, detail=f'live trading needs "confirm": "{LIVE_CONFIRMATION}"')
    notional = float(body.get("notional", KecRuleConfig.notional))
    if not MIN_NOTIONAL <= notional <= MAX_NOTIONAL:
        raise HTTPException(status_code=400, detail=f"notional must be between {MIN_NOTIONAL:.0f} and {MAX_NOTIONAL:.0f}")

    from tradingbot.scanner import calendar as cal

    today = now_ist().date()
    if not cal.is_trading_day(today):
        raise HTTPException(status_code=400, detail=f"{today} is not an NSE trading day")

    state = request.app.state.app_state
    config = state.config
    kite = _kite(config)

    from tradingbot.rule_executor.market import KiteMarketData

    if mode == "paper":
        from tradingbot.rule_executor.paper_broker import RulePaperBroker

        def price_feed(symbol: str) -> float:
            key = f"NSE:{symbol}"
            return float(kite.ltp([key])[key]["last_price"])

        broker = RulePaperBroker(config.paper, price_feed=price_feed)
    else:
        from tradingbot.core.kite_client import KiteClient

        broker = KiteClient(api_key=config.secrets.kite_api_key, api_secret=config.secrets.kite_api_secret, kite=kite)

    executor = RuleExecutor(
        broker=broker, market=KiteMarketData(kite), store=rt.store, mode=mode,
        config=replace(KecRuleConfig(), notional=notional), telegram=getattr(state, "_telegram", None),
    )
    rt.executor, rt.error = executor, None
    rt.task = asyncio.create_task(_run(rt, executor))
    return {"status": "started", "mode": mode, "notional": notional}


@router.post("/stop")
async def stop(request: Request):
    rt = _runtime(request)
    if rt.executor is None or not _is_running(rt):
        return {"status": "not_running"}
    rt.executor.stop()
    try:
        await asyncio.wait_for(rt.task, timeout=15)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        rt.task.cancel()
    position_open = rt.executor.state.phase == "in_position"
    return {"status": "stopped", "position_left_open": position_open}


@router.get("/trades")
async def trades(request: Request, limit: int = 200):
    return _runtime(request).store.trades(limit=limit)


@router.get("/events")
async def events(request: Request, date: str | None = None, limit: int = 200):
    return _runtime(request).store.events(trade_date=date, limit=limit)
