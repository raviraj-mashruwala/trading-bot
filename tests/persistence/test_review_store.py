"""Tests for TradeReviewStore — joins trades + setups into scorecards."""

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
from tradingbot.persistence.review_store import TradeReviewStore
from tradingbot.persistence.setup_store import SetupStore

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def stores(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    db.initialise()
    ss = SetupStore(db_path)
    rs = TradeReviewStore(db_path)
    yield db, ss, rs
    db.close()
    ss.close()
    rs.close()


def _save_setup(ss, **overrides) -> int:
    base = {
        "run_id": "run_001", "trade_date": "2026-09-30", "symbol": "TCS",
        "strategy": "breakout", "direction": "long", "entry_price": 3500.0,
        "stop_loss": 3450.0, "target_1": 3600.0, "target_2": 3680.0,
        "confidence": 0.78, "status": "approved", "reasoning": "test",
        "invalidation_condition": "Close below 3460", "bear_case": "FII selling",
        "confluence_count": 4, "regime_at_generation": "trending_up", "thesis": "Breakout",
    }
    base.update(overrides)
    return ss.save(base)


def _save_trade(db, setup_id, **overrides) -> int:
    base = dict(
        trade_date="2026-09-30", symbol="TCS", strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG, quantity=100, entry_price=3502.0,
        exit_price=3598.0, stop_loss=3450.0, target_1=3600.0, target_2=3680.0,
        entered_at=datetime(2026, 9, 30, 9, 35, tzinfo=IST),
        exited_at=datetime(2026, 9, 30, 11, 20, tzinfo=IST),
        pnl=9600.0, exit_reason="target_hit", status=TradeStatus.CLOSED,
        mode=Mode.PAPER, setup_id=setup_id,
    )
    base.update(overrides)
    return db.record_trade(ExecutedTrade(**base))


def test_get_scorecard_returns_linked_data(stores):
    db, ss, rs = stores
    setup_id = _save_setup(ss)
    trade_id = _save_trade(db, setup_id)

    sc = rs.get_scorecard(trade_id)
    assert sc is not None
    assert sc.setup_id == setup_id
    assert sc.predicted_entry == 3500.0
    assert sc.actual_entry == 3502.0
    assert sc.confluence_count == 4
    assert sc.regime_at_generation == "trending_up"


def test_get_scorecard_returns_none_for_missing(stores):
    _, _, rs = stores
    assert rs.get_scorecard(999) is None


def test_scorecard_excludes_trades_without_setup_id(stores):
    db, _, rs = stores
    _save_trade(db, setup_id=None)

    cards = rs.get_scorecards_for_date("2026-09-30")
    assert len(cards) == 0


def test_get_scorecards_for_date(stores):
    db, ss, rs = stores
    s1 = _save_setup(ss, symbol="TCS")
    s2 = _save_setup(ss, symbol="INFY")
    _save_trade(db, s1, symbol="TCS")
    _save_trade(db, s2, symbol="INFY", pnl=-2000.0, exit_reason="stop_hit")

    cards = rs.get_scorecards_for_date("2026-09-30")
    assert len(cards) == 2
    symbols = {c.symbol for c in cards}
    assert symbols == {"TCS", "INFY"}


def test_performance_stats_aggregation(stores):
    db, ss, rs = stores
    for i, (sym, pnl) in enumerate([("TCS", 5000), ("INFY", 3000), ("HDFC", -2000), ("RELIANCE", 1000)]):
        sid = _save_setup(ss, symbol=sym, confluence_count=4 if i < 2 else 2)
        _save_trade(db, sid, symbol=sym, pnl=float(pnl),
                    exit_reason="target_hit" if pnl > 0 else "stop_hit")

    stats = rs.get_performance_stats(lookback_days=30)
    assert stats.total_trades == 4
    assert stats.win_rate == pytest.approx(0.75)
    assert stats.total_pnl == pytest.approx(7000.0)


def test_empty_confluence_bucket_zero_win_rate(stores):
    db, ss, rs = stores
    sid = _save_setup(ss, confluence_count=4)
    _save_trade(db, sid, pnl=5000.0)

    stats = rs.get_performance_stats(lookback_days=30)
    assert stats.confluence_buckets["low"] == 0.0
    assert stats.confluence_buckets["high"] > 0
