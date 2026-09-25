from datetime import date

import pytest

from tradingbot.core.config import ScannerConfig
from tradingbot.core.models import MarketContext, MarketRegime, ShortlistedStock, Stock, StrategyName
from tradingbot.scanner.calendar import NotATradingDayError
from tradingbot.scanner.scanner import Scanner


class StubFetcher:
    def __init__(self, stocks):
        self.stocks = stocks
        self.universe_calls = 0

    def fetch_universe(self):
        self.universe_calls += 1
        return [stock.symbol for stock in self.stocks]

    def fetch_stock_metrics(self, symbols):
        return [stock for stock in self.stocks if stock.symbol in set(symbols)]


class StubContextFetcher:
    def __init__(self):
        self.calls = 0

    def fetch(self):
        self.calls += 1
        return MarketContext(
            nifty_level=25400.0,
            nifty_trend="bullish",
            banknifty_trend="bullish",
            india_vix=12.5,
            fii_net_cr=2300.0,
            dii_net_cr=-800.0,
            global_cues="US flat",
            sector_leaders=["IT"],
            sector_laggards=["FMCG"],
            regime=MarketRegime.TRENDING,
        )


class StubAnalyzer:
    def __init__(self, picks):
        self.picks = picks
        self.seen_stocks = None

    async def shortlist(self, stocks, context):
        self.seen_stocks = stocks
        return self.picks


def make_config() -> ScannerConfig:
    return ScannerConfig(
        min_volume=500000,
        min_price=50.0,
        max_price=5000.0,
        min_market_cap_cr=5000.0,
        min_atr_pct=0.5,
        max_stocks_to_llm=100,
        llm_pick_count=15,
    )


def make_stock(symbol, avg_volume=1_000_000.0) -> Stock:
    return Stock(
        symbol=symbol,
        exchange="NSE",
        last_price=100.0,
        avg_volume=avg_volume,
        market_cap_cr=50000.0,
        atr_pct=1.2,
        sector="IT",
    )


def make_pick(symbol) -> ShortlistedStock:
    return ShortlistedStock(
        symbol=symbol,
        reasoning="Looks good.",
        suggested_strategy=StrategyName.BREAKOUT,
        direction_bias="long",
        key_levels=[100.0],
    )


async def test_scan_returns_the_shortlist_and_the_context():
    fetcher = StubFetcher([make_stock("RELIANCE"), make_stock("TCS")])
    context_fetcher = StubContextFetcher()
    analyzer = StubAnalyzer([make_pick("RELIANCE")])
    scanner = Scanner(fetcher, context_fetcher, analyzer, make_config())

    result = await scanner.scan(date(2026, 9, 24))

    assert result.trade_date == date(2026, 9, 24)
    assert [pick.symbol for pick in result.shortlist] == ["RELIANCE"]
    assert result.context.nifty_level == pytest.approx(25400.0)
    assert context_fetcher.calls == 1


async def test_scan_only_sends_filtered_stocks_to_the_analyzer():
    fetcher = StubFetcher([make_stock("RELIANCE"), make_stock("ILLIQUID", avg_volume=10.0)])
    analyzer = StubAnalyzer([])
    scanner = Scanner(fetcher, StubContextFetcher(), analyzer, make_config())

    await scanner.scan(date(2026, 9, 24))

    assert [stock.symbol for stock in analyzer.seen_stocks] == ["RELIANCE"]


async def test_scan_records_why_stocks_were_rejected():
    fetcher = StubFetcher([make_stock("RELIANCE"), make_stock("ILLIQUID", avg_volume=10.0)])
    scanner = Scanner(fetcher, StubContextFetcher(), StubAnalyzer([]), make_config())

    result = await scanner.scan(date(2026, 9, 24))

    assert result.filter_result.rejected == {"volume": 1}


async def test_scan_refuses_a_saturday():
    scanner = Scanner(StubFetcher([]), StubContextFetcher(), StubAnalyzer([]), make_config())

    with pytest.raises(NotATradingDayError, match="2026-09-26"):
        await scanner.scan(date(2026, 9, 26))


async def test_scan_refuses_an_nse_holiday():
    scanner = Scanner(StubFetcher([]), StubContextFetcher(), StubAnalyzer([]), make_config())

    with pytest.raises(NotATradingDayError, match="2026-08-15"):
        await scanner.scan(date(2026, 8, 15))


async def test_scan_does_no_network_work_on_a_non_trading_day():
    fetcher = StubFetcher([make_stock("RELIANCE")])
    context_fetcher = StubContextFetcher()
    scanner = Scanner(fetcher, context_fetcher, StubAnalyzer([]), make_config())

    with pytest.raises(NotATradingDayError):
        await scanner.scan(date(2026, 9, 27))

    assert fetcher.universe_calls == 0
    assert context_fetcher.calls == 0
