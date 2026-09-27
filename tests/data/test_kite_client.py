import pytest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from tradingbot.data.kite_client import KiteClient, KiteRateLimiter


def test_rate_limiter_throttles():
    limiter = KiteRateLimiter(max_per_sec=3)
    import time
    start = time.monotonic()
    for _ in range(4):
        limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.9  # 4th call waits ~1 second


@pytest.fixture
def mock_kite():
    kite = MagicMock()
    kite.instruments.return_value = [
        {"instrument_token": 738561, "tradingsymbol": "RELIANCE",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
        {"instrument_token": 341249, "tradingsymbol": "HDFCBANK",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
    ]
    kite.historical_data.return_value = [
        {"date": datetime(2026, 9, 26, 9, 15), "open": 2500, "high": 2520,
         "low": 2490, "close": 2510, "volume": 100000},
    ]
    kite.margins.return_value = {"equity": {"available": {"live_balance": 400000}}}
    kite.ltp.return_value = {"NSE:RELIANCE": {"last_price": 2510.0}}
    return kite


def test_fetch_instruments(mock_kite):
    client = KiteClient(mock_kite, rate_limit_per_sec=3)
    instruments = client.fetch_instruments()
    assert len(instruments) == 2
    assert instruments[0]["tradingsymbol"] == "RELIANCE"
    mock_kite.instruments.assert_called_once_with("NSE")


def test_fetch_historical(mock_kite):
    client = KiteClient(mock_kite, rate_limit_per_sec=3)
    candles = client.fetch_historical(
        instrument_token=738561,
        interval="day",
        from_date=date(2026, 9, 1),
        to_date=date(2026, 9, 26),
    )
    assert len(candles) == 1
    assert candles[0]["close"] == 2510
    mock_kite.historical_data.assert_called_once()


def test_fetch_historical_respects_rate_limit(mock_kite):
    client = KiteClient(mock_kite, rate_limit_per_sec=100)
    for _ in range(5):
        client.fetch_historical(738561, "day", date(2026, 9, 1), date(2026, 9, 26))
    assert mock_kite.historical_data.call_count == 5


def test_get_margins(mock_kite):
    client = KiteClient(mock_kite, rate_limit_per_sec=3)
    margins = client.get_margins()
    assert margins["equity"]["available"]["live_balance"] == 400000


def test_get_ltp(mock_kite):
    client = KiteClient(mock_kite, rate_limit_per_sec=3)
    ltp = client.get_ltp(["NSE:RELIANCE"])
    assert ltp["NSE:RELIANCE"]["last_price"] == 2510.0
