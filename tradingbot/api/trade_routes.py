"""Trade history and stats routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from tradingbot.api.state import AppState
from tradingbot.core.models import now_ist

router = APIRouter(prefix="/api")


@router.get("/trades")
async def get_trades(request: Request, days: int = 30, date: str | None = None):
    state: AppState = request.app.state.app_state
    if date is not None:
        rows = state.database.connection.execute(
            "SELECT * FROM trades WHERE trade_date = ? ORDER BY id", (date,)
        ).fetchall()
    else:
        from datetime import timedelta
        today = now_ist().date()
        cutoff = (today - timedelta(days=days)).isoformat()
        rows = state.database.connection.execute(
            "SELECT * FROM trades WHERE trade_date >= ? ORDER BY trade_date, id", (cutoff,)
        ).fetchall()

    return [
        {
            "id": row["id"],
            "trade_date": row["trade_date"],
            "symbol": row["symbol"],
            "strategy": row["strategy"],
            "direction": row["direction"],
            "quantity": row["quantity"],
            "entry_price": row["entry_price"],
            "exit_price": row["exit_price"],
            "pnl": row["pnl"],
            "exit_reason": row["exit_reason"],
            "status": row["status"],
            "mode": row["mode"],
            "entered_at": row["entered_at"],
            "exited_at": row["exited_at"],
            "notes": row["notes"] if "notes" in row.keys() else "",
        }
        for row in rows
    ]


@router.get("/trades/stats")
async def get_trade_stats(request: Request, days: int = 30):
    state: AppState = request.app.state.app_state
    today = now_ist().date()
    trades = state.database.recent_trades(days=days, today=today)

    if not trades:
        return {
            "trade_count": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
            "max_drawdown": 0.0,
            "best_day": 0.0,
            "worst_day": 0.0,
        }

    wins = [t for t in trades if t.pnl > 0]
    total = sum(t.pnl for t in trades)

    daily_pnl: dict[str, float] = {}
    for t in trades:
        daily_pnl[t.trade_date] = daily_pnl.get(t.trade_date, 0.0) + t.pnl
    daily_values = list(daily_pnl.values())

    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for day_pnl in daily_values:
        cumulative += day_pnl
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)

    return {
        "trade_count": len(trades),
        "win_rate": len(wins) / len(trades),
        "total_pnl": total,
        "avg_pnl": total / len(trades),
        "max_drawdown": max_drawdown,
        "best_day": max(daily_values),
        "worst_day": min(daily_values),
    }


@router.post("/trades/{trade_id}/notes")
async def update_trade_notes(trade_id: int, request: Request):
    state: AppState = request.app.state.app_state
    body = await request.json()
    notes = body.get("notes", "")
    state.database.update_trade_notes(trade_id, notes)
    return {"status": "ok", "trade_id": trade_id}
