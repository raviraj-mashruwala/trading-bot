"""Tests for v2 pipeline integration in analysis routes.

Pipeline logic is tested in tests/analysis/test_pipeline.py.
These tests verify the routing: v2 dispatches to _run_analysis_v2,
v1 (default) still dispatches to _run_analysis_v1, and shared
behavior (409, trading day validation) works for both.
"""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date

from tradingbot.core.models import AnalysisRun, MarketRegime


async def test_analyze_v2_dispatches_to_v2_handler(api_client):
    """POST /analyze with pipeline=v2 calls _run_analysis_v2."""
    with patch("tradingbot.api.analysis_routes._run_analysis_v2") as mock_v2:
        mock_v2.return_value = None

        response = await api_client.post(
            "/api/analyze",
            json={"trade_date": "2026-09-29", "pipeline": "v2"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "started"
        assert data["trade_date"] == "2026-09-29"

        # Allow background task to run
        await asyncio.sleep(0.1)

        mock_v2.assert_called_once()
        call_args = mock_v2.call_args
        assert call_args[0][1] == date(2026, 9, 29)  # trade_date arg


async def test_analyze_v1_is_default(api_client):
    """POST /analyze without pipeline param calls _run_analysis_v1 (legacy)."""
    with patch("tradingbot.api.analysis_routes._run_analysis_v1") as mock_v1:
        mock_v1.return_value = None

        response = await api_client.post(
            "/api/analyze",
            json={"trade_date": "2026-09-29"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "started"

        await asyncio.sleep(0.1)

        mock_v1.assert_called_once()


async def test_analyze_v2_sets_status_complete_on_success(api_client):
    """_run_analysis_v2 sets state.analysis_status to 'complete'."""

    async def fake_v2(state, trade_date):
        state.analysis_status = "complete"
        state.analysis_error = None

    with patch("tradingbot.api.analysis_routes._run_analysis_v2", side_effect=fake_v2):
        response = await api_client.post(
            "/api/analyze",
            json={"trade_date": "2026-09-29", "pipeline": "v2"},
        )
        assert response.status_code == 200

        await asyncio.sleep(0.1)

        status_resp = await api_client.get("/api/analyze/status")
        status_data = status_resp.json()
        assert status_data["status"] == "complete"
        assert status_data["trade_date"] == "2026-09-29"


async def test_analyze_v2_409_when_already_running(api_client):
    """POST /analyze with pipeline=v2 returns 409 if analysis already running."""
    state = api_client._app.state.app_state
    state.analysis_status = "running"
    state.analysis_task = asyncio.ensure_future(asyncio.sleep(999))

    response = await api_client.post(
        "/api/analyze",
        json={"pipeline": "v2"},
    )
    assert response.status_code == 409

    state.analysis_task.cancel()
    try:
        await state.analysis_task
    except asyncio.CancelledError:
        pass
    state.analysis_status = "idle"


async def test_analyze_v2_rejects_non_trading_day(api_client):
    """POST /analyze with v2 pipeline rejects non-trading days same as v1."""
    response = await api_client.post(
        "/api/analyze",
        json={"trade_date": "2026-09-26", "pipeline": "v2"},
    )
    assert response.status_code == 400
    assert "trading day" in response.json()["detail"].lower()


async def test_analyze_explicit_v1_dispatches_to_v1_handler(api_client):
    """POST /analyze with pipeline=v1 explicitly calls _run_analysis_v1."""
    with patch("tradingbot.api.analysis_routes._run_analysis_v1") as mock_v1:
        mock_v1.return_value = None

        response = await api_client.post(
            "/api/analyze",
            json={"trade_date": "2026-09-29", "pipeline": "v1"},
        )
        assert response.status_code == 200

        await asyncio.sleep(0.1)

        mock_v1.assert_called_once()
