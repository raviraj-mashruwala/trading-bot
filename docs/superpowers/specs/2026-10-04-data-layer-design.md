# Data Layer Redesign: Local OHLCV Cache with Kite Historical API

**Date:** 2026-10-04
**Scope:** Replace yfinance with local DuckDB cache backed by Kite historical API
**Priority:** Critical — blocks live trading

---

## 1. Problem Statement

The analysis pipeline downloads 30 days of daily OHLCV for ~1500 stocks from yfinance on every run (~15 min). The user pays for Kite Connect which provides the same data (and better — exchange-grade). No local cache exists despite `CandleStore` being designed but never built. Backtesting uses only 60 days of 15-min candles — statistically thin for live money decisions.

## 2. Goals

- **Zero yfinance dependency** — delete it entirely
- **Kite is the single data source** — exchange-grade NSE data
- **Local DuckDB cache** — ~1.9 GB, all reads instant
- **Multi-timeframe:** daily + 15m + 5m + 1m
- **Deep history:** daily 11yr, 15m 11yr, 5m 5yr, 1m 5yr
- **Initial fill ~63 min** — background, resumable, never blocks server
- **Daily sync ~5-8 min** — automatic on server start
- **Analysis runs in < 30 seconds** — zero API calls, all local reads

## 3. Non-Goals

- Real-time tick storage (live ticks stay in-memory via existing ticker)
- Options data / derivatives
- Multi-exchange (BSE, MCX) — NSE only for now
- Migrating existing trade/setup databases to DuckDB (stay on SQLite)

---

## 4. Architecture

### 4.1 Component Map

```
NEW FILES:
  data/candle_store.py           — DuckDB OHLCV storage with read/write interface
  data/kite_data_sync.py         — Paginated Kite fetcher with resume/retry
  tests/data/test_candle_store.py
  tests/data/test_kite_data_sync.py

MODIFIED FILES:
  data/market_data_provider.py   — Remove yfinance methods, keep get_universe (Kite)
  analysis/pipeline.py           — Replace 4 yfinance fetch points with CandleStore
  api/analysis_routes.py         — Pass CandleStore to pipeline
  api/app.py                     — Start background sync on server startup
  pyproject.toml                 — Remove yfinance, add duckdb

DELETE:
  All yfinance imports and usage across codebase
```

### 4.2 Data Flow

```
SERVER START:
  1. Open/create DuckDB file (data/candles.duckdb)
  2. Check freshness: last sync date per interval
  3. If stale (>1 day): kick off background KiteDataSync
  4. If empty: kick off full initial fill (background, resumable)
  5. Server ready immediately — sync runs in background

ANALYSIS RUN:
  1. CandleStore.read_daily_batch(symbols) → DataFrame dict (instant)
  2. CandleStore.read(symbol, "15m", days=200) → DataFrame (instant)
  3. CandleStore.read(symbol, "5m", days=100) → DataFrame (instant)
  4. Zero Kite API calls during analysis
  5. Cache miss for unknown symbol → on-demand Kite fetch + cache

DAILY SYNC (background, automatic):
  1. Fetch yesterday's candles for all cached stocks
  2. Insert into DuckDB (append-only, no duplicates)
  3. Update sync metadata
  4. ~5-8 min at 3 req/sec
```

### 4.3 DuckDB Schema

```sql
CREATE TABLE candles (
    symbol      VARCHAR NOT NULL,
    interval    VARCHAR NOT NULL,  -- 'day', '1m', '5m', '15m'
    timestamp   TIMESTAMP NOT NULL,
    open        DOUBLE NOT NULL,
    high        DOUBLE NOT NULL,
    low         DOUBLE NOT NULL,
    close       DOUBLE NOT NULL,
    volume      BIGINT NOT NULL,
    PRIMARY KEY (symbol, interval, timestamp)
);

CREATE TABLE sync_metadata (
    symbol      VARCHAR NOT NULL,
    interval    VARCHAR NOT NULL,
    last_date   DATE NOT NULL,
    row_count   INTEGER NOT NULL,
    updated_at  TIMESTAMP NOT NULL,
    PRIMARY KEY (symbol, interval)
);
```

Single table for all intervals — DuckDB handles 100M+ rows efficiently with columnar storage. The `sync_metadata` table tracks last-fetched date per stock per interval for resumable syncs.

---

## 5. Component Specifications

### 5.1 CandleStore (`data/candle_store.py`)

