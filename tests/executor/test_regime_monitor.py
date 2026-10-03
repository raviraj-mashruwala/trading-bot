"""Tests for RegimeMonitor — live intraday regime detection."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _noul(v):
    return SimpleNamespace(noul=v)


def _choice(v, c=0.8):
    return SimpleNamespace(choice=v, confidence=c)


def _mock_jev(answers):
    client = MagicMock()
    client.available = True
    client.evaluate = MagicMock(return_value=answers)
    return client


def test_should_check_respects_interval():
    from tradingbot.executor.regime_monitor import RegimeMonitor
    jev = _mock_jev(None)
    monitor = RegimeMonitor(jev, check_interval_seconds=300)
    now = datetime(2026, 10, 3, 10, 0, 0)
    assert monitor.should_check(now) is True
    monitor._last_check = now
    assert monitor.should_check(now + timedelta(seconds=100)) is False
    assert monitor.should_check(now + timedelta(seconds=301)) is True


def test_check_detects_regime_change():
    from tradingbot.executor.regime_monitor import RegimeMonitor
    answers = {
        "regime_changed": _noul(0.85),
        "new_regime": _choice("volatile", 0.78),
    }
    jev = _mock_jev(answers)
    monitor = RegimeMonitor(jev)
    result = monitor.check({"vix": 22.0}, "trending_up")
    assert result.changed is True
    assert result.new_regime == "volatile"
    assert result.confidence > 0.5


def test_check_no_change():
    from tradingbot.executor.regime_monitor import RegimeMonitor
    answers = {
        "regime_changed": _noul(0.20),
        "new_regime": _choice("trending_up", 0.9),
    }
    jev = _mock_jev(answers)
    monitor = RegimeMonitor(jev)
    result = monitor.check({"vix": 13.0}, "trending_up")
    assert result.changed is False
    assert result.new_regime is None


def test_check_jev_fails_returns_no_change():
    from tradingbot.executor.regime_monitor import RegimeMonitor
    jev = _mock_jev(None)
    monitor = RegimeMonitor(jev)
    result = monitor.check({"vix": 13.0}, "trending_up")
    assert result.changed is False
