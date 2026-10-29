from datetime import date, datetime, timedelta

import pytest

from tradingbot.core.database import Database
from tradingbot.core.models import (
    IST, Direction, ExecutedTrade, Mode, StrategyName, TradeStatus,
)


# Relative to today so the 30-day history window never ages out of the fixtures.
RECENT_DAY = (date.today() - timedelta(days=1)).isoformat()
PREVIOUS_DAY = (date.today() - timedelta(days=2)).isoformat()


def make_trade(trade_date, symbol, pnl):
    return ExecutedTrade(
        trade_date=trade_date, symbol=symbol, strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG, quantity=10, entry_price=100.0,
        exit_price=100.0 + pnl / 10, stop_loss=95.0, target_1=110.0,
        target_2=115.0, entered_at=datetime(2026, 9, 24, 9, 45, tzinfo=IST),
        exited_at=datetime(2026, 9, 24, 13, 15, tzinfo=IST), pnl=pnl,
        exit_reason="target_1", status=TradeStatus.CLOSED, mode=Mode.PAPER,
    )


@pytest.fixture(autouse=True)
def seed_trades(api_client):
    tmp = api_client._tmp_path
    db = Database(tmp / "tradingbot.db")
    db.initialise()
    db.record_trade(make_trade(RECENT_DAY, "RELIANCE", 1040.0))
    db.record_trade(make_trade(RECENT_DAY, "TCS", -400.0))
    db.record_trade(make_trade(PREVIOUS_DAY, "INFY", 500.0))
    db.close()


async def test_get_trades_returns_recent_history(api_client):
    response = await api_client.get("/api/trades?days=30")
    assert response.status_code == 200
    assert len(response.json()) == 3


async def test_get_trades_filters_by_date(api_client):
    response = await api_client.get(f"/api/trades?date={RECENT_DAY}")
    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_get_trade_stats(api_client):
    response = await api_client.get("/api/trades/stats?days=30")
    assert response.status_code == 200
    stats = response.json()
    assert stats["trade_count"] == 3
    assert stats["total_pnl"] == pytest.approx(1140.0)
    assert stats["win_rate"] == pytest.approx(2 / 3)
