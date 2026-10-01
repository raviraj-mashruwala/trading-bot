"""NSE trading calendar backed by exchange_calendars.

Provides trading-day checks, market status, and holiday lists for NSE.
The exchange_calendars package is lazy-loaded and cached to avoid slow
import at module level.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

MARKET_PRE_OPEN = time(9, 0)
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
MARKET_POST_CLOSE = time(16, 0)


class NotATradingDayError(Exception):
    """Raised when an operation is attempted for a non-trading date."""


@dataclass(frozen=True)
class MarketStatusInfo:
    status: str  # "open" | "pre_market" | "post_market" | "closed" | "holiday"
    reason: str
    holiday_name: str | None = None


@dataclass(frozen=True)
class HolidayInfo:
    date: date
    name: str


# ---------------------------------------------------------------------------
# Lazy calendar singleton
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_cal = None
_holiday_cache: dict[int, list[HolidayInfo]] = {}


def _calendar():
    """Lazy-load the BSE (XBOM) calendar — same holidays as NSE. Thread-safe."""
    global _cal
    cal = _cal
    if cal is None:
        with _lock:
            cal = _cal
            if cal is None:
                import exchange_calendars as xcals
                cal = xcals.get_calendar("BSE")
                _cal = cal
    return cal


def clear_cache() -> None:
    """Drop cached calendar and holiday data. Used by the refresh endpoint."""
    global _cal, _holiday_cache
    with _lock:
        _cal = None
        _holiday_cache = {}


def _year_in_range(year: int) -> bool:
    cal = _calendar()
    return cal.first_session.year <= year <= cal.last_session.year


# ---------------------------------------------------------------------------
# Holiday name resolution
# ---------------------------------------------------------------------------

_FIXED_DATE_NAMES: dict[tuple[int, int], str] = {
    (1, 26): "Republic Day",
    (4, 14): "Dr. Ambedkar Jayanti",
    (5, 1): "Maharashtra Day",
    (8, 15): "Independence Day",
    (10, 2): "Gandhi Jayanti",
    (12, 25): "Christmas",
}

_VARIABLE_DATE_NAMES: dict[int, dict[tuple[int, int], str]] = {
    2025: {
        (2, 26): "Maha Shivaratri",
        (3, 14): "Holi",
        (3, 31): "Id-ul-Fitr",
        (4, 10): "Shri Mahavir Jayanti",
        (4, 18): "Good Friday",
        (5, 12): "Buddha Purnima",
        (6, 7): "Id-ul-Adha",
        (7, 6): "Muharram",
        (8, 16): "Janmashtami",
        (9, 5): "Milad-un-Nabi",
        (10, 21): "Dussehra",
        (10, 22): "Diwali (Laxmi Pujan)",
        (11, 5): "Guru Nanak Jayanti",
    },
    2026: {
        (1, 15): "Makar Sankranti",
        (3, 3): "Holi",
        (3, 26): "Shab-e-Meraj",
        (3, 31): "Id-ul-Fitr",
        (4, 3): "Good Friday",
        (5, 28): "Buddha Purnima",
        (6, 26): "Muharram",
        (9, 14): "Ganesh Chaturthi",
        (10, 20): "Dussehra",
        (11, 10): "Diwali (Laxmi Pujan)",
        (11, 24): "Guru Nanak Jayanti",
    },
}


def _resolve_holiday_name(day: date) -> str:
    """Look up holiday name from fixed-date and variable-date mappings."""
    key = (day.month, day.day)
    if key in _FIXED_DATE_NAMES:
        return _FIXED_DATE_NAMES[key]
    year_map = _VARIABLE_DATE_NAMES.get(day.year, {})
    if key in year_map:
        return year_map[key]
    return "Market Holiday"


# ---------------------------------------------------------------------------
# Public API — backward compatible
# ---------------------------------------------------------------------------


def is_trading_day(day: date) -> bool:
    """True for weekdays that are not on the NSE holiday list."""
    if day.weekday() >= 5:
        return False
    if not _year_in_range(day.year):
        return True
    import pandas as pd
    return _calendar().is_session(pd.Timestamp(day))


def next_trading_day(day: date) -> date:
    """The first trading day strictly after the given date."""
    import pandas as pd
    candidate = day + timedelta(days=1)
    cal = _calendar()
    if not _year_in_range(candidate.year):
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate
    return cal.date_to_session(pd.Timestamp(candidate), direction="next").date()


# ---------------------------------------------------------------------------
# Public API — new
# ---------------------------------------------------------------------------


def now_ist() -> datetime:
    """Current time in IST. Extracted for testability."""
    return datetime.now(tz=IST)


def get_holidays(year: int) -> list[HolidayInfo]:
    """All NSE holidays for a given year, sorted by date."""
    if year in _holiday_cache:
        return _holiday_cache[year]
    if not _year_in_range(year):
        return []
    import pandas as pd
    cal = _calendar()
    start = pd.Timestamp(f"{year}-01-01")
    end = pd.Timestamp(f"{year}-12-31")
    all_weekdays = pd.bdate_range(start, end)
    sessions = cal.sessions_in_range(start, end)
    holiday_dates = all_weekdays.difference(sessions)
    holidays = sorted(
        [HolidayInfo(date=d.date(), name=_resolve_holiday_name(d.date())) for d in holiday_dates],
        key=lambda h: h.date,
    )
    _holiday_cache[year] = holidays
    return holidays


def get_holiday_name(day: date) -> str | None:
    """Return the holiday name for a date, or None if not a holiday."""
    holidays = get_holidays(day.year)
    for h in holidays:
        if h.date == day:
            return h.name
    return None


def market_status() -> MarketStatusInfo:
    """Current NSE market status based on IST wall-clock time."""
    now = now_ist()
    today = now.date()
    current_time = now.time()

    if today.weekday() >= 5:
        return MarketStatusInfo(status="closed", reason="weekend")

    if not is_trading_day(today):
        name = get_holiday_name(today)
        return MarketStatusInfo(
            status="holiday",
            reason=name or "Market Holiday",
            holiday_name=name,
        )

    if current_time < MARKET_PRE_OPEN:
        return MarketStatusInfo(status="closed", reason="before_hours")
    if current_time < MARKET_OPEN:
        return MarketStatusInfo(status="pre_market", reason="Pre-open session")
    if current_time <= MARKET_CLOSE:
        return MarketStatusInfo(status="open", reason="Normal trading session")
    if current_time <= MARKET_POST_CLOSE:
        return MarketStatusInfo(status="post_market", reason="Closing session")
    return MarketStatusInfo(status="closed", reason="after_hours")


def next_trading_session() -> datetime:
    """Datetime of next market open (9:15 IST) on a trading day."""
    now = now_ist()
    today = now.date()

    if is_trading_day(today) and now.time() < MARKET_OPEN:
        session_date = today
    else:
        session_date = next_trading_day(today)

    return datetime.combine(session_date, MARKET_OPEN, tzinfo=IST)


def calendar_coverage() -> tuple[date, date]:
    """Return (first_session, last_session) of the loaded calendar."""
    cal = _calendar()
    return cal.first_session.date(), cal.last_session.date()
