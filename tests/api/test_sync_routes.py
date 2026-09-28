"""Tests for data sync API endpoints."""

import pytest


async def test_sync_status_idle(api_client):
    response = await api_client.get("/api/sync/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "idle"


async def test_sync_requires_kite_auth(api_client):
    response = await api_client.post("/api/sync")
    assert response.status_code == 400
    assert "Kite not authenticated" in response.json()["detail"]


async def test_sync_returns_409_when_running(api_client):
    state = api_client._app.state.app_state
    state.sync_status = "running"
    response = await api_client.post("/api/sync")
    assert response.status_code == 409
    state.sync_status = "idle"
