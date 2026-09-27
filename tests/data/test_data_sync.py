import pytest
from datetime import date, datetime
from unittest.mock import MagicMock, patch, call
from zoneinfo import ZoneInfo
from tradingbot.data.data_sync import DataSync
from tradingbot.data.instrument_cache import InstrumentCache
from tradingbot.data.candle_store import CandleStore

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def components(tmp_path):
    cache = InstrumentCache(tmp_path / "instruments.db")
    store = CandleStore(tmp_path / "candles.db")
    client = MagicMock()
    client.fetch_instruments.return_value = [
        {"instrument_token": 738561, "tradingsymbol": "RELIANCE",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
    ]
    client.fetch_historical.return_value = [
        {"date": datetime(2026, 9, 26, tzinfo=IST),
         "open": 2500, "high": 2520, "low": 2490, "close": 2510, "volume": 100000},
    ]
    sync = DataSync(client=client, instrument_cache=cache, candle_store=store)
    return sync, client, cache, store


def test_sync_instruments(components):
    sync, client, cache, _ = components
    count = sync.sync_instruments()
    assert count == 1
    assert cache.get_token("RELIANCE") == 738561


def test_sync_daily_candles_incremental(components):
    sync, client, _, store = components
    sync.sync_instruments()
    sync.sync_daily_candles(["RELIANCE"], lookback_days=365)
    assert client.fetch_historical.call_count == 1
    args = client.fetch_historical.call_args
    assert args.kwargs["interval"] == "day" or args[0][1] == "day"


def test_sync_intraday_candles(components):
    sync, client, _, store = components
    sync.sync_instruments()
    sync.sync_intraday_candles(["RELIANCE"], interval="15minute", lookback_days=60)
    assert client.fetch_historical.call_count >= 1


def test_deep_fetch_multiple_timeframes(components):
    sync, client, _, store = components
    sync.sync_instruments()
    sync.deep_fetch(["RELIANCE"])
    # deep_fetch should call for 5minute and minute intervals
    intervals_called = [c.kwargs.get("interval", c[0][1] if len(c[0]) > 1 else None)
                        for c in client.fetch_historical.call_args_list]
    assert len(client.fetch_historical.call_args_list) >= 2


def test_sync_symbol_missing_token_returns_zero(components):
    """_sync_symbol gracefully handles KeyError from get_token."""
    sync, client, cache, store = components
    # Don't sync instruments — cache empty, so get_token will raise
    count = sync.sync_daily_candles(["UNKNOWN_SYMBOL"])
    assert count == 0
    assert client.fetch_historical.call_count == 0


def test_sync_daily_incremental_skips_when_up_to_date(components):
    """When last_timestamp is today, no fetch occurs."""
    sync, client, cache, store = components
    sync.sync_instruments()
    # First sync fetches
    sync.sync_daily_candles(["RELIANCE"])
    first_call_count = client.fetch_historical.call_count
    assert first_call_count == 1
    # Mock last_timestamp to return today
    with patch.object(store, "last_timestamp", return_value=datetime.now(IST)):
        sync.sync_daily_candles(["RELIANCE"])
    # No additional fetch — from_date > to_date
    assert client.fetch_historical.call_count == first_call_count


def test_sync_handles_fetch_exception(components):
    """If fetch_historical raises, _sync_symbol logs and returns 0."""
    sync, client, cache, store = components
    sync.sync_instruments()
    client.fetch_historical.side_effect = ConnectionError("network down")
    count = sync.sync_daily_candles(["RELIANCE"])
    assert count == 0
