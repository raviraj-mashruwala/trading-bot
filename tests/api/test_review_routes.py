"""Tests for /api/review/* endpoints."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tradingbot.core.models import (
    Direction, ExecutedTrade, Mode, StrategyName, TradeStatus,
)

IST = ZoneInfo("Asia/Kolkata")


async def test_get_scorecards_returns_linked_trades(api_client):
    from tradingbot.persistence.setup_store import SetupStore

    state = api_client._app.state.app_state
    db_path = api_client._tmp_path / "tradingbot.db"

    ss = SetupStore(db_path)
    setup_id = ss.save({
        "run_id": "run_001", "trade_date": "2026-09-30", "symbol": "TCS",
        "strategy": "breakout", "direction": "long", "entry_price": 3500.0,
        "stop_loss": 3450.0, "target_1": 3600.0, "target_2": 3680.0,
        "confidence": 0.78, "status": "approved", "reasoning": "test",
        "invalidation_condition": "Close below 3460", "bear_case": "FII selling",
        "confluence_count": 4, "regime_at_generation": "trending_up", "thesis": "Breakout",
    })
    ss.close()

    state.database.record_trade(ExecutedTrade(
        trade_date="2026-09-30", symbol="TCS", strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG, quantity=100, entry_price=3502.0, exit_price=3598.0,
        stop_loss=3450.0, target_1=3600.0, target_2=3680.0,
        entered_at=datetime(2026, 9, 30, 9, 35, tzinfo=IST),
        exited_at=datetime(2026, 9, 30, 11, 20, tzinfo=IST),
        pnl=9600.0, exit_reason="target_hit", status=TradeStatus.CLOSED,
        mode=Mode.PAPER, setup_id=setup_id,
    ))

    response = await api_client.get("/api/review/scorecards?date=2026-09-30")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["symbol"] == "TCS"
    assert body[0]["predicted_entry"] == 3500.0
    assert body[0]["confluence_count"] == 4


async def test_get_stats_returns_aggregated(api_client):
    response = await api_client.get("/api/review/stats?days=30")
    assert response.status_code == 200
    body = response.json()
    assert "total_trades" in body
    assert "confluence_buckets" in body
