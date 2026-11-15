"""Tests for scheduler trigger logic."""

from datetime import date, time

from tradingbot import scheduler
from tradingbot.scheduler import should_start_execution


# Oct 9 2026 = Thursday, Oct 10 = Friday, Oct 11 = Saturday, Oct 12 = Sunday, Oct 13 = Monday
THU = date(2026, 10, 9)
FRI = date(2026, 10, 10)
SAT = date(2026, 10, 11)
SUN = date(2026, 10, 12)
MON = date(2026, 10, 13)
WED = date(2026, 10, 8)


class TestShouldStartExecution:
    def test_fires_at_9am_on_trading_day(self):
        assert should_start_execution(time(9, 0), THU, None, is_trading_day=True)

    def test_fires_within_window(self):
        assert should_start_execution(time(9, 3), THU, None, is_trading_day=True)

    def test_does_not_fire_past_window(self):
        assert not should_start_execution(time(9, 5), THU, None, is_trading_day=True)

    def test_does_not_fire_before(self):
        assert not should_start_execution(time(8, 59), THU, None, is_trading_day=True)

    def test_does_not_fire_on_non_trading_day(self):
        assert not should_start_execution(time(9, 0), SAT, None, is_trading_day=False)

    def test_does_not_fire_if_already_ran_today(self):
        assert not should_start_execution(time(9, 0), THU, THU, is_trading_day=True)

    def test_fires_if_last_ran_yesterday(self):
        assert should_start_execution(time(9, 0), THU, WED, is_trading_day=True)


class TestOnlyExecutionIsScheduled:
    """Sync, analysis and review are manual (scripts/analysis/*.sh and the review API)."""

    def test_no_sync_analysis_or_review_triggers_exist(self):
        for name in ("should_sync", "should_run_analysis", "should_review", "previous_day"):
            assert not hasattr(scheduler, name), name
