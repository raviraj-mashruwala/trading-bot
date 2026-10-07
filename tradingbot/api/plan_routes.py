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
    from tradingbot.scanner.calendar import next_trading_day
    try:
        today = next_trading_day(_date.today())
    except Exception:
        today = _date.today()
    try:
        plan = state.plan_store.load(str(today))
        return plan.to_dict()
    except (PlanNotFoundError, PlanCorruptError):
        pass
    try:
        plan = state.plan_store.load(str(_date.today()))
        return plan.to_dict()
    except PlanNotFoundError:
        raise HTTPException(status_code=404, detail="no plan for today")
    except PlanCorruptError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/plans/runs")
async def get_plan_runs(request: Request):
    state: AppState = request.app.state.app_state
    _ensure_stores(state)
    if state.run_store is None:
        raise HTTPException(status_code=404, detail="no plan for runs")
    try:
        from tradingbot.scanner.calendar import next_trading_day
        try:
            today = next_trading_day(_date.today())
        except Exception:
            today = _date.today()
        runs = state.run_store.list_for_date(today)
        if not runs:
            runs = state.run_store.list_for_date(_date.today())
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
        from tradingbot.scanner.calendar import next_trading_day
        try:
            today = next_trading_day(_date.today())
        except Exception:
            today = _date.today()
        rows = state.setup_store.get_active(today)
        if not rows:
            rows = state.setup_store.get_active(_date.today())
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
