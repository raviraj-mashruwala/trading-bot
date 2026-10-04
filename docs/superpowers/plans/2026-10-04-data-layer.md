# Data Layer Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace yfinance with a local DuckDB OHLCV cache backed by Kite historical API — multi-timeframe, deep history, instant analysis reads.

**Architecture:** `CandleStore` wraps a single DuckDB file with read/write for OHLCV across intervals. `KiteDataSync` paginates Kite historical API to fill and incrementally update the cache. Pipeline reads from CandleStore instead of yfinance. Background sync on server startup keeps cache fresh.

**Tech Stack:** Python 3.12, DuckDB, Pandas, existing `KiteClient` (rate-limited)

**Spec:** `docs/superpowers/specs/2026-10-04-data-layer-design.md`

## Global Constraints

- DuckDB is the only new dependency — `duckdb >= 1.0.0`
- yfinance is removed entirely after pipeline rewire
- `KiteClient` (`data/kite_client.py`) is the only interface to Kite — `fetch_historical(token, interval, from_date, to_date)`
- `InstrumentCache` (`data/instrument_cache.py`) maps symbols to tokens via `get_token(symbol) -> int`
- All DataFrames use lowercase columns: `timestamp`, `open`, `high`, `low`, `close`, `volume`
- Kite rate limit: 3 requests/second (enforced by `KiteRateLimiter`)
- Kite per-request caps: day=2000d, 15m=200d, 5m=100d, 1m=60d — pagination required for deeper history
- Index tokens: NIFTY 50 = `256265`, INDIA VIX = `264969`, NIFTY BANK = `260105`
- DuckDB file location: `{data_dir}/candles.duckdb`

## Review Focus

1. **DuckDB concurrent access during background sync + analysis read:** DuckDB allows concurrent readers but only one writer. If sync is writing while analysis reads, it must not corrupt or block. Test: write in one thread, read in another simultaneously. Added to Task 1.
2. **Kite token resolution for index symbols:** Index instruments (NIFTY 50, INDIA VIX) are not in `InstrumentCache` (it stores equities only). Sync must handle index tokens separately. Added to Task 2.
3. **Pagination boundary: off-by-one on date ranges:** If last_date is Oct 3 and we fetch from Oct 4, a weekend/holiday gap could produce an empty response that looks like "no more data." Sync must not mark the stock as fully synced. Added to Task 2.
4. **Pipeline cache miss during first run:** If initial fill hasn't completed and analysis runs, CandleStore returns empty DataFrames. Pipeline must handle empty gracefully — skip stock, don't crash. Added to Task 3.
5. **yfinance removal breaks `market_context.py` index fetching:** `MarketContextFetcher._read_index` uses `provider.get_index()` which calls yfinance. After removal, it must use CandleStore (the fallback path already exists at line 142 but needs the store passed in). Added to Task 4.

---

### Task 1: CandleStore — DuckDB OHLCV storage

**Files:**
- Create: `tradingbot/data/candle_store.py`
- Create: `tests/data/test_candle_store.py`
- Modify: `pyproject.toml` (add `duckdb >= 1.0.0`)

**Interfaces:**
- Consumes: nothing (foundation layer)
- Produces:
  - `CandleStore(db_path: Path)` with `.read(symbol, interval, days, from_date, to_date) -> pd.DataFrame`, `.read_batch(symbols, interval, days) -> dict[str, pd.DataFrame]`, `.write(symbol, interval, df) -> int`, `.write_batch(data, interval) -> int`, `.last_date(symbol, interval) -> date | None`, `.symbols_with_data(interval) -> list[str]`, `.freshness() -> dict[str, date]`, `.row_count() -> dict[str, int]`, `.close()`

- [ ] **Step 1: Add duckdb dependency**

```toml
# In pyproject.toml [project.dependencies], add:
"duckdb>=1.0.0",
```

Run: `uv sync`

- [ ] **Step 2: Write test — create store, write and read back**

