"""Trade history and stats routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from tradingbot.api.state import AppState
from tradingbot.core.models import now_ist

router = APIRouter(prefix="/api")

NIFTY_SECTORS = {
    "Banks": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "BANKBARODA", "PNB", "INDUSINDBK", "BANDHANBNK", "IDFCFIRSTB", "FEDERALBNK", "KARURVYSYA", "AUBANK"],
    "IT": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM", "MPHASIS", "COFORGE", "PERSISTENT", "SONATSOFTW"],
    "Pharma": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "AUROPHARMA", "BIOCON", "LUPIN", "TORNTPHARM", "FORTIS", "MOREPENLAB"],
    "Auto": ["MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO", "HEROMOTOCO", "EICHERMOT", "ASHOKLEY", "TVSMTR"],
    "Infrastructure": ["ADANIENT", "ADANIPORTS", "LT", "KEC", "COCHINSHIP", "IRCON", "NBCC", "INOXWIND"],
    "Energy": ["RELIANCE", "ONGC", "BPCL", "IOC", "NTPC", "POWERGRID", "TATAPOWER", "ADANIGREEN"],
    "Metals": ["TATASTEEL", "HINDALCO", "JSWSTEEL", "VEDL", "NMDC", "COALINDIA", "SAIL", "NATIONALUM", "JAIBALAJI"],
    "FMCG": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR", "MARICO", "COLPAL", "GODREJCP", "TATACONSUM"],
    "Realty": ["DLF", "GODREJPROP", "PRESTIGE", "OBEROIRLTY", "BRIGADE", "DBREALTY", "SOBHA"],
    "Chemicals": ["PIDILITIND", "UPL", "SRF", "AARTI", "DEEPAKNTR", "CLEAN", "DHAMPURSUG", "INDIAGLYCO"],
}


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


@router.get("/sectors/heatmap")
async def sector_heatmap(request: Request):
    state: AppState = request.app.state.app_state
    candle_store = getattr(state, "candle_store", None)
    if candle_store is None:
        return []

    from datetime import date, timedelta
    today = now_ist().date()
    yesterday = today - timedelta(days=1)

    sectors = []
    for sector_name, symbols in NIFTY_SECTORS.items():
        changes = []
        for sym in symbols:
            try:
                df = candle_store.read(sym, "day", from_date=yesterday, to_date=today)
                if df is not None and len(df) >= 2:
                    prev_close = float(df.iloc[-2]["close"])
                    curr_close = float(df.iloc[-1]["close"])
                    if prev_close > 0:
                        changes.append((curr_close - prev_close) / prev_close * 100)
                elif df is not None and len(df) == 1:
                    row = df.iloc[0]
                    if float(row["open"]) > 0:
                        changes.append((float(row["close"]) - float(row["open"])) / float(row["open"]) * 100)
            except Exception:
                continue

        if changes:
            avg_change = sum(changes) / len(changes)
            sectors.append({
                "sector": sector_name,
                "avg_change_pct": round(avg_change, 2),
                "stock_count": len(changes),
                "total_stocks": len(symbols),
            })

    sectors.sort(key=lambda s: s["avg_change_pct"], reverse=True)
    return sectors


@router.get("/trades/stats/by-strategy")
async def strategy_performance(request: Request):
    state: AppState = request.app.state.app_state
    return state.database.strategy_stats()


@router.post("/trades/{trade_id}/notes")
async def update_trade_notes(trade_id: int, request: Request):
    state: AppState = request.app.state.app_state
    body = await request.json()
    notes = body.get("notes", "")
    state.database.update_trade_notes(trade_id, notes)
    return {"status": "ok", "trade_id": trade_id}
