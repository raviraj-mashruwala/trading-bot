import pytest
import sqlite3
from tradingbot.data.instrument_cache import InstrumentCache


@pytest.fixture
def cache(tmp_path):
    db_path = tmp_path / "instruments.db"
    return InstrumentCache(db_path)


def test_refresh_and_get_all(cache):
    instruments = [
        {"instrument_token": 738561, "tradingsymbol": "RELIANCE",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
        {"instrument_token": 341249, "tradingsymbol": "HDFCBANK",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
    ]
    cache.refresh(instruments)
    result = cache.get_all()
    assert len(result) == 2
    symbols = {r["symbol"] for r in result}
    assert symbols == {"RELIANCE", "HDFCBANK"}


def test_get_token(cache):
    cache.refresh([
        {"instrument_token": 738561, "tradingsymbol": "RELIANCE",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
    ])
    assert cache.get_token("RELIANCE") == 738561


def test_get_token_missing_raises(cache):
    cache.refresh([])
    with pytest.raises(KeyError):
        cache.get_token("NONEXISTENT")


def test_refresh_replaces_old_data(cache):
    cache.refresh([
        {"instrument_token": 1, "tradingsymbol": "OLD",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
    ])
    cache.refresh([
        {"instrument_token": 2, "tradingsymbol": "NEW",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
    ])
    result = cache.get_all()
    assert len(result) == 1
    assert result[0]["symbol"] == "NEW"


def test_filters_non_equity(cache):
    cache.refresh([
        {"instrument_token": 1, "tradingsymbol": "RELIANCE",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
        {"instrument_token": 2, "tradingsymbol": "NIFTY26SEP",
         "exchange": "NFO", "lot_size": 50, "tick_size": 0.05,
         "instrument_type": "FUT", "segment": "NFO-FUT"},
    ])
    result = cache.get_all()
    assert len(result) == 1


def test_sector_stored_from_industry_type(cache):
    """Kite's industry_type field must be stored as sector."""
    cache.refresh([
        {"instrument_token": 738561, "tradingsymbol": "RELIANCE",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE",
         "industry_type": "Petroleum Products"},
        {"instrument_token": 341249, "tradingsymbol": "HDFCBANK",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE",
         "industry_type": "Banks"},
    ])
    result = {r["symbol"]: r for r in cache.get_all()}
    assert result["RELIANCE"]["sector"] == "Petroleum Products"
    assert result["HDFCBANK"]["sector"] == "Banks"


def test_sector_defaults_unknown_when_missing(cache):
    """Instruments without industry_type get sector='unknown'."""
    cache.refresh([
        {"instrument_token": 1, "tradingsymbol": "TEST",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
    ])
    result = cache.get_all()
    assert result[0]["sector"] == "unknown"


def test_migration_idempotent(tmp_path):
    """Opening InstrumentCache twice on same DB must not crash on duplicate column."""
    db = tmp_path / "inst.db"
    c1 = InstrumentCache(db)
    c1.refresh([{"instrument_token": 1, "tradingsymbol": "X",
                 "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
                 "instrument_type": "EQ", "segment": "NSE"}])
    c1.close()
    c2 = InstrumentCache(db)  # must not raise
    c2.close()