```python
class CandleStore:
    def __init__(self, db_path: Path):
        """Open or create DuckDB file. Create tables if not exist."""

    def read(self, symbol: str, interval: str, days: int = None,
             from_date: date = None, to_date: date = None) -> pd.DataFrame:
        """Read OHLCV for one symbol+interval. Returns DataFrame with
        columns: timestamp, open, high, low, close, volume."""

    def read_batch(self, symbols: list[str], interval: str,
                   days: int = 30) -> dict[str, pd.DataFrame]:
        """Read daily OHLCV for multiple symbols. Returns {symbol: df}.
        Used by Tier 1 screening for all 1500 stocks."""

    def write(self, symbol: str, interval: str, df: pd.DataFrame) -> int:
        """Append OHLCV rows. Deduplicates on (symbol, interval, timestamp).
        Returns count of new rows inserted."""

    def write_batch(self, data: dict[str, pd.DataFrame], interval: str) -> int:
        """Bulk write for multiple symbols. Used during sync."""

    def last_date(self, symbol: str, interval: str) -> date | None:
        """Last timestamp for a symbol+interval. Used by sync to know
        where to resume."""

    def symbols_with_data(self, interval: str) -> list[str]:
        """All symbols that have data for an interval."""

    def freshness(self) -> dict[str, date]:
        """Latest date across all symbols per interval. For health checks."""

    def row_count(self) -> dict[str, int]:
        """Total rows per interval. For monitoring."""

    def close(self) -> None:
        """Close DuckDB connection."""
```

**Design choices:**
- Returns Pandas DataFrames — matches existing pipeline expectations
- Lowercase columns (`open`, `high`, `low`, `close`, `volume`, `timestamp`)
- Deduplication on write — safe to re-fetch overlapping date ranges
- No ORM — direct DuckDB SQL for speed

### 5.2 KiteDataSync (`data/kite_data_sync.py`)

```python
class KiteDataSync:
    def __init__(self, kite_client: DataKiteClient, candle_store: CandleStore,
                 instrument_cache: InstrumentCache):
        """Uses existing DataKiteClient for rate-limited Kite calls."""

    async def initial_fill(self, progress_callback=None) -> SyncReport:
        """Full historical fill. Paginated, resumable, background-safe.
        
        Steps:
        1. Get all instruments from Kite
        2. Fetch daily for all 1500 (11 years, paginated in 2000-day chunks)
        3. Run liquidity filter to identify ~300 liquid stocks
        4. Fetch 15m for 300 (11 years, paginated in 200-day chunks)
        5. Fetch 5m for 300 (5 years, paginated in 100-day chunks)
        6. Fetch 1m for 300 (5 years, paginated in 60-day chunks)
        
        Each stock+interval is independently resumable via sync_metadata.
        """

    async def daily_sync(self, progress_callback=None) -> SyncReport:
        """Incremental: fetch only new candles since last sync date.
        
        For each symbol+interval in sync_metadata:
          last = candle_store.last_date(symbol, interval)
          fetch from last+1 to today
          write to store
        """

    async def fetch_on_demand(self, symbol: str, intervals: list[str]) -> None:
        """Fetch a single stock's data on demand (cache miss during analysis)."""

    def estimate_fill_time(self) -> dict:
        """Estimate remaining fill time based on sync_metadata gaps."""
```

**Pagination logic:**
```python
KITE_LIMITS = {
    "day": 2000,    # days per request
    "15m": 200,
    "5m": 100,
    "1m": 60,
}

TARGET_DEPTHS = {
    "day": {"years": 11, "stocks": "all"},       # ~1500
    "15m": {"years": 11, "stocks": "liquid"},     # ~300
    "5m":  {"years": 5,  "stocks": "liquid"},     # ~300
    "1m":  {"years": 5,  "stocks": "liquid"},     # ~300
}
```

For each stock+interval:
```
start_date = max(2015-01-01, last_synced_date + 1)
end_date = today
chunk through date range in KITE_LIMITS[interval] chunks
for each chunk: kite_client.fetch_historical(token, interval, from, to)
write to candle_store
update sync_metadata
```

**Resilience:**
- Per-stock retry: 3 attempts with exponential backoff (1s, 2s, 4s)
- Per-stock failure logged, doesn't stop other stocks
- Resume: checks `sync_metadata.last_date` — skips already-fetched ranges
- Progress callback for UI/logging: `"RELIANCE 1m: 2021-2022 done (45/300 stocks)"`
- Runs in asyncio background task — never blocks server

