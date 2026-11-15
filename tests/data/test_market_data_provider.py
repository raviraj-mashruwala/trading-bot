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


class TestEtfExclusion:
    @staticmethod
    def _provider(rows):
        instruments = [
            {"instrument_type": "EQ", "segment": "NSE", "tradingsymbol": sym, "name": name,
             "instrument_token": i, "exchange": "NSE", "lot_size": 1, "tick_size": 0.05, "last_price": 100}
            for i, (sym, name) in enumerate(rows)
        ]
        kite = type("K", (), {"kite": type("KK", (), {"instruments": staticmethod(lambda ex: instruments)})()})()
        return MarketDataProvider(kite_client=kite)

    def test_etfs_and_funds_are_dropped(self):
        provider = self._provider([
            ("SILVERBEES", "NIPPON INDIA SILVER ETF"),
            ("SILVER", "ADITYA BIRLA SUN LIFE SILVER ETF"),
            ("GOLDBEES", "NIPPON INDIA GOLD BEES ETF"),
            ("LIQUIDBEES", "NIPPON INDIA NIFTY 1D RATE LIQUID BEES ETF"),
            ("QGOLDHALF", "QUANTUM GOLD FUND ETF"),
            ("NIFTYBEES", "NIPPON INDIA ETF NIFTY 50 BEES"),
            ("RELIANCE", "RELIANCE INDUSTRIES"),
        ])

        assert [r["symbol"] for r in provider.get_universe()] == ["RELIANCE"]

    def test_symbols_ending_in_bees_or_etf_are_dropped_even_without_a_name(self):
        provider = self._provider([("CONSUMBEES", ""), ("CPSEETF", ""), ("TCS", "TATA CONSULTANCY SERVICES")])

        assert [r["symbol"] for r in provider.get_universe()] == ["TCS"]

    def test_operating_companies_with_fund_like_words_are_kept(self):
        provider = self._provider([
            ("SBIFUNDS", "SBI FUNDS MANAGEMENT"),
            ("NOCIL", "NOCIL"),
            ("BEESLTD", "BEES AGRO LIMITED"),
        ])

        symbols = [r["symbol"] for r in provider.get_universe()]

        assert "SBIFUNDS" in symbols and "NOCIL" in symbols
