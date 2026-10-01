# Market Calendar System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hardcoded NSE holiday list with `exchange_calendars`-backed market calendar, expose market status/holidays via API, and show a live market status widget on the dashboard header.

**Architecture:** `exchange_calendars` XNSE calendar provides authoritative holiday dates for any year. A thin wrapper in `tradingbot/scanner/calendar.py` preserves existing `is_trading_day()`/`next_trading_day()` signatures while adding `market_status()` and `next_trading_session()`. A new API route serves calendar data to a React dashboard widget that shows market status, next session, and upcoming holidays.

**Tech Stack:** Python (`exchange_calendars`, `pandas`), FastAPI, Next.js/React, TanStack Query, Tailwind CSS

**Spec:** Design approved in-chat (bounded task, no separate spec file)

## Global Constraints

- Python ≥ 3.12, `exchange_calendars` latest stable
- All existing callers of `is_trading_day()` and `next_trading_day()` must continue working with identical signatures
- Design system compliance: DESIGN.md colors, typography, spacing — no shadows, green/red only for state
- IST timezone (`Asia/Kolkata`) for all market time calculations
- NSE market hours: pre-open 9:00–9:15, normal 9:15–15:30, post-market 15:30–16:00

## Review Focus

1. **Year boundary:** If `exchange_calendars` package is outdated and doesn't cover the current year, `is_trading_day()` must not crash — it should fall back to weekend-only check and the API should surface a stale-data warning.
2. **Timezone mismatch:** `market_status()` must use IST regardless of server timezone. A server running in UTC must still report correct open/closed state for NSE.
3. **`exchange_calendars` import cost:** The package loads all exchange metadata on import. Lazy initialization is required to avoid slowing app startup.
4. **Saturday/Sunday vs holiday:** The status widget must distinguish "Weekend" from "Holiday: Republic Day" — weekends are not holidays, even though neither is a trading day.
5. **Concurrent refresh:** Two simultaneous `POST /refresh` calls must not corrupt state — the cache-clear + rebuild must be safe.

---

### Task 1: Replace hardcoded calendar with `exchange_calendars`

**Files:**
- Modify: `pyproject.toml:6-17` (add dependency)
- Modify: `tradingbot/scanner/calendar.py` (full rewrite)
- Modify: `tests/scanner/test_calendar.py` (full rewrite)

**Interfaces:**
- Consumes: `exchange_calendars.get_calendar("XNSE")` — external library
- Produces:
  - `is_trading_day(day: date) -> bool` — backward-compatible
  - `next_trading_day(day: date) -> date` — backward-compatible
  - `market_status() -> MarketStatusInfo` (dataclass: `status: str`, `reason: str`, `holiday_name: str | None`)
  - `next_trading_session() -> datetime` — returns IST-aware datetime of next market open
  - `get_holidays(year: int) -> list[HolidayInfo]` (dataclass: `date: date`, `name: str`)
  - `clear_cache() -> None` — resets lazy-loaded calendar
  - `calendar_coverage() -> tuple[date, date]` — returns (first_session, last_session) range
  - `NotATradingDayError` — unchanged

- [ ] **Step 1: Add `exchange_calendars` dependency**

In `pyproject.toml`, add to `dependencies` list:

```toml
    "exchange_calendars>=4.5",
```

- [ ] **Step 2: Install the dependency**

Run: `cd /Users/rmashruwala/work/Personal/Projects/trading-bot && uv sync`
Expected: installs `exchange_calendars` and its transitive deps

- [ ] **Step 3: Verify XNSE calendar loads**

Run:
```bash
python3 -c "
import exchange_calendars as xcals
cal = xcals.get_calendar('XNSE')
print('First session:', cal.first_session.date())
print('Last session:', cal.last_session.date())
print('Is 2026-01-26 a session?', cal.is_session('2026-01-26'))
print('Is 2026-09-24 a session?', cal.is_session('2026-09-24'))
"
```
Expected: First/last session dates printed, Republic Day = False, normal weekday = True

- [ ] **Step 4: Write failing tests for backward-compatible API**

Replace contents of `tests/scanner/test_calendar.py`:

