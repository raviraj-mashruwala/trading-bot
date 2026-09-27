import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from tradingbot.data.candle_store import CandleStore

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "candles.db"
    return CandleStore(db_path)


def test_upsert_and_read(store):
    candles = [
        {"date": datetime(2026, 9, 26, 9, 15, tzinfo=IST),
         "open": 2500, "high": 2520, "low": 2490, "close": 2510, "volume": 100000},
        {"date": datetime(2026, 9, 26, 9, 30, tzinfo=IST),
         "open": 2510, "high": 2530, "low": 2505, "close": 2525, "volume": 80000},
    ]
    store.upsert("RELIANCE", "15minute", candles)
    result = store.read(
        "RELIANCE", "15minute",
        datetime(2026, 9, 26, 9, 0, tzinfo=IST),
        datetime(2026, 9, 26, 10, 0, tzinfo=IST),
    )
    assert len(result) == 2
    assert result.iloc[0]["close"] == 2510


def test_upsert_deduplicates(store):
    candle = [{"date": datetime(2026, 9, 26, 9, 15, tzinfo=IST),
               "open": 2500, "high": 2520, "low": 2490, "close": 2510, "volume": 100000}]
    store.upsert("RELIANCE", "15minute", candle)
    store.upsert("RELIANCE", "15minute", candle)
    result = store.read(
        "RELIANCE", "15minute",
        datetime(2026, 9, 26, 9, 0, tzinfo=IST),
        datetime(2026, 9, 26, 10, 0, tzinfo=IST),
    )
    assert len(result) == 1


def test_last_timestamp_empty(store):
    assert store.last_timestamp("RELIANCE", "day") is None


def test_last_timestamp(store):
    candles = [
        {"date": datetime(2026, 9, 25, tzinfo=IST),
         "open": 2500, "high": 2520, "low": 2490, "close": 2510, "volume": 100000},
        {"date": datetime(2026, 9, 26, tzinfo=IST),
         "open": 2510, "high": 2530, "low": 2505, "close": 2525, "volume": 80000},
    ]
    store.upsert("RELIANCE", "day", candles)
    last = store.last_timestamp("RELIANCE", "day")
    assert last == datetime(2026, 9, 26, tzinfo=IST)


def test_read_returns_dataframe_with_correct_columns(store):
    candles = [{"date": datetime(2026, 9, 26, 9, 15, tzinfo=IST),
                "open": 100, "high": 110, "low": 95, "close": 105, "volume": 50000}]
    store.upsert("TCS", "day", candles)
    df = store.read("TCS", "day",
                    datetime(2026, 9, 26, tzinfo=IST),
                    datetime(2026, 9, 27, tzinfo=IST))
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.name == "date"
