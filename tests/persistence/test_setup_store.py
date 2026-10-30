"""Tests for SetupStore analytics field persistence and idempotent migration."""

from __future__ import annotations

import pytest
from tradingbot.persistence.setup_store import SetupStore


@pytest.fixture
def store(tmp_path):
    return SetupStore(tmp_path / "test.db")


def _base_setup(**overrides) -> dict:
    base = {
        "run_id": "run_20260929_001",
        "trade_date": "2026-09-29",
        "symbol": "TCS",
        "strategy": "momentum",
        "direction": "long",
        "entry_price": 3500.0,
        "stop_loss": 3450.0,
        "target_1": 3600.0,
        "target_2": 3680.0,
        "confidence": 0.78,
        "status": "approved",
        "reasoning": "strong momentum setup",
    }
    base.update(overrides)
    return base


def test_save_with_new_fields_returns_id(store):
    setup = _base_setup(
        thesis="Breakout above 6-month resistance with volume confirmation",
        invalidation_condition="Close below 3460 on 15m candle",
        bear_case="Market could gap down on global cues",
        confluence_count=4,
        entry_trigger="Break above 3510 with vol > 1.5x avg",
        regime_at_generation="trending_up",
        timeframe_alignment=["15m", "1h", "day"],
    )
    row_id = store.save(setup)
    assert isinstance(row_id, int) and row_id > 0


def test_new_fields_roundtrip(store):
    row_id = store.save(_base_setup(
        invalidation_condition="Close below 3460",
        bear_case="FII selling could resume",
        confluence_count=3,
        regime_at_generation="trending_up",
    ))
    row = store.get_by_id(row_id)
    assert row["invalidation_condition"] == "Close below 3460"
    assert row["bear_case"] == "FII selling could resume"
    assert row["confluence_count"] == 3
    assert row["regime_at_generation"] == "trending_up"


def test_save_without_new_fields_still_works(store):
    """Old callers that don't pass new fields must not break."""
    row_id = store.save(_base_setup())
    assert row_id > 0
    row = store.get_by_id(row_id)
    assert row.get("invalidation_condition") in (None, "")


def test_migration_idempotent(tmp_path):
    """Opening SetupStore twice on same DB must not crash on duplicate columns."""
    db = tmp_path / "idem.db"
    s1 = SetupStore(db)
    s1.save(_base_setup())
    s1.close()
    s2 = SetupStore(db)  # must not raise
    s2.close()


def test_supersede_approved_retires_only_approved_rows_for_that_date(store):
    from datetime import date

    approved = store.save(_base_setup())
    active = store.save(_base_setup(symbol="INFY", status="active"))
    other_day = store.save(_base_setup(symbol="WIPRO", trade_date="2026-09-30"))

    count = store.supersede_approved(date(2026, 9, 29), "replaced by rerun")

    assert count == 1
    assert store.get_by_id(approved)["status"] == "superseded"
    assert store.get_by_id(approved)["rejection_reason"] == "replaced by rerun"
    assert store.get_by_id(active)["status"] == "active"
    assert store.get_by_id(other_day)["status"] == "approved"
    assert [row["id"] for row in store.get_active(date(2026, 9, 29))] == [active]
