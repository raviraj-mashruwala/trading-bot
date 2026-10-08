"""Tests for scheduler trigger logic."""

from datetime import date, time

from tradingbot.scheduler import should_start_execution, should_sync, should_review


TODAY = date(2026, 10, 9)
YESTERDAY = date(2026, 10, 8)


class TestShouldStartExecution:
    def test_fires_at_9am_on_trading_day(self):
        assert should_start_execution(time(9, 0), TODAY, None, is_trading_day=True)

    def test_fires_at_9_03_within_window(self):
        assert should_start_execution(time(9, 3), TODAY, None, is_trading_day=True)

    def test_does_not_fire_at_9_05_past_window(self):
        assert not should_start_execution(time(9, 5), TODAY, None, is_trading_day=True)

    def test_does_not_fire_before_9am(self):
        assert not should_start_execution(time(8, 59), TODAY, None, is_trading_day=True)

    def test_does_not_fire_on_non_trading_day(self):
        assert not should_start_execution(time(9, 0), TODAY, None, is_trading_day=False)

    def test_does_not_fire_if_already_ran_today(self):
        assert not should_start_execution(time(9, 0), TODAY, TODAY, is_trading_day=True)

    def test_fires_if_last_ran_yesterday(self):
        assert should_start_execution(time(9, 0), TODAY, YESTERDAY, is_trading_day=True)


class TestShouldSync:
    def test_fires_at_4pm_on_trading_day(self):
        assert should_sync(time(16, 0), TODAY, None, is_trading_day=True)

    def test_fires_at_4_03_within_window(self):
        assert should_sync(time(16, 3), TODAY, None, is_trading_day=True)

    def test_does_not_fire_at_4_05_past_window(self):
        assert not should_sync(time(16, 5), TODAY, None, is_trading_day=True)

    def test_does_not_fire_before_4pm(self):
        assert not should_sync(time(15, 59), TODAY, None, is_trading_day=True)

    def test_does_not_fire_on_non_trading_day(self):
        assert not should_sync(time(16, 0), TODAY, None, is_trading_day=False)

    def test_does_not_fire_if_already_ran_today(self):
        assert not should_sync(time(16, 0), TODAY, TODAY, is_trading_day=True)


class TestShouldReview:
    def test_fires_at_8_30pm_on_trading_day(self):
        assert should_review(time(20, 30), TODAY, None, is_trading_day=True)

    def test_fires_at_8_33pm_within_window(self):
        assert should_review(time(20, 33), TODAY, None, is_trading_day=True)

    def test_does_not_fire_at_8_35pm_past_window(self):
        assert not should_review(time(20, 35), TODAY, None, is_trading_day=True)

    def test_does_not_fire_before_8_30pm(self):
        assert not should_review(time(20, 29), TODAY, None, is_trading_day=True)

    def test_does_not_fire_on_non_trading_day(self):
        assert not should_review(time(20, 30), TODAY, None, is_trading_day=False)

    def test_does_not_fire_if_already_ran_today(self):
        assert not should_review(time(20, 30), TODAY, TODAY, is_trading_day=True)
