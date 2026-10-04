"""Tests for MarketDataProvider (Kite universe only — yfinance removed)."""

import pytest
from tradingbot.data.market_data_provider import MarketDataProvider


class TestGetUniverse:
    def test_no_kite_raises(self):
        p = MarketDataProvider(kite_client=None)
        with pytest.raises(RuntimeError, match="Kite client required"):
            p.get_universe()

    def test_price_prefilter(self):
        mock_kite = type("K", (), {"kite": type("KK", (), {
            "instruments": staticmethod(lambda ex: [
                {"instrument_type": "EQ", "segment": "NSE", "tradingsymbol": "CHEAP",
                 "instrument_token": 1, "exchange": "NSE", "lot_size": 1, "tick_size": 0.05, "last_price": 5},
                {"instrument_type": "EQ", "segment": "NSE", "tradingsymbol": "GOOD",
                 "instrument_token": 2, "exchange": "NSE", "lot_size": 1, "tick_size": 0.05, "last_price": 500},
                {"instrument_type": "EQ", "segment": "NSE", "tradingsymbol": "PRICEY",
                 "instrument_token": 3, "exchange": "NSE", "lot_size": 1, "tick_size": 0.05, "last_price": 10000},
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
                 "instrument_token": 1, "exchange": "NSE", "lot_size": 1, "tick_size": 0.05, "last_price": 100},
                {"instrument_type": "EQ", "segment": "NSE", "tradingsymbol": "BOND-ND",
                 "instrument_token": 2, "exchange": "NSE", "lot_size": 1, "tick_size": 0.05, "last_price": 100},
                {"instrument_type": "EQ", "segment": "NSE", "tradingsymbol": "GOOD",
                 "instrument_token": 3, "exchange": "NSE", "lot_size": 1, "tick_size": 0.05, "last_price": 100},
            ])
        })()})()
        p = MarketDataProvider(kite_client=mock_kite)
        result = p.get_universe()
        symbols = [r["symbol"] for r in result]
        assert symbols == ["GOOD"]
