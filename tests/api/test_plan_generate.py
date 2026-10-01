"""Tests for POST /plans/generate endpoint."""

from __future__ import annotations

import pytest


async def test_generate_plan_creates_plan_file(api_client):
    from tradingbot.persistence.setup_store import SetupStore
    db_path = api_client._tmp_path / "analysis.db"
    ss = SetupStore(db_path)
    ss.save({
        "run_id": "run_001", "trade_date": "2026-10-01", "symbol": "TCS",
        "strategy": "breakout", "direction": "long", "entry_price": 3500.0,
        "stop_loss": 3450.0, "target_1": 3600.0, "target_2": 3680.0,
        "confidence": 0.78, "status": "approved", "reasoning": "test",
    })
    ss.close()

    response = await api_client.post("/api/plans/generate?trade_date=2026-10-01")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "generated"
    assert body["legs"] >= 1

    plan_response = await api_client.get("/api/plans/2026-10-01")
    assert plan_response.status_code == 200
    plan = plan_response.json()
    assert len(plan["legs"]) >= 1
    assert plan["legs"][0]["symbol"] == "TCS"


async def test_generate_plan_with_no_approved_setups(api_client):
    response = await api_client.post("/api/plans/generate?trade_date=2026-10-02")
    assert response.status_code == 200
    body = response.json()
    assert body["legs"] == 0


async def test_generate_plan_legs_carry_setup_id(api_client):
    from tradingbot.persistence.setup_store import SetupStore
    db_path = api_client._tmp_path / "analysis.db"
    ss = SetupStore(db_path)
    setup_id = ss.save({
        "run_id": "run_001", "trade_date": "2026-10-01", "symbol": "INFY",
        "strategy": "momentum", "direction": "long", "entry_price": 1800.0,
        "stop_loss": 1770.0, "target_1": 1860.0, "target_2": 1900.0,
        "confidence": 0.82, "status": "approved", "reasoning": "test",
    })
    ss.close()

    await api_client.post("/api/plans/generate?trade_date=2026-10-01")
    plan = (await api_client.get("/api/plans/2026-10-01")).json()

    found = [l for l in plan["legs"] if l["symbol"] == "INFY"]
    assert len(found) == 1
    assert found[0]["setup_id"] == setup_id
