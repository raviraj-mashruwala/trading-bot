"""Tests for POST /api/emergency-stop endpoint."""

from unittest.mock import MagicMock, patch

import pytest


async def test_emergency_stop_requires_kite_auth(api_client):
    """Should return 400 when Kite is not authenticated."""
    response = await api_client.post("/api/emergency-stop")
    assert response.status_code == 400
    assert "Kite not authenticated" in response.json()["detail"]


async def test_emergency_stop_with_no_orders_or_positions(api_client):
    """Should succeed silently when nothing is open."""
    state = api_client._app.state.app_state

    # Wire up authenticated kite_auth mock
    mock_auth = MagicMock()
    mock_auth.is_authenticated.return_value = True
    mock_kite = MagicMock()
    mock_kite.orders.return_value = []
    mock_kite.positions.return_value = {"net": []}
    mock_auth.kite = mock_kite
    state.kite_auth = mock_auth

    # Patch KiteClient so it returns our mock kite
    mock_kite_client = MagicMock()
    mock_kite_client.kite = mock_kite

    with patch(
        "tradingbot.data.kite_client.KiteClient", return_value=mock_kite_client,
    ), patch(
        "tradingbot.execution.kite_executor.KiteExecutor.__init__", return_value=None,
    ):
        response = await api_client.post("/api/emergency-stop")

    assert response.status_code == 200
    data = response.json()
    assert data["cancelled"] == 0
    assert data["squared_off"] == 0
    assert data["errors"] == 0
