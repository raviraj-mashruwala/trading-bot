"""NSE trading calendar. Prevents generating plans nobody can execute."""

from __future__ import annotations

from datetime import date, timedelta

NSE_HOLIDAYS_2026: frozenset[date] = frozenset(
    {
        date(2026, 1, 26),   # Republic Day
        date(2026, 3, 4),    # Holi
        date(2026, 3, 21),   # Id-ul-Fitr
        date(2026, 4, 1),    # Annual bank closing
        date(2026, 4, 3),    # Good Friday
        date(2026, 4, 14),   # Dr. Ambedkar Jayanti
        date(2026, 5, 1),    # Maharashtra Day
        date(2026, 8, 15),   # Independence Day
        date(2026, 9, 14),   # Ganesh Chaturthi
        date(2026, 10, 2),   # Gandhi Jayanti
        date(2026, 10, 20),  # Dussehra
        date(2026, 11, 9),   # Diwali Laxmi Pujan
        date(2026, 11, 24),  # Guru Nanak Jayanti
        date(2026, 12, 25),  # Christmas
    }
)


class NotATradingDayError(Exception):
    """Raised when an operation is attempted for a non-trading date."""


def is_trading_day(day: date) -> bool:
    """True for weekdays that are not on the NSE holiday list."""
    if day.weekday() >= 5:
        return False
    return day not in NSE_HOLIDAYS_2026


def next_trading_day(day: date) -> date:
    """The first trading day strictly after the given date."""
    candidate = day + timedelta(days=1)
    while not is_trading_day(candidate):
        candidate += timedelta(days=1)
    return candidate