```python
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
    # During market hours, next session is tomorrow (or next trading day)
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
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `cd /Users/rmashruwala/work/Personal/Projects/trading-bot && python -m pytest tests/scanner/test_calendar.py -v`
Expected: ImportError or AttributeError — new functions don't exist yet

- [ ] **Step 6: Implement the calendar module**

Replace `tradingbot/scanner/calendar.py` with:

```python
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
    """Lazy-load the XNSE calendar. Thread-safe."""
    global _cal
    if _cal is None:
        with _lock:
            if _cal is None:
                import exchange_calendars as xcals
                _cal = xcals.get_calendar("XNSE")
    return _cal


def clear_cache() -> None:
    """Drop cached calendar and holiday data. Used by the refresh endpoint."""
    global _cal, _holiday_cache
    with _lock:
        _cal = None
        _holiday_cache = {}


def _year_in_range(year: int) -> bool:
    """Check if the calendar covers a given year."""
    cal = _calendar()
    return cal.first_session.year <= year <= cal.last_session.year


# ---------------------------------------------------------------------------
# Holiday name resolution
# ---------------------------------------------------------------------------

_FIXED_HOLIDAY_NAMES: dict[tuple[int, int], str] = {
    (1, 26): "Republic Day",
    (5, 1): "Maharashtra Day",
    (8, 15): "Independence Day",
    (10, 2): "Gandhi Jayanti",
    (12, 25): "Christmas",
}


def _resolve_holiday_names(year: int) -> dict[date, str]:
    """Build a date→name mapping by inspecting exchange_calendars internals,
    then falling back to fixed-date lookup."""
    import pandas as pd

    cal = _calendar()
    start = pd.Timestamp(f"{year}-01-01")
    end = pd.Timestamp(f"{year}-12-31")

    all_weekdays = pd.bdate_range(start, end)
    sessions = cal.sessions_in_range(start, end)
    holiday_dates = all_weekdays.difference(sessions)

    names: dict[date, str] = {}

    # Try extracting names from calendar's regular holiday rules
    try:
        rules = getattr(cal, "regular_holidays", None)
        if rules is not None:
            rule_list = getattr(rules, "rules", [])
            for rule in rule_list:
                rule_dates = rule.dates(start, end)
                for d in rule_dates:
                    names[d.date()] = rule.name
    except Exception:
        pass

    # Fill remaining from fixed-date lookup
    for d in holiday_dates:
        day = d.date()
        if day not in names:
            key = (day.month, day.day)
            names[day] = _FIXED_HOLIDAY_NAMES.get(key, "Market Holiday")

    return names


# ---------------------------------------------------------------------------
# Public API — backward compatible
# ---------------------------------------------------------------------------


