"""Scheduled job triggers. Pure logic — no async, no side effects.

Each check function returns True when a job should fire, given the current
time and the set of dates already handled. The caller (app.py) runs the
actual async work.
"""

from __future__ import annotations

from datetime import date, time


def should_start_execution(now_time: time, today: date, last_date: date | None, is_trading_day: bool) -> bool:
    if last_date == today:
        return False
    if not is_trading_day:
        return False
    return now_time >= time(9, 0) and now_time < time(9, 5)


def should_sync(now_time: time, today: date, last_date: date | None, is_trading_day: bool) -> bool:
    if last_date == today:
        return False
    if not is_trading_day:
        return False
    return now_time >= time(16, 0) and now_time < time(16, 5)


def should_review(now_time: time, today: date, last_date: date | None, is_trading_day: bool) -> bool:
    if last_date == today:
        return False
    if not is_trading_day:
        return False
    return now_time >= time(20, 30) and now_time < time(20, 35)
