import pandas as pd
import pytest

from tradingbot.scanner.data_fetcher import DataFetcher, DataFetchError


class FakeTicker:
    def __init__(self, info, history):
        self.info = info
        self._history = history

    def history(self, period=None, interval=None):
        return self._history


def make_history(rows=250):
    index = pd.date_range("2026-01-01", periods=rows, freq="15min", tz="Asia/Kolkata")
    return pd.DataFrame(
        {
            "Open": [100.0] * rows,
            "High": [101.0] * rows,
            "Low": [99.0] * rows,
            "Close": [100.0] * rows,
            "Volume": [50000.0] * rows,
        },
        index=index,
    )


def test_fetch_universe_returns_nonempty_uppercase_symbols(tmp_path):
    fetcher = DataFetcher(cache_dir=tmp_path)

    symbols = fetcher.fetch_universe()

    assert len(symbols) > 0
    assert all(symbol == symbol.upper() for symbol in symbols)
    assert "RELIANCE" in symbols


def test_fetch_universe_result_has_no_duplicates(tmp_path):
    fetcher = DataFetcher(cache_dir=tmp_path)

    symbols = fetcher.fetch_universe()

    assert len(symbols) == len(set(symbols))


def test_fetch_candles_normalises_column_names(tmp_path, monkeypatch):
    fetcher = DataFetcher(cache_dir=tmp_path)
    monkeypatch.setattr(
        "tradingbot.scanner.data_fetcher.yf.Ticker",
        lambda symbol: FakeTicker({}, make_history()),
    )

    df = fetcher.fetch_candles("RELIANCE", days=30, interval="15m")

    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 250


def test_fetch_candles_raises_when_the_frame_is_empty(tmp_path, monkeypatch):
    fetcher = DataFetcher(cache_dir=tmp_path)
    monkeypatch.setattr(
        "tradingbot.scanner.data_fetcher.yf.Ticker",
        lambda symbol: FakeTicker({}, pd.DataFrame()),
    )

    with pytest.raises(DataFetchError, match="no candle data"):
        fetcher.fetch_candles("GHOST", days=30, interval="15m")


def test_fetch_stock_metrics_builds_stock_objects(tmp_path, monkeypatch):
    info = {"marketCap": 19_000_000_000_000, "sector": "Energy"}
    monkeypatch.setattr(
        "tradingbot.scanner.data_fetcher.yf.Ticker",
        lambda symbol: FakeTicker(info, make_history()),
    )
    fetcher = DataFetcher(cache_dir=tmp_path)

    stocks = fetcher.fetch_stock_metrics(["RELIANCE"])

    assert len(stocks) == 1
    stock = stocks[0]
    assert stock.symbol == "RELIANCE"
    assert stock.exchange == "NSE"
    assert stock.last_price == pytest.approx(100.0)
    assert stock.avg_volume == pytest.approx(50000.0)
    assert stock.market_cap_cr == pytest.approx(1_900_000.0)
    assert stock.sector == "Energy"
    assert stock.atr_pct > 0


def test_fetch_stock_metrics_skips_symbols_that_fail(tmp_path, monkeypatch):
    def ticker(symbol):
        if symbol.startswith("BROKEN"):
            raise RuntimeError("delisted")
        return FakeTicker({"marketCap": 1e12, "sector": "IT"}, make_history())

    monkeypatch.setattr("tradingbot.scanner.data_fetcher.yf.Ticker", ticker)
    fetcher = DataFetcher(cache_dir=tmp_path)

    stocks = fetcher.fetch_stock_metrics(["BROKEN.NS", "TCS"])

    assert [stock.symbol for stock in stocks] == ["TCS"]


def test_fetch_stock_metrics_skips_symbols_with_too_little_history(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tradingbot.scanner.data_fetcher.yf.Ticker",
        lambda symbol: FakeTicker({"marketCap": 1e12, "sector": "IT"}, make_history(rows=3)),
    )
    fetcher = DataFetcher(cache_dir=tmp_path)

    assert fetcher.fetch_stock_metrics(["TINY"]) == []
