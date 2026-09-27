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
