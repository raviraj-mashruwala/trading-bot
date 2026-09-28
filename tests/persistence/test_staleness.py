"""Tests for setup staleness detection."""

import pytest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from tradingbot.persistence.run_store import RunStore
from tradingbot.persistence.setup_store import SetupStore
from tradingbot.persistence.daily_plan import DailyPlanBuilder
from tradingbot.core.models import AnalysisRun, MarketRegime

IST = ZoneInfo("Asia/Kolkata")


def _save_setup(store, run_id, symbol, confidence, created_hours_ago):
    created = (datetime.now(tz=IST) - timedelta(hours=created_hours_ago)).isoformat()
    store._conn.execute(
        "INSERT INTO setups (run_id, trade_date, symbol, strategy, direction, "
        "entry_price, stop_loss, target_1, target_2, confidence, status, reasoning, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, str(date.today()), symbol, "momentum", "long",
         1000, 980, 1030, 1050, confidence, "approved", "test", created, created),
    )
    store._conn.commit()


def test_stale_in_volatile_regime(tmp_path):
    db = tmp_path / "test.db"
    store = SetupStore(db)
    _save_setup(store, "run_001", "OLD_STOCK", 0.8, created_hours_ago=3)
    _save_setup(store, "run_001", "NEW_STOCK", 0.8, created_hours_ago=1)

    stale_count = store.mark_stale("volatile", datetime.now(tz=IST))
    assert stale_count == 1  # OLD_STOCK stale (3h > 2h threshold)

    old = store.get_for_symbol("OLD_STOCK", date.today())
    assert old[0]["status"] == "stale"

    new = store.get_for_symbol("NEW_STOCK", date.today())
    assert new[0]["status"] == "approved"  # still fresh


def test_stale_in_normal_regime(tmp_path):
    db = tmp_path / "test.db"
    store = SetupStore(db)
    _save_setup(store, "run_001", "AGED", 0.8, created_hours_ago=5)

    stale_count = store.mark_stale("trending_up", datetime.now(tz=IST))
    assert stale_count == 1  # 5h > 4h threshold for non-volatile


def test_no_stale_when_fresh(tmp_path):
    db = tmp_path / "test.db"
    store = SetupStore(db)
    _save_setup(store, "run_001", "FRESH", 0.8, created_hours_ago=1)

    stale_count = store.mark_stale("volatile", datetime.now(tz=IST))
    assert stale_count == 0


def test_only_approved_active_marked_stale(tmp_path):
    """Rejected/closed setups should not be marked stale."""
    db = tmp_path / "test.db"
    store = SetupStore(db)
    _save_setup(store, "run_001", "OLD_REJECTED", 0.8, created_hours_ago=5)
    # Manually set status to rejected
    store._conn.execute(
        "UPDATE setups SET status = 'rejected' WHERE symbol = 'OLD_REJECTED'"
    )
    store._conn.commit()

    stale_count = store.mark_stale("trending_up", datetime.now(tz=IST))
    assert stale_count == 0  # rejected setup not touched


def test_daily_plan_marks_stale_recommendation(tmp_path):
    db = tmp_path / "test.db"
    run_store = RunStore(db)
    setup_store = SetupStore(db)

    run_store.save(AnalysisRun(
        run_id="run_001", timestamp=datetime.now(tz=IST),
        trade_date=date.today(), market_regime=MarketRegime.VOLATILE,
        regime_confidence=0.8, total_scanned=100, tier1_passed=10,
        tier2_shortlisted=5, setups_proposed=3, setups_approved=2,
        llm_calls=5, llm_cost_usd=0.1, duration_seconds=30,
    ))
    _save_setup(setup_store, "run_001", "STALE_ONE", 0.9, created_hours_ago=3)

    builder = DailyPlanBuilder(run_store, setup_store)
    plan = builder.build(date.today())
    # After mark_stale runs, the stale setup should not appear in ranked_suggestions
    # (because get_active filters for approved/active, stale setups are excluded)
    stale_setups = setup_store.get_for_symbol("STALE_ONE", date.today())
    assert stale_setups[0]["status"] == "stale"
