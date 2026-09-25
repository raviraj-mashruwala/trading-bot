import asyncio

import pytest


async def test_analyze_status_is_idle_initially(api_client):
    response = await api_client.get("/api/analyze/status")
    assert response.status_code == 200
    assert response.json()["status"] == "idle"


async def test_analyze_returns_409_when_already_running(api_client):
    state = api_client._app.state.app_state
    state.analysis_status = "running"
    state.analysis_task = asyncio.ensure_future(asyncio.sleep(999))

    response = await api_client.post("/api/analyze")
    assert response.status_code == 409

    state.analysis_task.cancel()
    try:
        await state.analysis_task
    except asyncio.CancelledError:
        pass
    state.analysis_status = "idle"


async def test_analyze_rejects_non_trading_day(api_client):
    response = await api_client.post("/api/analyze", json={"trade_date": "2026-09-26"})
    assert response.status_code == 400
    assert "trading day" in response.json()["detail"].lower()


async def test_analyze_cancel_when_idle_returns_ok(api_client):
    response = await api_client.post("/api/analyze/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "idle"
