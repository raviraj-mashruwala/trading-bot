"""Tests for NewsScreener — Jev-based headline analysis."""

from __future__ import annotations

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


def _headlines():
    return [
        {"title": "RBI cuts repo rate by 25 bps", "source": "ET", "time": "08:30"},
        {"title": "Nifty opens flat amid global cues", "source": "MC", "time": "09:15"},
        {"title": "HDFC Bank Q2 results beat estimates", "source": "BS", "time": "09:20"},
    ]


def _screen_answers(market_moving=0.85, sentiment="bullish", urgency=0.3):
    return {
        "market_moving": _noul(market_moving),
        "sentiment_shift": _choice(sentiment, 0.82),
        "urgency": _noul(urgency),
    }


def test_detects_market_moving_headlines():
    from tradingbot.executor.news_screener import NewsScreener
    jev = _mock_jev(_screen_answers(market_moving=0.9))
    screener = NewsScreener(jev)
    result = screener.screen(_headlines())
    assert result.market_moving > 0.8
    assert result.sentiment == "bullish"


def test_detects_urgent_headlines():
    from tradingbot.executor.news_screener import NewsScreener
    jev = _mock_jev(_screen_answers(urgency=0.9))
    screener = NewsScreener(jev)
    result = screener.screen(_headlines())
    assert result.urgent is True


def test_not_urgent_when_low():
    from tradingbot.executor.news_screener import NewsScreener
    jev = _mock_jev(_screen_answers(urgency=0.2))
    screener = NewsScreener(jev)
    result = screener.screen(_headlines())
    assert result.urgent is False


def test_bearish_sentiment():
    from tradingbot.executor.news_screener import NewsScreener
    jev = _mock_jev(_screen_answers(sentiment="bearish"))
    screener = NewsScreener(jev)
    result = screener.screen(_headlines())
    assert result.sentiment == "bearish"


def test_jev_fails_returns_neutral():
    from tradingbot.executor.news_screener import NewsScreener
    jev = _mock_jev(None)
    screener = NewsScreener(jev)
    result = screener.screen(_headlines())
    assert result.sentiment == "neutral"
    assert result.market_moving == 0.0
    assert result.urgent is False


def test_empty_headlines_returns_neutral():
    from tradingbot.executor.news_screener import NewsScreener
    jev = _mock_jev(_screen_answers())
    screener = NewsScreener(jev)
    result = screener.screen([])
    assert result.sentiment == "neutral"
    assert result.headlines_checked == 0
    jev.evaluate.assert_not_called()


def test_should_check_respects_interval():
    from tradingbot.executor.news_screener import NewsScreener
    from datetime import datetime, timedelta
    jev = _mock_jev(None)
    screener = NewsScreener(jev, check_interval_seconds=60)
    now = datetime(2026, 10, 3, 10, 0, 0)
    assert screener.should_check(now) is True
    screener._last_check = now
    assert screener.should_check(now + timedelta(seconds=30)) is False
    assert screener.should_check(now + timedelta(seconds=61)) is True