```python
# tests/data/test_candle_store.py
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def store(tmp_path):
    from tradingbot.data.candle_store import CandleStore
    s = CandleStore(tmp_path / "test.duckdb")
    yield s
    s.close()


def _sample_df(symbol: str = "RELIANCE", days: int = 5, start: date = date(2026, 9, 28)):
    rows = []
    for i in range(days):
        d = date(start.year, start.month, start.day + i) if start.day + i <= 28 else date(start.year, start.month + 1, i + 1)
        rows.append({
            "timestamp": datetime(2026, 10, 1 + i, 9, 15),
            "open": 2450.0 + i, "high": 2460.0 + i,
            "low": 2440.0 + i, "close": 2455.0 + i,
            "volume": 100000 + i * 1000,
        })
    return pd.DataFrame(rows)


def test_write_and_read(store):
    df = _sample_df()
    written = store.write("RELIANCE", "day", df)
    assert written == 5
    result = store.read("RELIANCE", "day")
    assert len(result) == 5
    assert list(result.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
```

- [ ] **Step 3: Write test — deduplication on write**

```python
def test_write_deduplicates(store):
    df = _sample_df()
    store.write("RELIANCE", "day", df)
    written2 = store.write("RELIANCE", "day", df)
    assert written2 == 0  # all duplicates
    assert len(store.read("RELIANCE", "day")) == 5
```

- [ ] **Step 4: Write test — read_batch returns dict**

```python
def test_read_batch(store):
    store.write("RELIANCE", "day", _sample_df())
    store.write("HDFCBANK", "day", _sample_df())
    result = store.read_batch(["RELIANCE", "HDFCBANK", "MISSING"], "day")
    assert "RELIANCE" in result
    assert "HDFCBANK" in result
    assert len(result["RELIANCE"]) == 5
    assert "MISSING" not in result or result["MISSING"].empty
```

- [ ] **Step 5: Write test — read with days parameter**

```python
def test_read_with_days_limit(store):
    store.write("RELIANCE", "day", _sample_df())
    result = store.read("RELIANCE", "day", days=3)
    assert len(result) == 3  # most recent 3
```

- [ ] **Step 6: Write test — last_date**

```python
def test_last_date(store):
    store.write("RELIANCE", "day", _sample_df())
    last = store.last_date("RELIANCE", "day")
    assert last is not None
    assert store.last_date("MISSING", "day") is None
```

- [ ] **Step 7: Write test — freshness**

```python
def test_freshness(store):
    store.write("RELIANCE", "day", _sample_df())
    store.write("RELIANCE", "15m", _sample_df())
    fresh = store.freshness()
    assert "day" in fresh
    assert "15m" in fresh
```

- [ ] **Step 8: Write test — empty read returns empty DataFrame**

```python
def test_empty_read_returns_empty_df(store):
    result = store.read("NONEXISTENT", "day")
    assert isinstance(result, pd.DataFrame)
    assert result.empty
```

