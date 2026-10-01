"""Tests for market calendar API routes."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

IST = ZoneInfo("Asia/Kolkata")


@pytest.mark.asyncio
async def test_get_market_calendar(api_client):
    mock_now = datetime(2026, 9, 24, 10, 30, tzinfo=IST)
    with patch("tradingbot.scanner.calendar.now_ist", return_value=mock_now):
        resp = await api_client.get("/api/market-calendar")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "open"
    assert data["today_is_trading_day"] is True
    assert "next_session" in data
    assert "holidays" in data
    assert isinstance(data["holidays"], list)
    assert "coverage" in data
    assert data["current_year_covered"] is True


@pytest.mark.asyncio
async def test_get_market_calendar_on_holiday(api_client):
    mock_now = datetime(2026, 1, 26, 10, 30, tzinfo=IST)
    with patch("tradingbot.scanner.calendar.now_ist", return_value=mock_now):
        resp = await api_client.get("/api/market-calendar")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "holiday"
    assert data["today_is_trading_day"] is False


@pytest.mark.asyncio
async def test_refresh_market_calendar(api_client):
    resp = await api_client.post("/api/market-calendar/refresh")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "holidays" in data
