"""Plan CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from tradingbot.api.state import AppState
from tradingbot.core.plan_store import PlanCorruptError, PlanNotFoundError

router = APIRouter(prefix="/api")


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
