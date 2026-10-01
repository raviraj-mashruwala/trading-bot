"""Market calendar routes — status, holidays, refresh."""

from __future__ import annotations

from fastapi import APIRouter

from tradingbot.scanner import calendar as cal

router = APIRouter(prefix="/api")


def _calendar_response() -> dict:
    now = cal.now_ist()
    today = now.date()
    status_info = cal.market_status()
    session = cal.next_trading_session()
    year = today.year
    holidays = cal.get_holidays(year)
    first, last = cal.calendar_coverage()

    upcoming = [h for h in holidays if h.date >= today][:10]

    return {
        "status": status_info.status,
        "reason": status_info.reason,
        "holiday_name": status_info.holiday_name,
        "next_session": session.isoformat(),
        "today_is_trading_day": cal.is_trading_day(today),
        "holidays": [{"date": h.date.isoformat(), "name": h.name} for h in upcoming],
        "total_holidays_this_year": len(holidays),
        "coverage": {"first": first.isoformat(), "last": last.isoformat()},
        "current_year_covered": first.year <= year <= last.year,
        "data_year": year,
    }


@router.get("/market-calendar")
async def get_market_calendar():
    return _calendar_response()


@router.post("/market-calendar/refresh")
async def refresh_market_calendar():
    cal.clear_cache()
    return _calendar_response()
