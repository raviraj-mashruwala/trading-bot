"""Tests for NSE market calendar backed by exchange_calendars."""

from datetime import date, datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from tradingbot.scanner.calendar import (
    HolidayInfo,
    MarketStatusInfo,
    NotATradingDayError,
    calendar_coverage,
    clear_cache,
    get_holidays,
    is_trading_day,
    market_status,
    next_trading_day,
    next_trading_session,
)

IST = ZoneInfo("Asia/Kolkata")


# --- Backward-compatible API ---


def test_weekday_is_trading_day():
    assert is_trading_day(date(2026, 9, 24)) is True


def test_saturday_is_not_trading_day():
    assert is_trading_day(date(2026, 9, 26)) is False


def test_sunday_is_not_trading_day():
    assert is_trading_day(date(2026, 9, 27)) is False


def test_republic_day_is_not_trading_day():
    assert is_trading_day(date(2026, 1, 26)) is False


def test_independence_day_is_not_trading_day():
    assert is_trading_day(date(2026, 8, 15)) is False


def test_next_trading_day_skips_weekend():
    assert next_trading_day(date(2026, 9, 25)) == date(2026, 9, 28)


def test_next_trading_day_skips_holiday():
    # Jan 23 (Fri) -> Jan 26 is Republic Day (Mon) -> Jan 27 (Tue)
    assert next_trading_day(date(2026, 1, 23)) == date(2026, 1, 27)


def test_not_a_trading_day_error_names_date():
    with pytest.raises(NotATradingDayError, match="2026-09-26"):
        raise NotATradingDayError("2026-09-26 is not an NSE trading day")


# --- New API: market_status ---


def test_market_status_open_during_session():
    mock_now = datetime(2026, 9, 24, 10, 30, tzinfo=IST)
    with patch("tradingbot.scanner.calendar.now_ist", return_value=mock_now):
        result = market_status()
    assert result.status == "open"


def test_market_status_closed_on_weekend():
    mock_now = datetime(2026, 9, 26, 10, 30, tzinfo=IST)
    with patch("tradingbot.scanner.calendar.now_ist", return_value=mock_now):
        result = market_status()
    assert result.status == "closed"
    assert result.reason == "weekend"


def test_market_status_holiday():
    mock_now = datetime(2026, 1, 26, 10, 30, tzinfo=IST)
    with patch("tradingbot.scanner.calendar.now_ist", return_value=mock_now):
        result = market_status()
    assert result.status == "holiday"
    assert result.holiday_name is not None


def test_market_status_pre_market():
    mock_now = datetime(2026, 9, 24, 9, 10, tzinfo=IST)
    with patch("tradingbot.scanner.calendar.now_ist", return_value=mock_now):
        result = market_status()
    assert result.status == "pre_market"


def test_market_status_post_market():
    mock_now = datetime(2026, 9, 24, 15, 45, tzinfo=IST)
    with patch("tradingbot.scanner.calendar.now_ist", return_value=mock_now):
        result = market_status()
    assert result.status == "post_market"


def test_market_status_before_hours():
    mock_now = datetime(2026, 9, 24, 7, 0, tzinfo=IST)
    with patch("tradingbot.scanner.calendar.now_ist", return_value=mock_now):
        result = market_status()
    assert result.status == "closed"
    assert result.reason == "before_hours"


def test_market_status_after_hours():
    mock_now = datetime(2026, 9, 24, 16, 30, tzinfo=IST)
    with patch("tradingbot.scanner.calendar.now_ist", return_value=mock_now):
        result = market_status()
    assert result.status == "closed"
    assert result.reason == "after_hours"


# --- New API: next_trading_session ---


def test_next_trading_session_from_weekday_evening():
    mock_now = datetime(2026, 9, 24, 16, 30, tzinfo=IST)  # Thu evening
    with patch("tradingbot.scanner.calendar.now_ist", return_value=mock_now):
        result = next_trading_session()
    assert result.date() == date(2026, 9, 25)  # Friday
    assert result.time() == time(9, 15)
    assert result.tzinfo is not None


def test_next_trading_session_during_market_hours():
    mock_now = datetime(2026, 9, 24, 10, 30, tzinfo=IST)  # Thu midday
    with patch("tradingbot.scanner.calendar.now_ist", return_value=mock_now):
        result = next_trading_session()
    assert result.date() == date(2026, 9, 25)


def test_next_trading_session_from_weekend():
    mock_now = datetime(2026, 9, 26, 10, 0, tzinfo=IST)  # Saturday
    with patch("tradingbot.scanner.calendar.now_ist", return_value=mock_now):
        result = next_trading_session()
    assert result.date() == date(2026, 9, 28)  # Monday


def test_next_trading_session_before_market_open():
    mock_now = datetime(2026, 9, 24, 7, 0, tzinfo=IST)  # Thu early morning
    with patch("tradingbot.scanner.calendar.now_ist", return_value=mock_now):
        result = next_trading_session()
    assert result.date() == date(2026, 9, 24)  # Today — market hasn't opened yet
    assert result.time() == time(9, 15)


# --- New API: get_holidays ---


def test_get_holidays_returns_list():
    holidays = get_holidays(2026)
    assert len(holidays) > 0
    assert all(isinstance(h, HolidayInfo) for h in holidays)


def test_get_holidays_republic_day_present():
    holidays = get_holidays(2026)
    dates = [h.date for h in holidays]
    assert date(2026, 1, 26) in dates


def test_get_holidays_sorted_by_date():
    holidays = get_holidays(2026)
    dates = [h.date for h in holidays]
    assert dates == sorted(dates)


def test_get_holidays_all_have_names():
    holidays = get_holidays(2026)
    for h in holidays:
        assert h.name, f"Holiday on {h.date} has no name"


# --- Cache ---


def test_clear_cache_does_not_raise():
    clear_cache()


# --- Coverage ---


def test_calendar_coverage_returns_date_range():
    first, last = calendar_coverage()
    assert first < last
    assert first.year <= 2026