- [ ] **Step 9: Write test — concurrent read during write (Review Focus #1)**

```python
def test_concurrent_read_during_write(store):
    import threading
    store.write("RELIANCE", "day", _sample_df())

    errors = []
    def reader():
        try:
            for _ in range(10):
                result = store.read("RELIANCE", "day")
                assert len(result) >= 0
        except Exception as e:
            errors.append(e)

    def writer():
        try:
            for i in range(5):
                rows = [{"timestamp": datetime(2026, 11, 1 + i, 9, 15),
                         "open": 2500.0, "high": 2510.0, "low": 2490.0,
                         "close": 2505.0, "volume": 50000}]
                store.write("HDFCBANK", "day", pd.DataFrame(rows))
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=reader)
    t2 = threading.Thread(target=writer)
    t1.start(); t2.start()
    t1.join(); t2.join()
    assert not errors, f"Concurrent access failed: {errors}"
```

- [ ] **Step 10: Run tests — expect FAIL**

Run: `uv run pytest tests/data/test_candle_store.py -v`
Expected: FAIL — module not found

- [ ] **Step 11: Implement candle_store.py**

```python
"""DuckDB-backed OHLCV candle storage with multi-interval support."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol      VARCHAR NOT NULL,
    interval    VARCHAR NOT NULL,
    timestamp   TIMESTAMP NOT NULL,
    open        DOUBLE NOT NULL,
    high        DOUBLE NOT NULL,
    low         DOUBLE NOT NULL,
    close       DOUBLE NOT NULL,
    volume      BIGINT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_candles_pk
    ON candles (symbol, interval, timestamp);
"""


class CandleStore:
    """Read/write OHLCV candles in DuckDB. Thread-safe for concurrent reads."""

    def __init__(self, db_path: Path) -> None:
        self._path = str(db_path)
        self._conn = duckdb.connect(self._path)
        self._conn.execute(_SCHEMA)

    def read(
        self,
        symbol: str,
        interval: str,
        days: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> pd.DataFrame:
        conditions = ["symbol = ? AND interval = ?"]
        params: list[Any] = [symbol, interval]

        if from_date is not None:
            conditions.append("timestamp >= ?")
            params.append(datetime.combine(from_date, datetime.min.time()))
        if to_date is not None:
            conditions.append("timestamp <= ?")
            params.append(datetime.combine(to_date, datetime.max.time()))

        where = " AND ".join(conditions)
        query = f"SELECT timestamp, open, high, low, close, volume FROM candles WHERE {where} ORDER BY timestamp"

        if days is not None:
            query += f" DESC LIMIT ?"
            params.append(days * 400)  # generous limit for intraday
            df = self._conn.execute(query, params).fetchdf()
            df = df.sort_values("timestamp").tail(days) if interval == "day" else df.sort_values("timestamp")
            # For intraday, 'days' means trading days
            if interval != "day" and days is not None:
                cutoff = datetime.now() - timedelta(days=days * 2)  # generous
                df = df[df["timestamp"] >= cutoff].tail(days * 400)
            return df.reset_index(drop=True)

        return self._conn.execute(query, params).fetchdf()

    def read_batch(
        self,
        symbols: list[str],
        interval: str,
        days: int = 30,
    ) -> dict[str, pd.DataFrame]:
        if not symbols:
            return {}
        placeholders = ", ".join(["?"] * len(symbols))
        cutoff = datetime.now() - timedelta(days=days * 2)
        query = f"""
            SELECT symbol, timestamp, open, high, low, close, volume
            FROM candles
            WHERE symbol IN ({placeholders})
              AND interval = ?
              AND timestamp >= ?
            ORDER BY symbol, timestamp
        """
        params = symbols + [interval, cutoff]
        df = self._conn.execute(query, params).fetchdf()
        if df.empty:
            return {}
        result = {}
        for sym, group in df.groupby("symbol"):
            result[sym] = group.drop(columns=["symbol"]).reset_index(drop=True)
        return result

    def write(self, symbol: str, interval: str, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        before = self._count(symbol, interval)
        records = df.copy()
        records["symbol"] = symbol
        records["interval"] = interval
        cols = ["symbol", "interval", "timestamp", "open", "high", "low", "close", "volume"]
        self._conn.execute(
            f"INSERT OR IGNORE INTO candles ({', '.join(cols)}) SELECT * FROM records[{cols}]"
        )
        after = self._count(symbol, interval)
        return after - before

    def write_batch(self, data: dict[str, pd.DataFrame], interval: str) -> int:
        total = 0
        for symbol, df in data.items():
            total += self.write(symbol, interval, df)
        return total

    def last_date(self, symbol: str, interval: str) -> date | None:
        row = self._conn.execute(
            "SELECT MAX(timestamp) as last_ts FROM candles WHERE symbol = ? AND interval = ?",
            [symbol, interval],
        ).fetchone()
        if row and row[0] is not None:
            ts = row[0]
            return ts.date() if isinstance(ts, datetime) else ts
        return None

    def symbols_with_data(self, interval: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT symbol FROM candles WHERE interval = ? ORDER BY symbol",
            [interval],
        ).fetchall()
        return [r[0] for r in rows]

    def freshness(self) -> dict[str, date]:
        rows = self._conn.execute(
            "SELECT interval, MAX(timestamp) as latest FROM candles GROUP BY interval"
        ).fetchall()
        result = {}
        for r in rows:
            ts = r[1]
            result[r[0]] = ts.date() if isinstance(ts, datetime) else ts
        return result

    def row_count(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT interval, COUNT(*) as cnt FROM candles GROUP BY interval"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def _count(self, symbol: str, interval: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM candles WHERE symbol = ? AND interval = ?",
            [symbol, interval],
        ).fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 12: Run tests — expect PASS**

Run: `uv run pytest tests/data/test_candle_store.py -v`
Expected: 8 passed

- [ ] **Step 13: Run full test suite — no regressions**

Run: `uv run pytest tests/data/ -q`
Expected: All pass

- [ ] **Step 14: Commit**

```bash
git add tradingbot/data/candle_store.py tests/data/test_candle_store.py pyproject.toml
git commit -m "feat(data): add CandleStore — DuckDB OHLCV cache with multi-interval support"
```

---

### Task 2: KiteDataSync — paginated fetcher with resume/retry

**Files:**
- Create: `tradingbot/data/kite_data_sync.py`
- Create: `tests/data/test_kite_data_sync.py`

**Interfaces:**
- Consumes: `CandleStore.write(symbol, interval, df)`, `CandleStore.last_date(symbol, interval)`, `CandleStore.read_batch(symbols, "day", 20)` from Task 1; `KiteClient.fetch_historical(token, interval, from_date, to_date)` from existing code; `InstrumentCache.get_token(symbol)`, `InstrumentCache.get_all()` from existing code
- Produces:
  - `KiteDataSync(kite_client, candle_store, instrument_cache, screening_config)` with `async initial_fill(progress_callback) -> SyncReport`, `async daily_sync(progress_callback) -> SyncReport`, `async fetch_on_demand(symbol, intervals) -> None`
  - `SyncReport(stocks_synced: int, rows_written: int, errors: list[str], duration_sec: float)`
  - `KITE_LIMITS: dict`, `TARGET_DEPTHS: dict`

- [ ] **Step 1: Write test — pagination chunks date range correctly**

```python
# tests/data/test_kite_data_sync.py
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pandas as pd
import pytest


@pytest.fixture
def store(tmp_path):
    from tradingbot.data.candle_store import CandleStore
    s = CandleStore(tmp_path / "test.duckdb")
    yield s
    s.close()


def _mock_kite(candles_per_call=5):
    kite = MagicMock()
    def _fetch(token, interval, from_date, to_date):
        rows = []
        for i in range(candles_per_call):
            rows.append({
                "date": datetime(2026, 10, 1, 9, 15 + i),
                "open": 2450.0, "high": 2460.0,
                "low": 2440.0, "close": 2455.0,
                "volume": 100000,
            })
        return rows
    kite.fetch_historical = MagicMock(side_effect=_fetch)
    return kite


def _mock_instruments():
    cache = MagicMock()
    cache.get_token = MagicMock(return_value=738561)
    cache.get_all = MagicMock(return_value=[
        {"token": 738561, "symbol": "RELIANCE", "sector": "energy"},
    ])
    return cache


def _mock_screening_config():
    config = MagicMock()
    config.min_volume = 100_000
    config.min_price = 50.0
    config.max_price = 5000.0
    config.min_market_cap_cr = 500.0
    return config


def test_pagination_chunks_correctly():
    from tradingbot.data.kite_data_sync import _date_chunks
    chunks = list(_date_chunks(date(2026, 1, 1), date(2026, 12, 31), max_days=100))
    assert len(chunks) == 4  # 365 / 100 = 3.65, so 4 chunks
    assert chunks[0][0] == date(2026, 1, 1)
    assert chunks[-1][1] == date(2026, 12, 31)
    # No gaps between chunks
    for i in range(len(chunks) - 1):
        assert (chunks[i + 1][0] - chunks[i][1]).days == 1
```

- [ ] **Step 2: Write test — resume skips already-fetched**

```python
@pytest.mark.asyncio
async def test_resume_skips_fetched(store):
    from tradingbot.data.kite_data_sync import KiteDataSync
    # Pre-populate store with some data
    rows = [{"timestamp": datetime(2026, 10, 1 + i, 9, 15),
             "open": 2450.0, "high": 2460.0, "low": 2440.0,
             "close": 2455.0, "volume": 100000} for i in range(3)]
    store.write("RELIANCE", "day", pd.DataFrame(rows))

    kite = _mock_kite()
    sync = KiteDataSync(kite, store, _mock_instruments(), _mock_screening_config())
    await sync.fetch_on_demand("RELIANCE", ["day"])

    # Should only fetch from after Oct 3 (last_date), not from the beginning
    calls = kite.fetch_historical.call_args_list
    if calls:
        first_from = calls[0][0][2]  # from_date argument
        assert first_from >= date(2026, 10, 3)
```

- [ ] **Step 3: Write test — per-stock failure doesn't stop sync**

```python
@pytest.mark.asyncio
async def test_per_stock_failure_continues():
    from tradingbot.data.kite_data_sync import KiteDataSync, SyncReport
    from tradingbot.data.candle_store import CandleStore
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        store = CandleStore(Path(tmp) / "test.duckdb")
        kite = MagicMock()
        call_count = [0]
        def _fetch(token, interval, from_date, to_date):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Kite API error")
            return [{"date": datetime(2026, 10, 1, 9, 15),
                     "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000}]
        kite.fetch_historical = MagicMock(side_effect=_fetch)

        instruments = MagicMock()
        instruments.get_all = MagicMock(return_value=[
            {"token": 1, "symbol": "FAIL_STOCK", "sector": "x"},
            {"token": 2, "symbol": "OK_STOCK", "sector": "y"},
        ])
        instruments.get_token = MagicMock(side_effect=lambda s: 1 if s == "FAIL_STOCK" else 2)

        sync = KiteDataSync(kite, store, instruments, _mock_screening_config())
        report = await sync._sync_interval(["FAIL_STOCK", "OK_STOCK"], "day",
                                           date(2026, 10, 1), date(2026, 10, 1))
        assert len(report.errors) >= 1
        assert report.stocks_synced >= 1  # OK_STOCK succeeded
        store.close()
```

- [ ] **Step 4: Write test — daily sync fetches only since last_date**

```python
@pytest.mark.asyncio
async def test_daily_sync_incremental(store):
    from tradingbot.data.kite_data_sync import KiteDataSync
    rows = [{"timestamp": datetime(2026, 10, 1, 9, 15),
             "open": 2450.0, "high": 2460.0, "low": 2440.0,
             "close": 2455.0, "volume": 100000}]
    store.write("RELIANCE", "day", pd.DataFrame(rows))

    kite = _mock_kite(candles_per_call=1)
    sync = KiteDataSync(kite, store, _mock_instruments(), _mock_screening_config())
    await sync.daily_sync()

    calls = kite.fetch_historical.call_args_list
    if calls:
        from_arg = calls[0][0][2]
        assert from_arg >= date(2026, 10, 1)
```

- [ ] **Step 5: Run tests — expect FAIL**

Run: `uv run pytest tests/data/test_kite_data_sync.py -v`
Expected: FAIL — module not found

- [ ] **Step 6: Implement kite_data_sync.py**

```python
"""Paginated Kite historical data fetcher with resume and retry."""

from __future__ import annotations

import asyncio
import logging
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

import pandas as pd

from tradingbot.data.candle_store import CandleStore

log = logging.getLogger(__name__)

KITE_LIMITS = {
    "day": 2000,
    "15minute": 200,
    "5minute": 100,
    "minute": 60,
}

INTERVAL_MAP = {
    "day": "day",
    "15m": "15minute",
    "5m": "5minute",
    "1m": "minute",
}

STORE_INTERVAL_MAP = {v: k for k, v in INTERVAL_MAP.items()}

TARGET_DEPTHS = {
    "day": {"years": 11, "stocks": "all"},
    "15m": {"years": 11, "stocks": "liquid"},
    "5m": {"years": 5, "stocks": "liquid"},
    "1m": {"years": 5, "stocks": "liquid"},
}

INDEX_TOKENS = {
    "NIFTY 50": 256265,
    "INDIA VIX": 264969,
    "NIFTY BANK": 260105,
}

MAX_RETRIES = 3
RETRY_BACKOFF = [1, 2, 4]


@dataclass
class SyncReport:
    stocks_synced: int = 0
    rows_written: int = 0
    errors: list[str] = field(default_factory=list)
    duration_sec: float = 0.0


def _date_chunks(start: date, end: date, max_days: int) -> list[tuple[date, date]]:
    chunks = []
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=max_days - 1), end)
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks


def _kite_rows_to_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    records = []
    for r in rows:
        ts = r["date"] if isinstance(r["date"], datetime) else datetime.combine(r["date"], datetime.min.time())
        records.append({
            "timestamp": ts,
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": int(r["volume"]),
        })
    return pd.DataFrame(records)


class KiteDataSync:
    """Paginated Kite historical fetcher with resume, retry, and background fill."""

    def __init__(
        self,
        kite_client: Any,
        candle_store: CandleStore,
        instrument_cache: Any,
        screening_config: Any = None,
    ) -> None:
        self._kite = kite_client
        self._store = candle_store
        self._instruments = instrument_cache
        self._screening = screening_config
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    async def initial_fill(self, progress_callback: Callable | None = None) -> SyncReport:
        start = _time.monotonic()
        report = SyncReport()
        self._cancelled = False
        today = date.today()

        all_instruments = self._instruments.get_all()
        all_symbols = [i["symbol"] for i in all_instruments]

        for store_interval, config in TARGET_DEPTHS.items():
            if self._cancelled:
                break
            kite_interval = INTERVAL_MAP[store_interval]
            max_days = KITE_LIMITS[kite_interval]
            start_date = date(today.year - config["years"], today.month, today.day)

            if config["stocks"] == "all":
                symbols = all_symbols
            else:
                symbols = self._get_liquid_symbols(all_symbols)

            # Add index symbols for daily
            if store_interval == "day":
                symbols = list(set(symbols) | set(INDEX_TOKENS.keys()))

            if progress_callback:
                progress_callback(f"Starting {store_interval}: {len(symbols)} stocks, since {start_date}")

            sub = await self._sync_interval(symbols, store_interval, start_date, today,
                                            kite_interval, max_days, progress_callback)
            report.stocks_synced += sub.stocks_synced
            report.rows_written += sub.rows_written
            report.errors.extend(sub.errors)

        report.duration_sec = _time.monotonic() - start
        log.info("Initial fill complete: %d stocks, %d rows, %.0fs, %d errors",
                 report.stocks_synced, report.rows_written, report.duration_sec, len(report.errors))
        return report

    async def daily_sync(self, progress_callback: Callable | None = None) -> SyncReport:
        start = _time.monotonic()
        report = SyncReport()
        self._cancelled = False
        today = date.today()

        for store_interval in TARGET_DEPTHS:
            if self._cancelled:
                break
            kite_interval = INTERVAL_MAP[store_interval]
            max_days = KITE_LIMITS[kite_interval]
            symbols = self._store.symbols_with_data(store_interval)

            if not symbols:
                continue

            if progress_callback:
                progress_callback(f"Daily sync {store_interval}: {len(symbols)} stocks")

            for symbol in symbols:
                if self._cancelled:
                    break
                last = self._store.last_date(symbol, store_interval)
                if last and last >= today:
                    continue
                from_date = last + timedelta(days=1) if last else today - timedelta(days=5)
                try:
                    token = self._resolve_token(symbol)
                    raw = await asyncio.to_thread(
                        self._kite.fetch_historical, token, kite_interval, from_date, today
                    )
                    df = _kite_rows_to_df(raw)
                    written = self._store.write(symbol, store_interval, df)
                    report.rows_written += written
                    report.stocks_synced += 1
                except Exception as exc:
                    report.errors.append(f"{symbol}/{store_interval}: {exc}")

        report.duration_sec = _time.monotonic() - start
        log.info("Daily sync: %d stocks, %d rows, %.0fs", report.stocks_synced, report.rows_written, report.duration_sec)
        return report

    async def fetch_on_demand(self, symbol: str, intervals: list[str] | None = None) -> None:
        if intervals is None:
            intervals = ["day", "15m"]
        today = date.today()
        for store_interval in intervals:
            last = self._store.last_date(symbol, store_interval)
            kite_interval = INTERVAL_MAP.get(store_interval, store_interval)
            max_days = KITE_LIMITS.get(kite_interval, 60)
            from_date = last + timedelta(days=1) if last else today - timedelta(days=max_days)
            try:
                token = self._resolve_token(symbol)
                raw = await asyncio.to_thread(
                    self._kite.fetch_historical, token, kite_interval, from_date, today
                )
                df = _kite_rows_to_df(raw)
                self._store.write(symbol, store_interval, df)
            except Exception:
                log.warning("On-demand fetch failed for %s/%s", symbol, store_interval, exc_info=True)

    async def _sync_interval(
        self,
        symbols: list[str],
        store_interval: str,
        start_date: date,
        end_date: date,
        kite_interval: str | None = None,
        max_days: int | None = None,
        progress_callback: Callable | None = None,
    ) -> SyncReport:
        if kite_interval is None:
            kite_interval = INTERVAL_MAP[store_interval]
        if max_days is None:
            max_days = KITE_LIMITS[kite_interval]

        report = SyncReport()
        for idx, symbol in enumerate(symbols):
            if self._cancelled:
                break

            last = self._store.last_date(symbol, store_interval)
            sym_start = last + timedelta(days=1) if last else start_date
            if sym_start > end_date:
                report.stocks_synced += 1
                continue

            chunks = _date_chunks(sym_start, end_date, max_days)
            sym_rows = 0

            for chunk_from, chunk_to in chunks:
                if self._cancelled:
                    break
                for attempt in range(MAX_RETRIES):
                    try:
                        token = self._resolve_token(symbol)
                        raw = await asyncio.to_thread(
                            self._kite.fetch_historical, token, kite_interval, chunk_from, chunk_to
                        )
                        df = _kite_rows_to_df(raw)
                        written = self._store.write(symbol, store_interval, df)
                        sym_rows += written
                        break
                    except Exception as exc:
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(RETRY_BACKOFF[attempt])
                        else:
                            report.errors.append(f"{symbol}/{store_interval} {chunk_from}-{chunk_to}: {exc}")

            report.rows_written += sym_rows
            report.stocks_synced += 1

            if progress_callback and (idx + 1) % 10 == 0:
                progress_callback(f"{store_interval}: {idx + 1}/{len(symbols)} stocks, {report.rows_written} rows")

        return report

    def _resolve_token(self, symbol: str) -> int:
        if symbol in INDEX_TOKENS:
            return INDEX_TOKENS[symbol]
        return self._instruments.get_token(symbol)

    def _get_liquid_symbols(self, all_symbols: list[str]) -> list[str]:
        daily_data = self._store.read_batch(all_symbols, "day", days=20)
        liquid = []
        for symbol, df in daily_data.items():
            if df.empty or len(df) < 5:
                continue
            avg_vol = float(df["volume"].tail(20).mean())
            last_price = float(df["close"].iloc[-1])
            if self._screening is None:
                if avg_vol >= 100_000 and 50 <= last_price <= 5000:
                    liquid.append(symbol)
            else:
                if (avg_vol >= self._screening.min_volume
                        and self._screening.min_price <= last_price <= self._screening.max_price):
                    liquid.append(symbol)
        log.info("Liquid stocks for intraday: %d / %d", len(liquid), len(all_symbols))
        return liquid
```

- [ ] **Step 7: Run tests — expect PASS**

Run: `uv run pytest tests/data/test_kite_data_sync.py -v`
Expected: 4 passed

- [ ] **Step 8: Commit**

```bash
git add tradingbot/data/kite_data_sync.py tests/data/test_kite_data_sync.py
git commit -m "feat(data): add KiteDataSync — paginated Kite fetcher with resume/retry"
```

---

### Task 3: Pipeline rewire — replace yfinance with CandleStore

**Files:**
- Modify: `tradingbot/analysis/pipeline.py`
- Modify: `tradingbot/api/analysis_routes.py`

**Interfaces:**
- Consumes: `CandleStore.read_batch(symbols, interval, days)`, `CandleStore.read(symbol, interval, days)` from Task 1
- Produces: Pipeline that reads from CandleStore, falls back to on-demand Kite fetch on cache miss

- [ ] **Step 1: Modify pipeline constructor — accept candle_store**

In `pipeline.py`, add `candle_store` parameter to `__init__`:

```python
def __init__(
    self,
    ...,
    candle_store: Any = None,
):
    ...
    self._candle_store = candle_store
```

- [ ] **Step 2: Replace yfinance fetch point #1 — screening daily batch**

In `_build_stock_metrics_from_instruments`, replace lines 391-398:

```python
if self._candle_store is not None:
    daily_data = self._candle_store.read_batch(symbols, "day", days=30)
elif self._provider is not None:
    daily_data = self._provider.get_daily_batch(symbols, days=30)
else:
    daily_data = {}
    for sym in symbols:
        df = self._candles.read(sym, "day", from_dt, now)
        if not df.empty:
            daily_data[sym] = df
```

- [ ] **Step 3: Find and replace remaining yfinance fetch points**

Search for all `self._provider.get_intraday` and `self._provider.get_daily_batch` calls. Replace each with `self._candle_store.read()` or `self._candle_store.read_batch()` with CandleStore-first, provider fallback.

- [ ] **Step 4: Pass candle_store from analysis_routes**

In `api/analysis_routes.py`, pass `candle_store` when constructing the pipeline:

```python
pipeline = AnalysisPipeline(
    ...,
    candle_store=getattr(state, 'candle_store', None),
)
```

- [ ] **Step 5: Run analysis tests**

Run: `uv run pytest tests/analysis/ -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add tradingbot/analysis/pipeline.py tradingbot/api/analysis_routes.py
git commit -m "feat(data): rewire pipeline to use CandleStore — yfinance now fallback only"
```

---

### Task 4: Server startup sync + yfinance removal + index data

**Files:**
- Modify: `tradingbot/api/app.py` (add CandleStore creation + background sync)
- Modify: `tradingbot/api/state.py` (add candle_store field)
- Modify: `tradingbot/data/market_data_provider.py` (remove yfinance methods)
- Modify: `tradingbot/scanner/market_context.py` (use CandleStore for index data)
- Modify: `pyproject.toml` (remove yfinance if present in deps)
- Modify: `tradingbot/cli.py` (remove yfinance references)

**Interfaces:**
- Consumes: `CandleStore` from Task 1, `KiteDataSync` from Task 2
- Produces: Server that auto-syncs on startup, market context reads from cache

- [ ] **Step 1: Add candle_store to AppState**

In `api/state.py`, add field:

```python
candle_store: object | None = None
```

- [ ] **Step 2: Create CandleStore + start sync in app.py lifespan**

In `api/app.py` `lifespan()`, after database init:

```python
from tradingbot.data.candle_store import CandleStore
candle_store = CandleStore(resolved_data_dir / "candles.duckdb")

app.state.app_state = AppState(
    ...,
    candle_store=candle_store,
)

# Background sync
from tradingbot.data.kite_data_sync import KiteDataSync
freshness = candle_store.freshness()
if not freshness or any(v < date.today() - timedelta(days=1) for v in freshness.values()):
    # Need Kite client for sync — create lazily when auth is available
    log.info("Data cache stale or empty — sync will start when Kite auth is available")
```

Add `candle_store.close()` to the shutdown path.

- [ ] **Step 3: Remove yfinance from market_data_provider.py**

Remove `import yfinance as yf` and all yfinance-using methods (`get_daily_batch`, `get_intraday`, `get_intraday_batch`, `get_index`, `_split_multi_ticker`). Keep `get_universe()` (uses Kite).

- [ ] **Step 4: Wire CandleStore into MarketContextFetcher (Review Focus #5)**

In `scanner/market_context.py`, ensure the constructor accepts and stores `candle_store`. The fallback path at line 142 (`self._candles.read(...)`) already exists — but the CandleStore interface is different. Add adapter:

```python
# In _read_index, after provider fails:
if self._candle_store is not None:
    try:
        return self._candle_store.read(symbol, "day", days=days)
    except Exception as exc:
        logger.warning("CandleStore index fetch failed for %s: %s", symbol, exc)
```

- [ ] **Step 5: Remove yfinance references from cli.py**

Remove yfinance comments and references in cli.py (lines 284, 339, 341).

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest tests/ -x -q`
Expected: All pass — no yfinance usage in production paths when CandleStore is present

- [ ] **Step 7: Commit**

```bash
git add tradingbot/api/app.py tradingbot/api/state.py tradingbot/data/market_data_provider.py tradingbot/scanner/market_context.py tradingbot/cli.py pyproject.toml
git commit -m "feat(data): server startup sync + yfinance removal + index data via cache"
```

---

### Task 5: Final verification + sync API endpoint

**Files:**
- No new code — verification and optional sync trigger endpoint

- [ ] **Step 1: Verify DuckDB import**

Run: `uv run python -c "import duckdb; print('DuckDB', duckdb.__version__)"`
Expected: DuckDB version printed

- [ ] **Step 2: Verify CandleStore creates and reads**

Run: `uv run python -c "from tradingbot.data.candle_store import CandleStore; from pathlib import Path; s = CandleStore(Path('/tmp/test_candles.duckdb')); print('rows:', s.row_count()); print('freshness:', s.freshness()); s.close()"`
Expected: Empty dicts

- [ ] **Step 3: Verify yfinance no longer imported in production**

Run: `grep -rn "import yfinance\|from yfinance" tradingbot/ --include="*.py" | grep -v __pycache__ | grep -v test`
Expected: No matches (yfinance gone from production code)

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: All pass

- [ ] **Step 5: Commit if cleanup needed**

```bash
git status
```
