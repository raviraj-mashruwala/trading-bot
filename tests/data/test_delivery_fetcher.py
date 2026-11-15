"""Tests for NSE delivery percentage bhav copy fetcher."""

from __future__ import annotations

import pytest
import httpx
from datetime import date

from tradingbot.data.delivery_fetcher import fetch_delivery_pct, _date_str


# ── date string helper ────────────────────────────────────────────────────────

def test_date_str_format():
    # NSE names the file sec_bhavdata_full_DDMMYYYY.csv (numeric month), not 29SEP2026.
    assert _date_str(date(2026, 9, 29)) == "29092026"
    assert _date_str(date(2026, 1, 5)) == "05012026"
    assert _date_str(date(2026, 12, 31)) == "31122026"


# ── Successful fetch ──────────────────────────────────────────────────────────

_SAMPLE_CSV = (
    "SYMBOL,SERIES,DATE1,PREV_CLOSE,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,"
    "LAST_PRICE,CLOSE_PRICE,AVG_PRICE,TTL_TRD_QNTY,TURNOVER_LACS,"
    "NO_OF_TRADES,DELIV_QTY,DELIV_PER\n"
    "RELIANCE,EQ,29-SEP-2026,2800,2810,2850,2800,2840,2838,2830,"
    "1000000,283000,5000,650000,65.00\n"
    "TCS,EQ,29-SEP-2026,3500,3510,3560,3490,3540,3538,3530,"
    "500000,176500,3000,200000,40.00\n"
    "NIFTY26SEP,BE,29-SEP-2026,100,101,102,99,101,101,101,"
    "1000,101,50,800,80.00\n"  # non-EQ series — should be filtered
)


def _make_client(csv_text: str, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=csv_text)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_returns_symbol_delivery_pct_dict():
    client = _make_client(_SAMPLE_CSV)
    result = fetch_delivery_pct(date(2026, 9, 29), http_client=client)
    assert "RELIANCE" in result
    assert result["RELIANCE"] == pytest.approx(65.0)
    assert result["TCS"] == pytest.approx(40.0)


def test_filters_non_eq_series():
    client = _make_client(_SAMPLE_CSV)
    result = fetch_delivery_pct(date(2026, 9, 29), http_client=client)
    assert "NIFTY26SEP" not in result


# ── Network failure ───────────────────────────────────────────────────────────

def test_returns_empty_dict_on_404():
    client = _make_client("", status=404)
    result = fetch_delivery_pct(date(2026, 9, 29), http_client=client)
    assert result == {}


def test_returns_empty_dict_on_malformed_csv():
    client = _make_client("not,a,valid,bhav,csv\n1,2,3,4,5\n")
    result = fetch_delivery_pct(date(2026, 9, 29), http_client=client)
    assert result == {}


def test_skips_weekends():
    """Saturday/Sunday dates must be skipped; tries prior weekday (Friday)."""
    results_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        results_seen.append(str(request.url))
        if "25092026" in str(request.url):  # Friday before the weekend
            return httpx.Response(200, text=_SAMPLE_CSV)
        return httpx.Response(404, text="")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    # 2026-09-27 is a Sunday and 09-26 a Saturday: both skipped, so it tries Friday 09-25
    result = fetch_delivery_pct(date(2026, 9, 27), http_client=client)
    assert "RELIANCE" in result
    assert any("25092026" in u for u in results_seen)


# ── Which URLs are requested ──────────────────────────────────────────────────

def _recording_client(available: set[str]):
    """404 for everything except file names in `available`; records requested names."""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("_", 1)[-1].removesuffix(".csv")
        requested.append(name)
        if name in available:
            return httpx.Response(200, text=_SAMPLE_CSV)
        return httpx.Response(404, text="")

    return httpx.Client(transport=httpx.MockTransport(handler)), requested


def test_url_uses_the_numeric_date():
    client, requested = _recording_client({"29092026"})

    result = fetch_delivery_pct(date(2026, 9, 29), http_client=client)

    assert requested == ["29092026"]
    assert "RELIANCE" in result


def test_walks_back_over_trading_days_not_calendar_days():
    # Monday target; only Friday's file exists (Sat and Sun are skipped).
    client, requested = _recording_client({"25092026"})

    result = fetch_delivery_pct(date(2026, 9, 28), http_client=client, today=date(2026, 9, 28))

    assert requested == ["28092026", "25092026"]
    assert "RELIANCE" in result


def test_never_requests_a_date_after_today():
    # Analysing for Monday 11-02 on Friday evening: the newest file that can exist is today's.
    client, requested = _recording_client({"30102026"})

    result = fetch_delivery_pct(date(2026, 11, 2), http_client=client, today=date(2026, 10, 30))

    assert requested == ["30102026"]
    assert "RELIANCE" in result


def test_lookback_covers_a_long_weekend():
    # Tuesday target; the last file is Thursday's (Fri holiday, then a weekend, then Mon holiday).
    client, requested = _recording_client({"24092026"})

    result = fetch_delivery_pct(date(2026, 9, 29), http_client=client, today=date(2026, 9, 29))

    assert "24092026" in requested
    assert "RELIANCE" in result


def test_returns_empty_when_nothing_is_published_in_the_window():
    client, requested = _recording_client(set())

    assert fetch_delivery_pct(date(2026, 9, 29), http_client=client, today=date(2026, 9, 29)) == {}
    assert len(requested) >= 4  # it really looked back, not just once
