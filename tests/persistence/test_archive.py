"""Tests for RunStore.archive_old() — 7-day data archival."""

import pytest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from tradingbot.persistence.run_store import RunStore
from tradingbot.persistence.setup_store import SetupStore

IST = ZoneInfo("Asia/Kolkata")


def test_archive_old_runs(tmp_path):
    store = RunStore(tmp_path / "test.db")
    old_date = (date.today() - timedelta(days=10)).isoformat()
    recent_date = date.today().isoformat()

    store._conn.execute(
        "INSERT INTO analysis_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("old_run", old_date, datetime.now(tz=IST).isoformat(), "trending_up", 0.8,
         100, 10, 5, 3, 2, 5, 0.1, 30),
    )
    store._conn.execute(
        "INSERT INTO analysis_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("new_run", recent_date, datetime.now(tz=IST).isoformat(), "trending_up", 0.8,
         100, 10, 5, 3, 2, 5, 0.1, 30),
    )
    store._conn.commit()

    archived = store.archive_old(days=7)
    assert archived == 1
    remaining = store.list_for_date(date.fromisoformat(old_date))
    assert len(remaining) == 0
    recent = store.list_for_date(date.today())
    assert len(recent) == 1


def test_archive_skips_runs_with_active_setups(tmp_path):
    db = tmp_path / "test.db"
    run_store = RunStore(db)
    setup_store = SetupStore(db)

    old_date = (date.today() - timedelta(days=10)).isoformat()
    run_store._conn.execute(
        "INSERT INTO analysis_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("active_run", old_date, datetime.now(tz=IST).isoformat(), "trending_up", 0.8,
         100, 10, 5, 3, 2, 5, 0.1, 30),
    )
    run_store._conn.commit()

    setup_store.save({
        "run_id": "active_run", "trade_date": old_date, "symbol": "TEST",
        "strategy": "momentum", "direction": "long", "entry_price": 100,
        "stop_loss": 95, "target_1": 110, "target_2": 120, "confidence": 0.8,
        "status": "active", "reasoning": "test",
    })

    archived = run_store.archive_old(days=7, setup_store=setup_store)
    assert archived == 0  # skipped because setup is active


def test_archive_old_no_rows_to_archive(tmp_path):
    store = RunStore(tmp_path / "test.db")
    archived = store.archive_old(days=7)
    assert archived == 0
