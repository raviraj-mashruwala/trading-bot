"""Scheduled job triggers. Pure logic: no async, no side effects.

Only execution is scheduled. Data sync, analysis and the nightly review are
manual (scripts/analysis/*.sh and the review API), so an idle server never
starts work, or LLM spend, on its own.

Schedule (IST, trading days only):
  09:00  Auto-start execution (for today's plan)
"""

from __future__ import annotations

from datetime import date, time


def should_start_execution(now_time: time, today: date, last_date: date | None, is_trading_day: bool) -> bool:
    if last_date == today:
        return False
    if not is_trading_day:
        return False
    return now_time >= time(9, 0) and now_time < time(9, 5)
