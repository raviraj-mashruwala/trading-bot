import httpx
import pytest

from tradingbot.core.models import MarketRegime
from tradingbot.scanner.market_context import MarketContextFetcher

FII_DII_PAYLOAD = [
    {"category": "FII/FPI *", "buyValue": "12000.00", "sellValue": "9700.00", "netValue": "2300.00"},
    {"category": "DII **", "buyValue": "7000.00", "sellValue": "7800.00", "netValue": "-800.00"},
]


def make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_returns_a_populated_context():
    def handler(request):
        if "fiidiiTradeReact" in str(request.url):
            return httpx.Response(200, json=FII_DII_PAYLOAD)
        return httpx.Response(200, json={})

    fetcher = MarketContextFetcher(http_client=make_client(handler))

    context = fetcher.fetch()

    assert context.fii_net_cr == pytest.approx(2300.0)
    assert context.dii_net_cr == pytest.approx(-800.0)
    assert isinstance(context.regime, MarketRegime)
    assert isinstance(context.sector_leaders, list)


def test_fii_dii_default_to_zero_when_the_nse_call_fails():
    def handler(request):
        return httpx.Response(503, text="service unavailable")

    fetcher = MarketContextFetcher(http_client=make_client(handler))

    context = fetcher.fetch()

    assert context.fii_net_cr == pytest.approx(0.0)
    assert context.dii_net_cr == pytest.approx(0.0)


def test_high_vix_classifies_the_regime_as_volatile():
    fetcher = MarketContextFetcher(http_client=make_client(lambda request: httpx.Response(200, json=[])))

    assert fetcher.classify_regime(vix=28.0, nifty_above_sma20=True, nifty_above_sma50=True) is MarketRegime.VOLATILE


def test_low_vix_classifies_the_regime_as_low_vol():
    fetcher = MarketContextFetcher(http_client=make_client(lambda request: httpx.Response(200, json=[])))

    assert fetcher.classify_regime(vix=9.0, nifty_above_sma20=True, nifty_above_sma50=True) is MarketRegime.LOW_VOL_SQUEEZE


def test_aligned_moving_averages_classify_the_regime_as_trending():
    fetcher = MarketContextFetcher(http_client=make_client(lambda request: httpx.Response(200, json=[])))

    assert fetcher.classify_regime(vix=15.0, nifty_above_sma20=True, nifty_above_sma50=True) is MarketRegime.TRENDING_UP


def test_conflicting_moving_averages_classify_the_regime_as_ranging():
    fetcher = MarketContextFetcher(http_client=make_client(lambda request: httpx.Response(200, json=[])))

    assert fetcher.classify_regime(vix=15.0, nifty_above_sma20=True, nifty_above_sma50=False) is MarketRegime.RANGE_BOUND


# ── CandleStore-based index fetch tests ──────────────────────────────────────

import numpy as np
import pandas as pd
from unittest.mock import MagicMock
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _make_daily_df(n=60, last_close=24000.0, trend="up"):
    """Build OHLCV daily df. trend='up' means close > SMA20 > SMA50."""
    if trend == "up":
        closes = np.linspace(last_close * 0.85, last_close, n)
    else:
        closes = np.linspace(last_close, last_close * 0.85, n)
    return pd.DataFrame({
        "open": closes - 10, "high": closes + 20,
        "low": closes - 20, "close": closes,
        "volume": [1_000_000] * n,
    })


def test_fetch_index_trend_reads_from_candle_store():
    """_fetch_index_trend must use candle_store.read, not yfinance."""
    candle_store = MagicMock()
    candle_store.read.return_value = _make_daily_df(60, last_close=24000.0, trend="up")

    fetcher = MarketContextFetcher(
        http_client=make_client(lambda r: httpx.Response(200, json=[])),
        candle_store=candle_store,
    )
    level, above20, above50 = fetcher._fetch_index_trend("NIFTY 50")

    assert level > 0
    assert candle_store.read.called
    # uptrend df → close > SMA20 > SMA50
    assert above20 is True
    assert above50 is True


def test_fetch_index_trend_returns_neutral_when_no_candle_store():
    """No candle_store → returns (0.0, False, False) gracefully."""
    fetcher = MarketContextFetcher(
        http_client=make_client(lambda r: httpx.Response(200, json=[])),
    )
    level, above20, above50 = fetcher._fetch_index_trend("NIFTY 50")
    assert level == 0.0
    assert above20 is False
    assert above50 is False


def test_fetch_vix_reads_from_candle_store():
    """_fetch_vix must use candle_store, return last close of INDIA VIX."""
    candle_store = MagicMock()
    vix_df = pd.DataFrame({
        "open": [14.5], "high": [15.0], "low": [14.0],
        "close": [14.8], "volume": [0],
    })
    candle_store.read.return_value = vix_df

    fetcher = MarketContextFetcher(
        http_client=make_client(lambda r: httpx.Response(200, json=[])),
        candle_store=candle_store,
    )
    vix = fetcher._fetch_vix()

    assert vix == pytest.approx(14.8)


def test_fetch_vix_returns_default_when_no_candle_store():
    """No candle_store → returns 15.0 (mid-range neutral default)."""
    fetcher = MarketContextFetcher(
        http_client=make_client(lambda r: httpx.Response(200, json=[])),
    )
    assert fetcher._fetch_vix() == pytest.approx(15.0)


def test_fetch_populates_nifty_level_from_candle_store():
    """Full fetch() must populate nifty_level from CandleStore, not yfinance."""
    nifty_df = _make_daily_df(60, last_close=24500.0, trend="up")
    vix_df = pd.DataFrame({"open": [13.0], "high": [13.5], "low": [12.5],
                            "close": [13.0], "volume": [0]})

    def fake_read(symbol, *args, **kwargs):
        if symbol == "INDIA VIX":
            return vix_df
        return nifty_df

    candle_store = MagicMock()
    candle_store.read.side_effect = fake_read

    fetcher = MarketContextFetcher(
        http_client=make_client(lambda r: httpx.Response(200, json=[])),
        candle_store=candle_store,
    )
    ctx = fetcher.fetch()
    assert ctx.nifty_level == pytest.approx(24500.0, rel=0.01)
    assert ctx.india_vix == pytest.approx(13.0)
