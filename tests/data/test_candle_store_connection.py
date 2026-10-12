"""Tests for CandleStore connection modes (local file and URL strings)."""

import os
import tempfile

import pytest

from tradingbot.data.candle_store import CandleStore


def test_local_file_connection():
    """CandleStore works with a local file path (backward compat)."""
    with tempfile.TemporaryDirectory() as d:
        store = CandleStore(f"{d}/test.duckdb")
        assert store.freshness() == {}
        store.close()


def test_string_path_accepted():
    """CandleStore accepts a plain string path, not just Path objects."""
    with tempfile.TemporaryDirectory() as d:
        store = CandleStore(f"{d}/test2.duckdb")
        assert store._conn is not None
        store.close()


@pytest.mark.skipif(
    os.environ.get("MOTHERDUCK_TOKEN", "") != "",
    reason="MOTHERDUCK_TOKEN is set — cannot test missing-token path",
)
def test_missing_motherduck_token_raises():
    """Connecting to md: without MOTHERDUCK_TOKEN raises a clear error."""
    import duckdb
    with pytest.raises((duckdb.IOException, duckdb.ConnectionException, Exception)):
        CandleStore("md:test_nonexistent")
