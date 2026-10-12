"""Tests for CandleStore auto-reconnection after connection drop."""

import tempfile

from tradingbot.data.candle_store import CandleStore


def test_reconnects_after_connection_drop():
    """CandleStore reconnects if the connection is closed."""
    with tempfile.TemporaryDirectory() as d:
        store = CandleStore(f"{d}/test.duckdb")
        store._conn.close()
        result = store.freshness()
        assert isinstance(result, dict)
        store.close()


def test_reconnects_preserves_data():
    """Data written before disconnect is readable after reconnect."""
    import pandas as pd
    from datetime import datetime

    with tempfile.TemporaryDirectory() as d:
        store = CandleStore(f"{d}/test.duckdb")
        df = pd.DataFrame([{
            "timestamp": datetime(2026, 1, 1, 9, 15),
            "open": 100.0, "high": 101.0, "low": 99.0,
            "close": 100.5, "volume": 1000,
        }])
        store.write("TEST", "day", df)
        store._conn.close()
        result = store.read("TEST", "day")
        assert len(result) == 1
        assert result.iloc[0]["close"] == 100.5
        store.close()
