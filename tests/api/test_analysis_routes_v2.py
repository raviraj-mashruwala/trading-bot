"""Tests for analysis pipeline integration in analysis routes.

Pipeline logic is tested in tests/analysis/test_pipeline.py.
These tests verify that POST /analyze dispatches to _run_analysis,
and shared behavior (409, trading day validation) works.
"""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date

from tradingbot.core.models import AnalysisRun, MarketRegime


async def test_analyze_dispatches_to_handler(api_client):
    """POST /analyze calls _run_analysis."""
    with patch("tradingbot.api.analysis_routes._run_analysis") as mock_run:
        mock_run.return_value = None

        response = await api_client.post(
            "/api/analyze",
            json={"trade_date": "2026-09-29"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "started"
        assert data["trade_date"] == "2026-09-29"

        # Allow background task to run
        await asyncio.sleep(0.1)

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][1] == date(2026, 9, 29)  # trade_date arg


async def test_analyze_sets_status_complete_on_success(api_client):
    """_run_analysis sets state.analysis_status to 'complete'."""

    async def fake_run(state, trade_date):
        state.analysis_status = "complete"
        state.analysis_error = None

    with patch("tradingbot.api.analysis_routes._run_analysis", side_effect=fake_run):
        response = await api_client.post(
            "/api/analyze",
            json={"trade_date": "2026-09-29"},
        )
        assert response.status_code == 200

        await asyncio.sleep(0.1)

        status_resp = await api_client.get("/api/analyze/status")
        status_data = status_resp.json()
        assert status_data["status"] == "complete"
        assert status_data["trade_date"] == "2026-09-29"


async def test_analyze_409_when_already_running(api_client):
    """POST /analyze returns 409 if analysis already running."""
    state = api_client._app.state.app_state
    state.analysis_status = "running"
    state.analysis_task = asyncio.ensure_future(asyncio.sleep(999))

    response = await api_client.post(
        "/api/analyze",
        json={},
    )
    assert response.status_code == 409

    state.analysis_task.cancel()
    try:
        await state.analysis_task
    except asyncio.CancelledError:
        pass
    state.analysis_status = "idle"


async def test_analyze_rejects_non_trading_day(api_client):
    """POST /analyze rejects non-trading days."""
    response = await api_client.post(
        "/api/analyze",
        json={"trade_date": "2026-09-26"},
    )
    assert response.status_code == 400
    assert "trading day" in response.json()["detail"].lower()


async def test_analyze_ignores_pipeline_param(api_client):
    """POST /analyze ignores the pipeline param (v2 is always used)."""
    with patch("tradingbot.api.analysis_routes._run_analysis") as mock_run:
        mock_run.return_value = None

        response = await api_client.post(
            "/api/analyze",
            json={"trade_date": "2026-09-29", "pipeline": "v1"},
        )
        assert response.status_code == 200

        await asyncio.sleep(0.1)

        mock_run.assert_called_once()
