"""Tests for MarketDataProvider."""

import pytest
import pandas as pd
from tradingbot.data.market_data_provider import MarketDataProvider


class TestSymbolMapping:
    def test_to_nse_symbol(self):
        p = MarketDataProvider()
        assert p.to_nse_symbol("RELIANCE") == "RELIANCE.NS"
        assert p.to_nse_symbol("M&M") == "M&M.NS"
        assert p.to_nse_symbol("RELIANCE.NS") == "RELIANCE.NS"

    def test_from_nse_symbol(self):
        p = MarketDataProvider()
        assert p.from_nse_symbol("RELIANCE.NS") == "RELIANCE"
        assert p.from_nse_symbol("M&M.NS") == "M&M"

    def test_from_nse_symbol_no_suffix(self):
        p = MarketDataProvider()
        assert p.from_nse_symbol("RELIANCE") == "RELIANCE"


class TestNormalize:
    def test_renames_columns_to_lowercase(self):
        df = pd.DataFrame({"Open": [1], "High": [2], "Low": [0.5], "Close": [1.5], "Volume": [100]})
        result = MarketDataProvider._normalize(df)
        assert list(result.columns) == ["open", "high", "low", "close", "volume"]

    def test_drops_extra_columns(self):
        df = pd.DataFrame({
            "Open": [1], "High": [2], "Low": [0.5], "Close": [1.5],
            "Volume": [100], "Dividends": [0], "Stock Splits": [0],
        })
        result = MarketDataProvider._normalize(df)
        assert "dividends" not in result.columns
        assert "stock splits" not in result.columns


class TestGetUniverse:
    def test_no_kite_raises(self):
        p = MarketDataProvider(kite_client=None)
        with pytest.raises(RuntimeError, match="Kite client required"):
            p.get_universe()

    def test_price_prefilter(self):
        mock_kite = type("K", (), {"kite": type("KK", (), {
            "instruments": staticmethod(lambda ex: [
                {"instrument_type": "EQ", "segment": "NSE", "tradingsymbol": "CHEAP",
                 "instrument_token": 1, "lot_size": 1, "tick_size": 0.05, "last_price": 5},
                {"instrument_type": "EQ", "segment": "NSE", "tradingsymbol": "GOOD",
                 "instrument_token": 2, "lot_size": 1, "tick_size": 0.05, "last_price": 500},
                {"instrument_type": "EQ", "segment": "NSE", "tradingsymbol": "PRICEY",
                 "instrument_token": 3, "lot_size": 1, "tick_size": 0.05, "last_price": 10000},
            ])
        })()})()
        p = MarketDataProvider(kite_client=mock_kite)
        result = p.get_universe(min_price=50, max_price=5000)
        symbols = [r["symbol"] for r in result]
        assert symbols == ["GOOD"]

    def test_junk_suffix_regex_filters(self):
        mock_kite = type("K", (), {"kite": type("KK", (), {
            "instruments": staticmethod(lambda ex: [
                {"instrument_type": "EQ", "segment": "NSE", "tradingsymbol": "BOND-NS",
                 "instrument_token": 1, "lot_size": 1, "tick_size": 0.05, "last_price": 100},
                {"instrument_type": "EQ", "segment": "NSE", "tradingsymbol": "BOND-ND",
                 "instrument_token": 2, "lot_size": 1, "tick_size": 0.05, "last_price": 100},
                {"instrument_type": "EQ", "segment": "NSE", "tradingsymbol": "GOOD",
                 "instrument_token": 3, "lot_size": 1, "tick_size": 0.05, "last_price": 100},
            ])
        })()})()
        p = MarketDataProvider(kite_client=mock_kite)
        result = p.get_universe()
        symbols = [r["symbol"] for r in result]
        assert symbols == ["GOOD"]


class TestCache:
    def test_clear_cache(self):
        p = MarketDataProvider()
        p._cache["test"] = pd.DataFrame()
        p.clear_cache()
        assert len(p._cache) == 0


class TestSplitMulti:
    def test_single_symbol(self):
        p = MarketDataProvider()
        df = pd.DataFrame(
            {"Open": [100.0], "High": [105.0], "Low": [99.0], "Close": [103.0], "Volume": [1000]},
            index=pd.DatetimeIndex(["2026-10-01"]),
        )
        result = p._split_multi(df, ["RELIANCE"], ["RELIANCE.NS"])
        assert "RELIANCE" in result
        assert list(result["RELIANCE"].columns) == ["open", "high", "low", "close", "volume"]

    def test_empty_dataframe(self):
        p = MarketDataProvider()
        df = pd.DataFrame()
        result = p._split_multi(df, ["RELIANCE"], ["RELIANCE.NS"])
        assert result == {}


@pytest.mark.integration
class TestIntegration:
    def test_get_daily_batch_real(self):
        p = MarketDataProvider()
        result = p.get_daily_batch(["RELIANCE", "TCS"], days=30)
        assert "RELIANCE" in result
        df = result["RELIANCE"]
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert len(df) > 15

    def test_get_index_real(self):
        p = MarketDataProvider()
        df = p.get_index("NIFTY 50", days=30)
        assert len(df) > 15
        assert "close" in df.columns

    def test_get_intraday_real(self):
        p = MarketDataProvider()
        df = p.get_intraday("RELIANCE", interval="15m", days=10)
        assert len(df) > 10
        assert "close" in df.columns
