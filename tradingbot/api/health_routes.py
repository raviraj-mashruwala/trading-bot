"""GET /api/health — server and dependency status."""

from __future__ import annotations

from fastapi import APIRouter, Request

from tradingbot.api.state import AppState

router = APIRouter(prefix="/api")


@router.get("/health")
async def health(request: Request):
    state: AppState = request.app.state.app_state
    db_ok = True
    try:
        state.database.connection.execute("SELECT 1")
    except Exception:  # noqa: BLE001
        db_ok = False

    return {
        "api": "ok",
        "database": "ok" if db_ok else "error",
        "llm": "unconfigured",
    }