def is_trading_day(day: date) -> bool:
    """True for weekdays that are not on the NSE holiday list."""
    if day.weekday() >= 5:
        return False
    if not _year_in_range(day.year):
        return True  # fallback: weekday-only check
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
    names = _resolve_holiday_names(year)
    holidays = sorted(
        [HolidayInfo(date=d, name=n) for d, n in names.items()],
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
```

- [ ] **Step 7: Run tests**

Run: `cd /Users/rmashruwala/work/Personal/Projects/trading-bot && python -m pytest tests/scanner/test_calendar.py -v`
Expected: All tests pass

- [ ] **Step 8: Run existing callers' tests to verify no regression**

Run: `cd /Users/rmashruwala/work/Personal/Projects/trading-bot && python -m pytest tests/api/test_analysis_routes.py tests/api/test_analysis_routes_v2.py -v`
Expected: All pass — `is_trading_day` and `next_trading_day` signatures unchanged

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml tradingbot/scanner/calendar.py tests/scanner/test_calendar.py
git commit -m "feat(calendar): replace hardcoded holidays with exchange_calendars XNSE

Adds market_status(), next_trading_session(), get_holidays() while
keeping is_trading_day()/next_trading_day() backward-compatible.
Holiday data now comes from the exchange_calendars package, which
covers NSE holidays for all supported years."
```

---

### Task 2: Calendar API routes

**Files:**
- Create: `tradingbot/api/calendar_routes.py`
- Modify: `tradingbot/api/app.py:75-89` (register router)
- Create: `tests/api/test_calendar_routes.py`

**Interfaces:**
- Consumes: `tradingbot.scanner.calendar` — `market_status()`, `next_trading_session()`, `get_holidays()`, `calendar_coverage()`, `clear_cache()`, `is_trading_day()`, `HolidayInfo`, `MarketStatusInfo`
- Produces:
  - `GET /api/market-calendar` → `{"status": str, "reason": str, "holiday_name": str|null, "next_session": str (ISO), "today_is_trading_day": bool, "holidays": [{"date": str, "name": str}], "coverage": {"first": str, "last": str}, "current_year_covered": bool}`
  - `POST /api/market-calendar/refresh` → same shape as GET, after cache clear

- [ ] **Step 1: Write failing test for GET endpoint**

Create `tests/api/test_calendar_routes.py`:

```python
"""Tests for market calendar API routes."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from tradingbot.api.app import create_app

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture()
async def client(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        '[general]\nmode = "paper"\ncapital = 100000\nlog_level = "INFO"\n'
        '[execution]\nmode = "paper"\nentry_slippage_pct = 0.05\n'
        'square_off_time = "15:10"\nconnection_timeout_sec = 30\n'
        'heartbeat_interval_sec = 60\nplan_max_age_hours = 14\n'
        'max_entry_price_drift_pct = 2.0\n'
        '[llm]\nprovider = "anthropic"\nmodel = "claude-sonnet-4-20250514"\n'
        'timeout_sec = 60\nmax_retries = 1\n'
        '[paper]\nslippage_pct = 0.05\ninitial_capital = 100000\n'
        '[strategy]\nbacktest_days = 30\ncandle_interval = "15minute"\n'
        'min_confidence = 0.5\nmin_reward_risk = 1.5\nmax_trades_per_day = 2\n'
    )
    env = {
        "ANTHROPIC_API_KEY": "test-key",
        "KITE_API_KEY": "test-key",
        "KITE_API_SECRET": "test-secret",
    }
    with patch.dict("os.environ", env):
        app = create_app(config_path=config, data_dir=tmp_path)
        async with LifespanManager(app) as manager:
            transport = ASGITransport(app=manager.app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                yield c


@pytest.mark.asyncio
async def test_get_market_calendar(client):
    mock_now = datetime(2026, 9, 24, 10, 30, tzinfo=IST)
    with patch("tradingbot.scanner.calendar.now_ist", return_value=mock_now):
        resp = await client.get("/api/market-calendar")
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
async def test_get_market_calendar_on_holiday(client):
    mock_now = datetime(2026, 1, 26, 10, 30, tzinfo=IST)
    with patch("tradingbot.scanner.calendar.now_ist", return_value=mock_now):
        resp = await client.get("/api/market-calendar")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "holiday"
    assert data["today_is_trading_day"] is False


@pytest.mark.asyncio
async def test_refresh_market_calendar(client):
    resp = await client.post("/api/market-calendar/refresh")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "holidays" in data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/rmashruwala/work/Personal/Projects/trading-bot && python -m pytest tests/api/test_calendar_routes.py -v`
Expected: FAIL — module `tradingbot.api.calendar_routes` does not exist

- [ ] **Step 3: Implement calendar routes**

Create `tradingbot/api/calendar_routes.py`:

```python
"""Market calendar routes — status, holidays, refresh."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter

from tradingbot.scanner.calendar import (
    calendar_coverage,
    clear_cache,
    get_holidays,
    is_trading_day,
    market_status,
    next_trading_session,
    now_ist,
)

router = APIRouter(prefix="/api")


def _calendar_response() -> dict:
    now = now_ist()
    today = now.date()
    status_info = market_status()
    session = next_trading_session()
    year = today.year
    holidays = get_holidays(year)
    first, last = calendar_coverage()

    upcoming = [
        h for h in holidays if h.date >= today
    ][:10]

    return {
        "status": status_info.status,
        "reason": status_info.reason,
        "holiday_name": status_info.holiday_name,
        "next_session": session.isoformat(),
        "today_is_trading_day": is_trading_day(today),
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
    clear_cache()
    return _calendar_response()
```

- [ ] **Step 4: Register router in app.py**

In `tradingbot/api/app.py`, add after the review_router import (around line 81):

```python
    from tradingbot.api.calendar_routes import router as calendar_router
```

And add after `app.include_router(review_router)` (around line 89):

```python
    app.include_router(calendar_router)
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/rmashruwala/work/Personal/Projects/trading-bot && python -m pytest tests/api/test_calendar_routes.py -v`
Expected: All pass

- [ ] **Step 6: Run full test suite for regression check**

Run: `cd /Users/rmashruwala/work/Personal/Projects/trading-bot && python -m pytest -x -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add tradingbot/api/calendar_routes.py tradingbot/api/app.py tests/api/test_calendar_routes.py
git commit -m "feat(api): add market calendar endpoints

GET /api/market-calendar returns current market status, next session,
upcoming holidays, and calendar coverage info.
POST /api/market-calendar/refresh clears the cached calendar data
and returns fresh results."
```

---

### Task 3: Frontend market status widget

**Files:**
- Modify: `web/src/types/index.ts` (add MarketCalendar type)
- Modify: `web/src/lib/api.ts` (add calendar API methods)
- Create: `web/src/components/dashboard/market-status.tsx`
- Modify: `web/src/app/page.tsx` (add widget to dashboard header)

**Interfaces:**
- Consumes: `GET /api/market-calendar`, `POST /api/market-calendar/refresh` from Task 2
- Produces: `<MarketStatus />` React component rendered at top of dashboard

- [ ] **Step 1: Add TypeScript type**

In `web/src/types/index.ts`, add at the end:

```typescript
export interface MarketHoliday {
  date: string;
  name: string;
}

export interface MarketCalendarResponse {
  status: "open" | "pre_market" | "post_market" | "closed" | "holiday";
  reason: string;
  holiday_name: string | null;
  next_session: string;
  today_is_trading_day: boolean;
  holidays: MarketHoliday[];
  total_holidays_this_year: number;
  coverage: { first: string; last: string };
  current_year_covered: boolean;
  data_year: number;
}
```

- [ ] **Step 2: Add API methods**

In `web/src/lib/api.ts`, add to the `api` object (before the closing `};`):

```typescript
  // Market Calendar
  getMarketCalendar: () => get<MarketCalendarResponse>("/api/market-calendar"),
  refreshMarketCalendar: () => post<MarketCalendarResponse>("/api/market-calendar/refresh"),
```

Also add the import at the top of the file — append `MarketCalendarResponse` to the existing import:

```typescript
import type {
  HealthStatus, ConfigResponse, Provider, PlanSummary, TradePlan,
  Trade, TradeStats, AnalysisStatus, ExecutionStatusResponse,
  KiteAuthStatus, AnalysisRun, Setup, DailyPlan, SyncStatus,
  TradeScorecard, PerformanceStatsData, GeneratePlanResponse,
  MarketCalendarResponse,
} from "@/types";
```

- [ ] **Step 3: Create the MarketStatus component**

Create `web/src/components/dashboard/market-status.tsx`:

```tsx
"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";

const STATUS_CONFIG: Record<string, { dot: string; label: string; color: string }> = {
  open: { dot: "bg-[#2da44e]", label: "Market Open", color: "text-[#2da44e]" },
  pre_market: { dot: "bg-[#d4a015] animate-pulse", label: "Pre-Market", color: "text-[#d4a015]" },
  post_market: { dot: "bg-[#d4a015]", label: "Post-Market", color: "text-[#d4a015]" },
  closed: { dot: "bg-[#f85149]", label: "Closed", color: "text-[#f85149]" },
  holiday: { dot: "bg-[#d4a015]", label: "Holiday", color: "text-[#d4a015]" },
};

function formatSessionTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffMs = d.getTime() - now.getTime();

  if (diffMs < 0) return "Now";

  const diffH = Math.floor(diffMs / 3_600_000);
  const diffM = Math.floor((diffMs % 3_600_000) / 60_000);

  const dateStr = d.toLocaleDateString("en-IN", { weekday: "short", month: "short", day: "numeric" });
  const timeStr = d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });

  if (diffH < 24) {
    const parts: string[] = [];
    if (diffH > 0) parts.push(`${diffH}h`);
    parts.push(`${diffM}m`);
    return `${dateStr} ${timeStr} (${parts.join(" ")})`;
  }

  return `${dateStr} ${timeStr}`;
}

export function MarketStatus() {
  const queryClient = useQueryClient();
  const [showHolidays, setShowHolidays] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["market-calendar"],
    queryFn: api.getMarketCalendar,
    refetchInterval: 60_000,
  });

  if (isLoading || !data) {
    return (
      <Card className="border-border/50 bg-card/80">
        <CardContent className="flex items-center gap-2 px-4 py-3">
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-[#d4a015] border-t-transparent" />
          <span className="text-xs text-muted-foreground">Loading market status…</span>
        </CardContent>
      </Card>
    );
  }

  const cfg = STATUS_CONFIG[data.status] ?? STATUS_CONFIG.closed;

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await api.refreshMarketCalendar();
      queryClient.invalidateQueries({ queryKey: ["market-calendar"] });
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <Card className="border-border/50 bg-card/80">
      <CardContent className="px-4 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            {/* Status badge */}
            <div className="flex items-center gap-2">
              <span className={`inline-flex h-2 w-2 rounded-full ${cfg.dot}`} />
              <span className={`text-sm font-medium ${cfg.color}`}>
                {data.status === "holiday" && data.holiday_name
                  ? `Holiday: ${data.holiday_name}`
                  : cfg.label}
              </span>
            </div>

            {/* Next session */}
            {data.status !== "open" && (
              <div className="flex items-center gap-2">
                <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Next</span>
                <span className="font-mono-nums text-xs text-foreground/80">
                  {formatSessionTime(data.next_session)}
                </span>
              </div>
            )}

            {/* Upcoming holidays toggle */}
            {data.holidays.length > 0 && (
              <button
                onClick={() => setShowHolidays(!showHolidays)}
                className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted-foreground/50 hover:text-muted-foreground/80 transition-colors cursor-pointer"
              >
                <span className={`transition-transform ${showHolidays ? "rotate-90" : ""}`}>▸</span>
                {data.holidays.length} upcoming
              </button>
            )}
          </div>

          <div className="flex items-center gap-2">
            {/* Stale data warning */}
            {!data.current_year_covered && (
              <span className="text-[10px] uppercase tracking-wider text-[#f85149]">
                Calendar data outdated
              </span>
            )}

            {/* Refresh button */}
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="rounded-md px-2 py-1 text-[10px] uppercase tracking-wider text-muted-foreground/50 hover:text-muted-foreground/80 hover:bg-[#161d26] transition-colors cursor-pointer disabled:opacity-50"
            >
              {refreshing ? "…" : "↻ Refresh"}
            </button>
          </div>
        </div>

        {/* Expandable holidays list */}
        {showHolidays && data.holidays.length > 0 && (
          <div className="mt-3 border-t border-border/30 pt-3">
            <div className="grid gap-1.5">
              {data.holidays.map((h) => (
                <div key={h.date} className="flex items-center justify-between text-xs">
                  <span className="text-foreground/70">{h.name}</span>
                  <span className="font-mono-nums text-muted-foreground/60">
                    {new Date(h.date + "T00:00:00").toLocaleDateString("en-IN", {
                      weekday: "short",
                      month: "short",
                      day: "numeric",
                    })}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 4: Wire widget into dashboard**

In `web/src/app/page.tsx`, add the import and component:

Add import:
```typescript
import { MarketStatus } from "@/components/dashboard/market-status";
```

Add `<MarketStatus />` right after the `<h1>` tag and before the `StatCards`:

```tsx
      <MarketStatus />
```

The full return block becomes:

```tsx
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Dashboard</h1>

      <MarketStatus />

      {stats && <StatCards stats={stats} />}

      <div className="grid grid-cols-2 gap-3">
        <EquityCurve trades={trades ?? []} />
        <DailyPnlChart trades={trades ?? []} />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <WinRateDonut winRate={stats?.win_rate ?? 0} tradeCount={stats?.trade_count ?? 0} />
        <LastAnalysis />
      </div>
    </div>
```

- [ ] **Step 5: Type check**

Run: `cd /Users/rmashruwala/work/Personal/Projects/trading-bot/web && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 6: Start dev server and verify visually**

Run: `cd /Users/rmashruwala/work/Personal/Projects/trading-bot/web && npm run dev`

Open `http://localhost:3000` in browser. Verify:
- Market status badge visible at top of dashboard (below title, above stat cards)
- Status shows correct state for current time
- "Upcoming holidays" toggle expands to show holiday list
- "Refresh" button works (spins briefly, reloads data)
- Colors match DESIGN.md: green for open, gold for pre/post/holiday, red for closed
- Font sizes: 10px uppercase tracked labels, 13px body, mono for times
- No shadows, card uses surface/border pattern

- [ ] **Step 7: Commit**

```bash
git add web/src/types/index.ts web/src/lib/api.ts web/src/components/dashboard/market-status.tsx web/src/app/page.tsx
git commit -m "feat(web): add market status widget to dashboard

Shows live market status (open/closed/holiday), next session with
countdown, and expandable upcoming holidays list. Refresh button
clears cached calendar data. Auto-refreshes every 60 seconds.
Warns when calendar data doesn't cover the current year."
```
