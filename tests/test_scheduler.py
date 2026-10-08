"""Tests for scheduler trigger logic."""

from datetime import date, time

from tradingbot.scheduler import (
    should_start_execution, should_sync, should_run_analysis,
    should_review, previous_day,
)


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


class TestShouldSync:
    def test_fires_at_4pm(self):
        assert should_sync(time(16, 0), THU, None, is_trading_day=True)

    def test_fires_within_window(self):
        assert should_sync(time(16, 3), THU, None, is_trading_day=True)

    def test_does_not_fire_past_window(self):
        assert not should_sync(time(16, 5), THU, None, is_trading_day=True)

    def test_does_not_fire_on_non_trading_day(self):
        assert not should_sync(time(16, 0), SAT, None, is_trading_day=False)

    def test_does_not_fire_if_already_ran(self):
        assert not should_sync(time(16, 0), THU, THU, is_trading_day=True)


class TestShouldRunAnalysis:
    def test_fires_at_4_30pm_on_trading_day(self):
        assert should_run_analysis(time(16, 30), THU, None, is_trading_day=True)

    def test_fires_within_window(self):
        assert should_run_analysis(time(16, 33), THU, None, is_trading_day=True)

    def test_does_not_fire_past_window(self):
        assert not should_run_analysis(time(16, 35), THU, None, is_trading_day=True)

    def test_does_not_fire_before_window(self):
        assert not should_run_analysis(time(16, 29), THU, None, is_trading_day=True)

    def test_does_not_fire_on_non_trading_day(self):
        """Friday analysis generates Monday plan. Saturday/Sunday should NOT trigger."""
        assert not should_run_analysis(time(16, 30), SAT, None, is_trading_day=False)

    def test_fires_on_friday(self):
        """Friday 4:30 PM should fire — generates plan for Monday."""
        assert should_run_analysis(time(16, 30), FRI, None, is_trading_day=True)

    def test_does_not_fire_if_already_ran_today(self):
        assert not should_run_analysis(time(16, 30), THU, THU, is_trading_day=True)


class TestShouldReview:
    def test_fires_at_midnight(self):
        """Thursday midnight reviews Wednesday's trades."""
        assert should_review(time(0, 0), THU, None, prev_was_trading_day=True)

    def test_fires_within_window(self):
        assert should_review(time(0, 3), THU, None, prev_was_trading_day=True)

    def test_does_not_fire_past_window(self):
        assert not should_review(time(0, 5), THU, None, prev_was_trading_day=True)

    def test_does_not_fire_if_previous_day_not_trading(self):
        """Sunday midnight — Saturday wasn't a trading day, skip."""
        assert not should_review(time(0, 0), SUN, None, prev_was_trading_day=False)

    def test_fires_on_saturday_midnight(self):
        """Saturday midnight — Friday WAS a trading day, review Friday."""
        assert should_review(time(0, 0), SAT, None, prev_was_trading_day=True)

    def test_fires_on_monday_midnight(self):
        """Monday midnight — but Sunday wasn't trading, so skip.
        Friday's review should have fired Saturday midnight."""
        assert not should_review(time(0, 0), MON, None, prev_was_trading_day=False)

    def test_does_not_fire_if_already_ran_today(self):
        assert not should_review(time(0, 0), THU, THU, prev_was_trading_day=True)

    def test_does_not_fire_at_old_time(self):
        """Old 8:30 PM time should NOT trigger review."""
        assert not should_review(time(20, 30), THU, None, prev_was_trading_day=True)


class TestPreviousDay:
    def test_thursday_prev_is_wednesday(self):
        assert previous_day(THU) == WED

    def test_monday_prev_is_sunday(self):
        assert previous_day(MON) == SUN

    def test_saturday_prev_is_friday(self):
        assert previous_day(SAT) == FRI