**Liquid stock selection:**
- After daily data fetched for all 1500
- Apply same liquidity filter thresholds from `ScreeningConfig`: min_volume, min_price, max_price, min_market_cap_cr
- Use last 20 trading days from daily cache to compute avg_volume
- ~300 stocks pass — these get intraday data
- List refreshes on each daily sync

### 5.3 Pipeline Rewire (`analysis/pipeline.py`)

Four yfinance fetch points replaced:

| Line | Current (yfinance) | After (CandleStore) |
|------|-------------------|---------------------|
| 392 | `provider.get_daily_batch(symbols, 30)` | `candle_store.read_batch(symbols, "day", 30)` |
| 552 | `provider.get_intraday(sym, "15m", 60)` | `candle_store.read(sym, "15m", days=60)` |
| 612 | `provider.get_daily_batch(subset, 30)` | `candle_store.read_batch(subset, "day", 30)` |
| 722 | `provider.get_intraday(sym, "15m", 60)` | `candle_store.read(sym, "15m", days=60)` |

**Cache miss handling:** If `candle_store.read()` returns empty for a symbol, trigger `sync.fetch_on_demand(symbol, ["day", "15m"])` — one-time Kite fetch, cached for next time.

**Constructor change:**
```python
def __init__(self, ..., candle_store: CandleStore = None):
```

### 5.4 Server Startup (`api/app.py`)

```python
@asynccontextmanager
async def lifespan(app):
    # ... existing startup ...
    
    # Start background data sync
    candle_store = CandleStore(Path(data_dir) / "candles.duckdb")
    state.candle_store = candle_store
    
    freshness = candle_store.freshness()
    if not freshness:
        # First run — kick off initial fill
        asyncio.create_task(sync.initial_fill(progress_callback=log_progress))
    elif any_stale(freshness):
        # Daily sync needed
        asyncio.create_task(sync.daily_sync(progress_callback=log_progress))
    
    yield
    candle_store.close()
```

### 5.5 yfinance Removal

- Remove `yfinance` from `pyproject.toml` dependencies
- Remove `import yfinance` from `data/market_data_provider.py`
- Remove methods: `get_daily_batch`, `get_intraday`, `get_intraday_batch`, `get_index`
- Keep `get_universe()` — still uses Kite instruments API
- Remove yfinance from `scanner/market_context.py` (Nifty/VIX data from Kite or cache)
- Delete any `yf.download` or `yf.Ticker` calls

---

## 6. Test Plan

### 6.1 test_candle_store.py (~8 tests)

| # | Test |
|---|------|
| 1 | Create store, write daily data, read it back |
| 2 | Write deduplicates on (symbol, interval, timestamp) |
| 3 | read_batch returns dict of DataFrames for multiple symbols |
| 4 | read with days parameter limits rows |
| 5 | read with from_date/to_date filters correctly |
| 6 | last_date returns correct date |
| 7 | freshness returns per-interval latest date |
| 8 | Empty read returns empty DataFrame (not None) |

### 6.2 test_kite_data_sync.py (~6 tests)

| # | Test |
|---|------|
| 1 | Pagination chunks date range correctly |
| 2 | Resume skips already-fetched ranges |
| 3 | Per-stock failure doesn't stop sync |
| 4 | Retry on Kite API error (3 attempts) |
| 5 | Liquid stock selection from daily data |
| 6 | Daily sync fetches only since last_date |

---

## 7. Migration Path

1. Build CandleStore + KiteDataSync (new files, no existing code changes)
2. Run initial fill (background, ~63 min)
3. Rewire pipeline to use CandleStore
4. Remove yfinance
5. Verify: analysis runs in < 30 sec with all data local

Steps 1-2 can ship independently. Steps 3-4 are the breaking change. Step 5 is verification.

---

## 8. Estimated Effort

| Task | Effort |
|------|--------|
| CandleStore (DuckDB schema + read/write) | 0.5 day |
| KiteDataSync (pagination + resume + retry) | 1 day |
| Pipeline rewire + yfinance removal | 0.5 day |
| Server startup wiring + background sync | 0.5 day |
| Tests (14 total) | included |
| **Total** | **~2.5 days** |

## 9. Storage

| What | Size |
|------|------|
| Initial fill | ~1.9 GB |
| Growth | ~1 GB/year |
| Location | `data/candles.duckdb` |
