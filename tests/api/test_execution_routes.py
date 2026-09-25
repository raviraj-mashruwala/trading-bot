import asyncio

import pytest


async def test_execute_status_is_idle_initially(api_client):
    response = await api_client.get("/api/execute/status")
    assert response.status_code == 200
    assert response.json()["status"] == "idle"


async def test_execute_returns_400_when_no_plan(api_client):
    response = await api_client.post("/api/execute", json={"mode": "paper"})
    assert response.status_code == 400
    assert "no plan" in response.json()["detail"].lower()


async def test_execute_returns_409_when_already_running(api_client):
    state = api_client._app.state.app_state
    state.executor_status = "running"
    state.executor_task = asyncio.ensure_future(asyncio.sleep(999))

    response = await api_client.post("/api/execute", json={"mode": "paper"})
    assert response.status_code == 409

    state.executor_task.cancel()
    try:
        await state.executor_task
    except asyncio.CancelledError:
        pass
    state.executor_status = "idle"


async def test_execute_stop_when_idle_returns_ok(api_client):
    response = await api_client.post("/api/execute/stop")
    assert response.status_code == 200
