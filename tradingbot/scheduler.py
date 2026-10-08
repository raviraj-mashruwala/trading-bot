"""Scheduled job triggers. Pure logic — no async, no side effects.

Each check function returns True when a job should fire, given the current
time and the set of dates already handled. The caller (app.py) runs the
actual async work.

Schedule (all IST, trading days only):
  09:00  Auto-start execution (for today's plan)
  16:00  Daily data sync
  16:30  Run analysis (generates plan for NEXT trading day)
  00:00  Nightly review (reviews the PREVIOUS trading day)
"""

from __future__ import annotations

from datetime import date, time, timedelta


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


def should_run_analysis(now_time: time, today: date, last_date: date | None, is_trading_day: bool) -> bool:
    """Fire at 4:30 PM on trading days. Generates plan for next trading day."""
    if last_date == today:
        return False
    if not is_trading_day:
        return False
    return now_time >= time(16, 30) and now_time < time(16, 35)


def should_review(now_time: time, today: date, last_date: date | None, prev_was_trading_day: bool) -> bool:
    """Fire at midnight. Reviews the previous calendar day IF it was a trading day.

    On Monday 00:00 → reviews Friday. On Tuesday 00:00 → reviews Monday.
    On Saturday 00:00 → reviews Friday. On Sunday 00:00 → skips (Saturday wasn't trading).
    """
    if last_date == today:
        return False
    if not prev_was_trading_day:
        return False
    return now_time >= time(0, 0) and now_time < time(0, 5)


def previous_day(today: date) -> date:
    return today - timedelta(days=1)
