"""Plan CRUD routes."""

from __future__ import annotations

from datetime import date as _date

from fastapi import APIRouter, HTTPException, Request

from tradingbot.api.state import AppState
from tradingbot.core.plan_store import PlanCorruptError, PlanNotFoundError

router = APIRouter(prefix="/api")


def _ensure_stores(state: AppState) -> None:
    if state.run_store is None:
        from pathlib import Path
        from tradingbot.persistence.run_store import RunStore
        from tradingbot.persistence.setup_store import SetupStore
        db_path = Path(state.data_dir) / "analysis.db"
        state.run_store = RunStore(db_path)
        state.setup_store = SetupStore(db_path)


@router.get("/plans")
async def list_plans(request: Request):
    state: AppState = request.app.state.app_state
    plans = []
    for path in sorted(state.plan_store.plan_dir.glob("*.json")):
        try:
            plan = state.plan_store.load(path.stem)
            plans.append({
                "trade_date": plan.trade_date,
                "legs_count": len(plan.legs),
                "market_regime": plan.market_regime.value,
                "generated_at": plan.generated_at.isoformat(),
            })
        except (PlanNotFoundError, PlanCorruptError):
            continue
    return plans


@router.get("/plans/today")
async def get_plan_today(request: Request):
    state: AppState = request.app.state.app_state
    _ensure_stores(state)
    from tradingbot.scanner.calendar import is_trading_day
    from tradingbot.core.models import now_ist
    now = now_ist()
    today = now.date()
    if is_trading_day(today) and now.hour < 16:
        target = today
    else:
        from tradingbot.scanner.calendar import next_trading_day
        target = next_trading_day(today)
    plan = None
    for d in [target, today]:
        try:
            plan = state.plan_store.load(str(d))
            break
        except (PlanNotFoundError, PlanCorruptError):
            continue
    if plan is None:
        raise HTTPException(status_code=404, detail="no plan for today")

    setups = []
    if state.setup_store is not None:
        for d in [target, today]:
            rows = state.setup_store.get_active(d)
            if rows:
                setups = rows
                break

    ranked = []
    for i, s in enumerate(setups):
        ranked.append({
            "rank": i + 1,
            "symbol": s.get("symbol", ""),
            "direction": s.get("direction", "long"),
            "confidence": s.get("confidence", 0),
            "consistency": 1.0,
            "run_count": 1,
            "recommendation": "execute" if s.get("status") in ("approved", "active") else "watch",
            "best_setup": s,
        })

    runs = []
    if state.run_store is not None:
        for d in [target, today]:
            runs = state.run_store.list_for_date(d)
            if runs:
                break

    return {
        "date": str(plan.trade_date),
        "runs": runs,
        "total_runs": len(runs),
        "active_setups": setups,
        "ranked_suggestions": ranked,
    }


@router.get("/plans/runs")
async def get_plan_runs(request: Request):
    state: AppState = request.app.state.app_state
    _ensure_stores(state)
    if state.run_store is None:
        raise HTTPException(status_code=404, detail="no plan for runs")
    try:
        from tradingbot.scanner.calendar import is_trading_day
        from tradingbot.core.models import now_ist
        now = now_ist()
        today = now.date()
        if is_trading_day(today) and now.hour < 16:
            target = today
        else:
            from tradingbot.scanner.calendar import next_trading_day
            target = next_trading_day(today)
        runs = state.run_store.list_for_date(target)
        if not runs:
            runs = state.run_store.list_for_date(today)
        if not runs:
            raise HTTPException(status_code=404, detail="no runs found")
        return runs
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="no plan for runs")


@router.get("/plans/setups")
async def get_plan_setups(request: Request):
    state: AppState = request.app.state.app_state
    _ensure_stores(state)
    if state.setup_store is None:
        raise HTTPException(status_code=404, detail="no plan for setups")
    try:
        from tradingbot.scanner.calendar import is_trading_day
        from tradingbot.core.models import now_ist
        now = now_ist()
        today = now.date()
        if is_trading_day(today) and now.hour < 16:
            target = today
        else:
            from tradingbot.scanner.calendar import next_trading_day
            target = next_trading_day(today)
        rows = state.setup_store.get_active(target)
        if not rows:
            rows = state.setup_store.get_active(today)
        if not rows:
            raise HTTPException(status_code=404, detail="no plan for setups")
        return rows
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="no plan for setups")


@router.get("/plans/{date}")
async def get_plan(date: str, request: Request):
    state: AppState = request.app.state.app_state
    try:
        plan = state.plan_store.load(date)
        return plan.to_dict()
    except PlanNotFoundError:
        raise HTTPException(status_code=404, detail=f"no plan for {date}")
    except PlanCorruptError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/plans/{date}")
async def delete_plan(date: str, request: Request):
    state: AppState = request.app.state.app_state
    path = state.plan_store.path_for(date)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"no plan for {date}")
    path.unlink()
    return {"status": "deleted", "trade_date": date}


@router.post("/plans/{date}/approve")
async def approve_plan(date: str, request: Request):
    state: AppState = request.app.state.app_state
    if state.database is None:
        raise HTTPException(status_code=500, detail="database unavailable")
    state.database.approve_plan(date)
    return {"status": "approved", "trade_date": date}


@router.get("/plans/{date}/review-status")
async def plan_review_status(date: str, request: Request):
    state: AppState = request.app.state.app_state
    if state.database is None:
        return {"reviewed": False}
    return {"reviewed": state.database.is_plan_reviewed(date)}
