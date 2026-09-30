"""Tests for setup_id persistence in the trades table."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tradingbot.core.database import Database
from tradingbot.core.models import (
    Direction,
    ExecutedTrade,
    Mode,
    StrategyName,
    TradeStatus,
)

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.initialise()
    yield d
    d.close()


def _make_trade(setup_id: int | None = None) -> ExecutedTrade:
    return ExecutedTrade(
        trade_date="2026-09-30",
        symbol="TCS",
        strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG,
        quantity=100,
        entry_price=3502.0,
        exit_price=3598.0,
        stop_loss=3450.0,
        target_1=3600.0,
        target_2=3680.0,
        entered_at=datetime(2026, 9, 30, 9, 35, tzinfo=IST),
        exited_at=datetime(2026, 9, 30, 11, 20, tzinfo=IST),
        pnl=9600.0,
        exit_reason="target_hit",
        status=TradeStatus.CLOSED,
        mode=Mode.PAPER,
        setup_id=setup_id,
    )


def test_record_trade_persists_setup_id(db):
    trade = _make_trade(setup_id=42)
    trade_id = db.record_trade(trade)
    assert trade_id > 0

    rows = db.trades_for_date("2026-09-30")
    assert len(rows) == 1
    assert rows[0].setup_id == 42


def test_record_trade_persists_none_setup_id(db):
    trade = _make_trade(setup_id=None)
    db.record_trade(trade)

    rows = db.trades_for_date("2026-09-30")
    assert rows[0].setup_id is None


def test_migration_idempotent(tmp_path):
    d1 = Database(tmp_path / "idem.db")
    d1.initialise()
    d1.record_trade(_make_trade(setup_id=1))
    d1.close()

    d2 = Database(tmp_path / "idem.db")
    d2.initialise()
    rows = d2.trades_for_date("2026-09-30")
    assert rows[0].setup_id == 1
    d2.close()
