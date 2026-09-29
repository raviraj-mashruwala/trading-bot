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


# ── Index candle sync tests ───────────────────────────────────────────────────

def test_sync_index_candles_calls_fetch_historical_for_each_index(components):
    """sync_index_candles must fetch NIFTY 50, NIFTY BANK, INDIA VIX."""
    sync, client, _, _ = components
    from tradingbot.data.data_sync import DataSync

    client.fetch_historical.return_value = [
        {"date": datetime(2026, 9, 26, tzinfo=IST),
         "open": 24000, "high": 24100, "low": 23900, "close": 24050, "volume": 0},
    ]
    count = sync.sync_index_candles(lookback_days=30)

    tokens_called = {c.args[0] for c in client.fetch_historical.call_args_list}
    assert DataSync._INDEX_INSTRUMENTS["NIFTY 50"] in tokens_called
    assert DataSync._INDEX_INSTRUMENTS["NIFTY BANK"] in tokens_called
    assert DataSync._INDEX_INSTRUMENTS["INDIA VIX"] in tokens_called
    assert count == 3  # 1 candle × 3 indices


def test_sync_index_candles_stored_in_candle_store(components):
    """After sync, CandleStore must have candle rows for NIFTY 50."""
    sync, client, _, store = components
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    IST2 = ZoneInfo("Asia/Kolkata")
    client.fetch_historical.return_value = [
        {"date": datetime(2026, 9, 26, tzinfo=IST2),
         "open": 24000, "high": 24100, "low": 23900, "close": 24050, "volume": 0},
    ]
    sync.sync_index_candles(lookback_days=30)

    df = store.read(
        "NIFTY 50", "day",
        datetime(2026, 9, 25, tzinfo=IST2),
        datetime(2026, 9, 27, tzinfo=IST2),
    )
    assert len(df) == 1
    assert float(df["close"].iloc[0]) == pytest.approx(24050.0)


def test_sync_index_candles_failure_does_not_crash(components):
    """fetch_historical failure for one index must not abort others."""
    sync, client, _, _ = components
    from tradingbot.data.data_sync import DataSync

    call_count = [0]
    def side_effect(token, *args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise ConnectionError("network down")
        return [{"date": datetime(2026, 9, 26, tzinfo=IST),
                 "open": 24000, "high": 24100, "low": 23900, "close": 24050, "volume": 0}]

    client.fetch_historical.side_effect = side_effect
    count = sync.sync_index_candles(lookback_days=30)
    # 1 failed + 2 succeeded × 1 candle each
    assert count == 2


def test_full_sync_includes_index_candles(components):
    """full_sync result dict must include index_candles key."""
    sync, client, cache, _ = components
    client.fetch_historical.return_value = [
        {"date": datetime(2026, 9, 26, tzinfo=IST),
         "open": 24000, "high": 24100, "low": 23900, "close": 24050, "volume": 0},
    ]
    result = sync.full_sync(daily_lookback=30, intraday_lookback=5)
    assert "index_candles" in result
    assert result["index_candles"] >= 0
