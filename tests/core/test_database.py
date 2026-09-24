from datetime import date, datetime

import pytest

from tradingbot.core.database import Database
from tradingbot.core.models import (
    IST,
    Direction,
    ExecutedTrade,
    MarketRegime,
    Mode,
    StrategyName,
    TradePlan,
    TradeStatus,
)


def make_trade(trade_date: str, symbol: str, pnl: float) -> ExecutedTrade:
    return ExecutedTrade(
        trade_date=trade_date,
        symbol=symbol,
        strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG,
        quantity=10,
        entry_price=100.0,
        exit_price=100.0 + pnl / 10,
        stop_loss=95.0,
        target_1=110.0,
        target_2=115.0,
        entered_at=datetime(2026, 9, 24, 9, 45, tzinfo=IST),
        exited_at=datetime(2026, 9, 24, 13, 15, tzinfo=IST),
        pnl=pnl,
        exit_reason="target_1",
        status=TradeStatus.CLOSED,
        mode=Mode.PAPER,
    )


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialise()
    yield database
    database.close()


def test_initialise_is_idempotent(tmp_path):
    database = Database(tmp_path / "twice.db")
    database.initialise()
    database.initialise()
    database.close()


def test_record_and_read_back_a_trade(db):
    trade = make_trade("2026-09-24", "RELIANCE", 1040.0)
    trade_id = db.record_trade(trade)
    assert trade_id > 0

    stored = db.trades_for_date("2026-09-24")
    assert len(stored) == 1
    assert stored[0].symbol == "RELIANCE"
    assert stored[0].pnl == pytest.approx(1040.0)
    assert stored[0].strategy is StrategyName.BREAKOUT
    assert stored[0].mode is Mode.PAPER
    assert stored[0].entered_at.tzinfo is not None


def test_realised_pnl_sums_all_trades_for_the_day(db):
    db.record_trade(make_trade("2026-09-24", "RELIANCE", 1000.0))
    db.record_trade(make_trade("2026-09-24", "TCS", -400.0))
    db.record_trade(make_trade("2026-09-25", "INFY", 9999.0))

    assert db.realised_pnl_for_date("2026-09-24") == pytest.approx(600.0)


def test_realised_pnl_for_a_day_with_no_trades_is_zero(db):
    assert db.realised_pnl_for_date("2026-01-01") == pytest.approx(0.0)


def test_recent_trades_respects_the_lookback_window(db):
    db.record_trade(make_trade("2026-09-24", "RELIANCE", 100.0))
    db.record_trade(make_trade("2026-09-10", "TCS", 200.0))

    recent = db.recent_trades(days=7, today=date(2026, 9, 24))

    assert [trade.symbol for trade in recent] == ["RELIANCE"]


def test_save_plan_snapshot_stores_one_row_per_trade_date(db):
    plan = TradePlan(
        trade_date="2026-09-24",
        generated_at=datetime(2026, 9, 23, 22, 0, tzinfo=IST),
        capital=400000.0,
        max_risk_per_trade_pct=0.01,
        max_daily_loss_pct=0.02,
        market_regime=MarketRegime.TRENDING,
        market_summary="Nifty bullish.",
        legs=[],
    )
    db.save_plan_snapshot(plan)
    db.save_plan_snapshot(plan)

    cursor = db.connection.execute("SELECT COUNT(*) FROM plan_snapshots WHERE trade_date = ?", ("2026-09-24",))
    assert cursor.fetchone()[0] == 1
