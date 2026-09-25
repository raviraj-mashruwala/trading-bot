"""Tests for NseLiveFetcher — mocked, no real network calls."""

from unittest.mock import MagicMock, patch

import pytest

from tradingbot.scanner.nse_live import NseFetchError, NseLiveFetcher


@pytest.fixture
def fetcher():
    return NseLiveFetcher()


def _make_session(ltp=2480.0):
    """Build a mock session that behaves like requests.Session."""
    session = MagicMock()
    session.headers = {}
    session.cookies = {"nseappid": "abc123"}

    homepage_resp = MagicMock()
    homepage_resp.raise_for_status = MagicMock()

    quote_resp = MagicMock()
    quote_resp.status_code = 200
    quote_resp.raise_for_status = MagicMock()
    quote_resp.json.return_value = {"priceInfo": {"lastPrice": ltp}}

    def get_side_effect(url, **kw):
        if "api" in url:
            return quote_resp
        return homepage_resp

    session.get.side_effect = get_side_effect
    return session


def test_get_ltp_returns_price(fetcher):
    session = _make_session(2480.0)
    with patch("tradingbot.scanner.nse_live.requests.Session", return_value=session):
        price = fetcher.get_ltp("RELIANCE")
    assert price == 2480.0


def test_get_ltp_retries_on_403(fetcher):
    session = _make_session(2500.0)
    call_count = {"n": 0}

    def get_side_effect(url, **kw):
        if "api" not in url:
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            return resp
        call_count["n"] += 1
        if call_count["n"] == 1:
            resp = MagicMock()
            resp.status_code = 403
            return resp
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"priceInfo": {"lastPrice": 2500.0}}
        return resp

    session.get.side_effect = get_side_effect
    with patch("tradingbot.scanner.nse_live.requests.Session", return_value=session):
        price = fetcher.get_ltp("RELIANCE")
    assert price == 2500.0


def test_get_ltp_raises_on_missing_price(fetcher):
    session = _make_session()
    quote_resp = MagicMock()
    quote_resp.status_code = 200
    quote_resp.raise_for_status = MagicMock()
    quote_resp.json.return_value = {"priceInfo": {}}

    def get_side_effect(url, **kw):
        if "api" in url:
            return quote_resp
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        return resp

    session.get.side_effect = get_side_effect
    with patch("tradingbot.scanner.nse_live.requests.Session", return_value=session):
        with pytest.raises(NseFetchError, match="no lastPrice"):
            fetcher.get_ltp("BADSTOCK")


def test_session_reused_within_timeout(fetcher):
    session = _make_session(100.0)
    with patch("tradingbot.scanner.nse_live.requests.Session", return_value=session) as mock_cls:
        fetcher.get_ltp("TCS")
        fetcher.get_ltp("INFY")
    assert mock_cls.call_count == 1
