"""Tests for Kite OAuth API endpoints."""

import pytest
from unittest.mock import MagicMock, patch


async def test_kite_login_returns_url(api_client):
    with patch("tradingbot.api.analysis_routes._ensure_kite_auth") as mock_auth:
        auth = MagicMock()
        auth.get_login_url.return_value = "https://kite.zerodha.com/connect/login?v=3&api_key=test"
        mock_auth.return_value = auth
        response = await api_client.get("/api/auth/kite/login")
        assert response.status_code == 200
        data = response.json()
        assert "login_url" in data
        assert "kite.zerodha.com" in data["login_url"]


async def test_kite_status_unauthenticated(api_client):
    response = await api_client.get("/api/auth/kite/status")
    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is False


async def test_kite_callback_without_token_returns_400(api_client):
    response = await api_client.get("/api/auth/kite/callback")
    assert response.status_code == 400


async def test_kite_callback_with_valid_token(api_client):
    with patch("tradingbot.api.analysis_routes._ensure_kite_auth") as mock_ensure:
        auth = MagicMock()
        auth.generate_session.return_value = {
            "access_token": "test_token",
            "user_id": "AB1234",
        }
        mock_ensure.return_value = auth
        response = await api_client.get(
            "/api/auth/kite/callback?request_token=test_req",
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert "kite=success" in response.headers["location"]
