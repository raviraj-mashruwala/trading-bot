from datetime import date

import pytest

from tradingbot.scanner.calendar import NotATradingDayError, is_trading_day, next_trading_day


def test_a_weekday_that_is_not_a_holiday_is_a_trading_day():
    assert is_trading_day(date(2026, 9, 24)) is True


def test_saturday_is_not_a_trading_day():
    assert is_trading_day(date(2026, 9, 26)) is False


def test_sunday_is_not_a_trading_day():
    assert is_trading_day(date(2026, 9, 27)) is False


def test_republic_day_is_not_a_trading_day():
    assert is_trading_day(date(2026, 1, 26)) is False


def test_independence_day_is_not_a_trading_day():
    assert is_trading_day(date(2026, 8, 15)) is False


def test_next_trading_day_skips_the_weekend():
    assert next_trading_day(date(2026, 9, 25)) == date(2026, 9, 28)


def test_next_trading_day_skips_a_holiday():
    assert next_trading_day(date(2026, 1, 23)) == date(2026, 1, 27)


def test_not_a_trading_day_error_names_the_date():
    with pytest.raises(NotATradingDayError, match="2026-09-26"):
        raise NotATradingDayError("2026-09-26 is not an NSE trading day")
