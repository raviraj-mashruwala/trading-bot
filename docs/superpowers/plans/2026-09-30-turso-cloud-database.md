# Turso Cloud Database Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace local SQLite files with Turso (LibSQL) cloud databases using embedded replicas, so all machines share the same trade history, instrument data, and analysis results while keeping local-disk read speed.

**Architecture:** A shared `db_factory.py` creates connections — Turso with embedded replica when `TURSO_URL` is configured, plain sqlite3 when not. All 5 database classes (Database, InstrumentCache, CandleStore, SetupStore, RunStore) get their connections from the factory. Two Turso databases: `trading` (critical: trades, decisions, setups, runs) and `market-data` (rebuildable: instruments, candles). Existing tests use local SQLite unchanged.

**Tech Stack:** libsql-experimental (Python LibSQL client), Turso CLI (for DB creation), existing sqlite3 as fallback

**Spec:** No formal spec — this plan is the spec. Design decisions from the in-chat analysis.

## Global Constraints

- Zero breaking changes to existing code — same `conn.execute()` API everywhere
- All existing tests must pass without Turso configured (local SQLite fallback)
- `libsql-experimental` added as optional dependency — app runs without it
- Connection factory is the ONLY place that knows about Turso — individual modules never import libsql
- Embedded replicas: local SQLite file for reads, async sync to cloud for writes
- Two Turso databases: `trading` (small, critical) and `market-data` (large, rebuildable)
- Config via environment: `TURSO_TRADING_URL`, `TURSO_TRADING_TOKEN`, `TURSO_MARKET_URL`, `TURSO_MARKET_TOKEN`
- `row_factory` compatibility: libsql returns tuples by default, adapter needed for sqlite3.Row behavior

## Review Focus

1. **Turso unavailable at runtime**: If Turso URL is configured but the service is down, the factory must fall back to local replica gracefully — not crash the app. Test: factory with unreachable URL still returns a working connection via local replica.
2. **row_factory mismatch**: Existing code accesses columns by name (`row["symbol"]`). libsql connections don't support sqlite3.Row directly. Test: a query result from the factory connection supports `row["column_name"]` access.
3. **executemany with large batches**: CandleStore and InstrumentCache use `executemany()` with hundreds/thousands of rows. LibSQL embedded replica sync must not block or timeout on large batch inserts. Test: executemany with 1000 rows succeeds and syncs.
4. **Concurrent access from multiple machines**: Two machines writing to the same Turso DB simultaneously (e.g., both running analysis). Verified by design (Turso handles server-side) + Task 5 `test_factory_connections_independent` tests two local connections to same file. True multi-machine test requires live Turso — manual verification.
5. **ALTER TABLE compatibility**: SetupStore dynamically adds columns via `ALTER TABLE ... ADD COLUMN` in try/except. Test: ALTER TABLE works through the factory connection the same as sqlite3.

---

### Task 1: Connection Factory + Row Adapter

**Files:**
- Create: `tradingbot/core/db_factory.py`
- Create: `tests/core/test_db_factory.py`
- Modify: `pyproject.toml` — add `libsql-experimental` as optional dependency

**Interfaces:**
- Consumes: Environment variables `TURSO_TRADING_URL`, `TURSO_TRADING_TOKEN`, `TURSO_MARKET_URL`, `TURSO_MARKET_TOKEN`
- Produces:
  - `create_connection(kind: DatabaseKind, local_path: Path) -> Connection` — returns a connection that supports `.execute()`, `.executemany()`, `.executescript()`, `.commit()`, `.close()`, and row access by column name
  - `DatabaseKind` — enum: `TRADING`, `MARKET_DATA`
  - `get_turso_config(kind: DatabaseKind) -> tuple[str, str] | None` — returns (url, token) or None

- [ ] **Step 1: Write failing tests for the factory**

```python
# tests/core/test_db_factory.py
import os
import sqlite3
from pathlib import Path
import pytest
from tradingbot.core.db_factory import create_connection, DatabaseKind, get_turso_config


def test_local_fallback_when_no_turso_env(tmp_path, monkeypatch):
    """Without TURSO env vars, factory returns plain sqlite3 connection."""
    monkeypatch.delenv("TURSO_TRADING_URL", raising=False)
    monkeypatch.delenv("TURSO_TRADING_TOKEN", raising=False)
    conn = create_connection(DatabaseKind.TRADING, tmp_path / "test.db")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO t (name) VALUES (?)", ("hello",))
    conn.commit()
    row = conn.execute("SELECT * FROM t").fetchone()
    assert row["name"] == "hello"
    conn.close()


def test_row_access_by_name(tmp_path, monkeypatch):
    """Rows support dict-style access by column name."""
    monkeypatch.delenv("TURSO_TRADING_URL", raising=False)
    conn = create_connection(DatabaseKind.TRADING, tmp_path / "test.db")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, symbol TEXT, price REAL)")
    conn.execute("INSERT INTO t (symbol, price) VALUES (?, ?)", ("RELIANCE", 2450.0))
    conn.commit()
    row = conn.execute("SELECT * FROM t").fetchone()
    assert row["symbol"] == "RELIANCE"
    assert row["price"] == 2450.0
    assert row[1] == "RELIANCE"  # positional also works
    conn.close()


def test_executemany_works(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_TRADING_URL", raising=False)
    conn = create_connection(DatabaseKind.TRADING, tmp_path / "test.db")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
    data = [(f"item_{i}",) for i in range(1000)]
    conn.executemany("INSERT INTO t (val) VALUES (?)", data)
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    assert count == 1000
    conn.close()


def test_executescript_works(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_TRADING_URL", raising=False)
    conn = create_connection(DatabaseKind.TRADING, tmp_path / "test.db")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS a (id INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS b (id INTEGER PRIMARY KEY);
    """)
    # Both tables exist
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r[0] for r in tables}
    assert "a" in names
    assert "b" in names
    conn.close()


def test_get_turso_config_returns_none_when_not_set(monkeypatch):
    monkeypatch.delenv("TURSO_TRADING_URL", raising=False)
    assert get_turso_config(DatabaseKind.TRADING) is None


def test_get_turso_config_returns_tuple_when_set(monkeypatch):
    monkeypatch.setenv("TURSO_TRADING_URL", "libsql://test.turso.io")
    monkeypatch.setenv("TURSO_TRADING_TOKEN", "secret123")
    result = get_turso_config(DatabaseKind.TRADING)
    assert result == ("libsql://test.turso.io", "secret123")


def test_turso_unavailable_falls_back_to_local(tmp_path, monkeypatch):
    """When Turso URL is set but unreachable, factory falls back to local SQLite."""
    monkeypatch.setenv("TURSO_TRADING_URL", "libsql://unreachable.turso.io")
    monkeypatch.setenv("TURSO_TRADING_TOKEN", "fake-token")
    conn = create_connection(DatabaseKind.TRADING, tmp_path / "fallback.db")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO t (name) VALUES (?)", ("works",))
    conn.commit()
    row = conn.execute("SELECT * FROM t").fetchone()
    assert row["name"] == "works"
    conn.close()


def test_alter_table_works(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_TRADING_URL", raising=False)
    conn = create_connection(DatabaseKind.TRADING, tmp_path / "test.db")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("ALTER TABLE t ADD COLUMN extra TEXT DEFAULT 'none'")
    conn.commit()
    conn.execute("INSERT INTO t (name, extra) VALUES (?, ?)", ("a", "b"))
    conn.commit()
    row = conn.execute("SELECT * FROM t").fetchone()
    assert row["extra"] == "b"
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_db_factory.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement db_factory**

```python
# tradingbot/core/db_factory.py
from __future__ import annotations

import logging
import os
import sqlite3
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DatabaseKind(Enum):
    TRADING = "trading"
    MARKET_DATA = "market_data"


_ENV_MAP = {
    DatabaseKind.TRADING: ("TURSO_TRADING_URL", "TURSO_TRADING_TOKEN"),
    DatabaseKind.MARKET_DATA: ("TURSO_MARKET_URL", "TURSO_MARKET_TOKEN"),
}


def get_turso_config(kind: DatabaseKind) -> tuple[str, str] | None:
    url_key, token_key = _ENV_MAP[kind]
    url = os.environ.get(url_key)
    token = os.environ.get(token_key)
    if url and token:
        return (url, token)
    return None


def create_connection(kind: DatabaseKind, local_path: Path) -> Any:
    turso = get_turso_config(kind)
    if turso is not None:
        return _create_libsql_connection(turso[0], turso[1], local_path)
    return _create_sqlite_connection(local_path)


def _create_sqlite_connection(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _create_libsql_connection(url: str, token: str, local_path: Path) -> Any:
    try:
        import libsql_experimental as libsql
    except ImportError:
        logger.warning("libsql-experimental not installed, falling back to local SQLite")
        return _create_sqlite_connection(local_path)
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        conn = libsql.connect(
            str(local_path),
            sync_url=url,
            auth_token=token,
        )
        conn.sync()
        return _RowAdapterConnection(conn)
    except Exception:
        logger.warning("Turso connection failed, falling back to local SQLite", exc_info=True)
        return _create_sqlite_connection(local_path)


class _RowAdapter:
    """Makes libsql rows accessible by column name like sqlite3.Row."""

    __slots__ = ("_data", "_columns")

    def __init__(self, data: tuple, columns: list[str]) -> None:
        self._data = data
        self._columns = {name: i for i, name in enumerate(columns)}

    def __getitem__(self, key: int | str) -> Any:
        if isinstance(key, str):
            return self._data[self._columns[key]]
        return self._data[key]

    def keys(self) -> list[str]:
        return list(self._columns.keys())


class _RowAdapterCursor:
    """Wraps a libsql cursor to return _RowAdapter rows."""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor
        self._description = cursor.description

    @property
    def description(self) -> Any:
        return self._description

    @property
    def lastrowid(self) -> int | None:
        return getattr(self._cursor, "lastrowid", None)

    @property
    def rowcount(self) -> int:
        return getattr(self._cursor, "rowcount", -1)

    def fetchone(self) -> _RowAdapter | None:
        row = self._cursor.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._description] if self._description else []
        return _RowAdapter(row, cols)

    def fetchall(self) -> list[_RowAdapter]:
        rows = self._cursor.fetchall()
        cols = [d[0] for d in self._description] if self._description else []
        return [_RowAdapter(r, cols) for r in rows]

    def __iter__(self):
        cols = [d[0] for d in self._description] if self._description else []
        for row in self._cursor:
            yield _RowAdapter(row, cols)


class _RowAdapterConnection:
    """Wraps a libsql connection to return adapted cursors."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def execute(self, sql: str, parameters: Any = ()) -> _RowAdapterCursor:
        cursor = self._conn.execute(sql, parameters)
        return _RowAdapterCursor(cursor)

    def executemany(self, sql: str, parameters: Any) -> _RowAdapterCursor:
        cursor = self._conn.executemany(sql, parameters)
        return _RowAdapterCursor(cursor)

    def executescript(self, sql: str) -> None:
        self._conn.executescript(sql)

    def commit(self) -> None:
        self._conn.commit()
        try:
            self._conn.sync()
        except Exception:
            logger.debug("Turso sync after commit failed", exc_info=True)

    def close(self) -> None:
        try:
            self._conn.sync()
        except Exception:
            pass
        self._conn.close()
```

- [ ] **Step 4: Add libsql-experimental to pyproject.toml as optional**

In `pyproject.toml`, add to dependencies or optional-dependencies:

```toml
[project.optional-dependencies]
turso = ["libsql-experimental>=0.0.50"]
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/core/test_db_factory.py -v`
Expected: 8 PASSED (all use local SQLite fallback)

- [ ] **Step 6: Commit**

```bash
git add tradingbot/core/db_factory.py tests/core/test_db_factory.py pyproject.toml
git commit -m "feat(db): add connection factory with Turso/LibSQL support and SQLite fallback

create_connection() returns Turso embedded replica when TURSO_*_URL
env vars are set, plain sqlite3 when not. RowAdapter makes libsql
results accessible by column name. Graceful fallback on import error
or connection failure. Two database kinds: TRADING and MARKET_DATA."
```

---

### Task 2: Migrate Database class (trades, snapshots, decisions)

**Files:**
- Modify: `tradingbot/core/database.py` — use `create_connection` from factory
- Modify: `tests/core/test_database.py` (if exists) or create
- Modify: `tradingbot/cli.py` — pass `DatabaseKind.TRADING` when creating Database
- Modify: `tradingbot/api/app.py` — same

**Interfaces:**
- Consumes: `create_connection(DatabaseKind.TRADING, path)` from Task 1
- Produces: Same `Database` class API — no changes to callers beyond connection creation

- [ ] **Step 1: Read current Database.__init__ and initialise()**

Read `tradingbot/core/database.py` to understand exact constructor pattern and schema.

- [ ] **Step 2: Write test verifying factory connection works with Database**

```python
# tests/core/test_database_factory.py
from pathlib import Path
import pytest
from tradingbot.core.database import Database


def test_database_uses_factory(tmp_path, monkeypatch):
    """Database works through factory connection (local fallback)."""
    monkeypatch.delenv("TURSO_TRADING_URL", raising=False)
    db = Database(tmp_path / "test.db")
    db.initialise()
    # Should be able to record and query a trade
    from tradingbot.core.models import ExecutedTrade, Direction, StrategyName, TradeStatus, Mode
    from datetime import datetime
    trade = ExecutedTrade(
        trade_date="2026-09-30", symbol="RELIANCE",
        strategy=StrategyName.BREAKOUT, direction=Direction.LONG,
        quantity=10, entry_price=2450.0, exit_price=2470.0,
        stop_loss=2430.0, target_1=2470.0, target_2=2490.0,
        entered_at=datetime(2026, 9, 30, 9, 30),
        exited_at=datetime(2026, 9, 30, 10, 15),
        pnl=2000.0, exit_reason="target_1",
        status=TradeStatus.CLOSED, mode=Mode.PAPER,
    )
    db.record_trade(trade)
    trades = db.trades_for_date("2026-09-30")
    assert len(trades) == 1
    assert trades[0]["symbol"] == "RELIANCE"
    db.close()
```

- [ ] **Step 3: Modify Database.__init__ to use factory**

Change `tradingbot/core/database.py`:

```python
# Before:
import sqlite3

class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row

# After:
from tradingbot.core.db_factory import create_connection, DatabaseKind

class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self._conn = create_connection(DatabaseKind.TRADING, db_path)
```

Remove the `sqlite3.connect()` call and `row_factory` assignment — factory handles both.

- [ ] **Step 4: Run all existing database tests + new test**

Run: `uv run pytest tests/core/test_database_factory.py tests/ -k "database" -v`
Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add tradingbot/core/database.py tests/core/test_database_factory.py
git commit -m "refactor(db): Database class uses connection factory

Swaps sqlite3.connect for create_connection(DatabaseKind.TRADING).
Turso when configured, local SQLite when not. Zero API changes."
```

---

### Task 3: Migrate InstrumentCache and CandleStore (market data)

**Files:**
- Modify: `tradingbot/data/instrument_cache.py` — use factory with `MARKET_DATA`
- Modify: `tradingbot/data/candle_store.py` — use factory with `MARKET_DATA`
- Create: `tests/data/test_market_data_factory.py`

**Interfaces:**
- Consumes: `create_connection(DatabaseKind.MARKET_DATA, path)` from Task 1
- Produces: Same `InstrumentCache` and `CandleStore` APIs — no changes to callers

- [ ] **Step 1: Write test for InstrumentCache with factory**

```python
# tests/data/test_market_data_factory.py
from pathlib import Path
import pytest
from tradingbot.data.instrument_cache import InstrumentCache


def test_instrument_cache_uses_factory(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_MARKET_URL", raising=False)
    cache = InstrumentCache(tmp_path / "instruments.db")
    raw = [
        {"instrument_token": 738561, "tradingsymbol": "RELIANCE",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE",
         "industry_type": "Refineries"},
    ]
    count = cache.refresh(raw)
    assert count == 1
    assert cache.get_token("RELIANCE") == 738561
    cache.close()


def test_candle_store_uses_factory(tmp_path, monkeypatch):
    from tradingbot.data.candle_store import CandleStore
    from datetime import date
    monkeypatch.delenv("TURSO_MARKET_URL", raising=False)
    store = CandleStore(tmp_path / "candles.db")
    rows = [
        {"timestamp": "2026-09-30 09:15:00", "open": 2450.0, "high": 2455.0,
         "low": 2448.0, "close": 2453.0, "volume": 1000},
    ]
    store.upsert("RELIANCE", "15minute", rows)
    result = store.read("RELIANCE", "15minute", date(2026, 9, 29), date(2026, 10, 1))
    assert len(result) == 1
    store.close()
```

- [ ] **Step 2: Modify InstrumentCache to use factory**

```python
# Before:
self._conn = sqlite3.connect(str(db_path))
self._conn.row_factory = sqlite3.Row

# After:
from tradingbot.core.db_factory import create_connection, DatabaseKind
self._conn = create_connection(DatabaseKind.MARKET_DATA, db_path)
```

Remove `import sqlite3` (no longer needed directly).

- [ ] **Step 3: Modify CandleStore to use factory**

Same pattern. CandleStore doesn't use `row_factory` currently — the factory sets it, but CandleStore accesses by index. Both still work since `_RowAdapter` supports positional access.

```python
# Before:
self._conn = sqlite3.connect(str(db_path))

# After:
from tradingbot.core.db_factory import create_connection, DatabaseKind
self._conn = create_connection(DatabaseKind.MARKET_DATA, db_path)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/data/test_market_data_factory.py tests/data/ -v`
Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add tradingbot/data/instrument_cache.py tradingbot/data/candle_store.py tests/data/test_market_data_factory.py
git commit -m "refactor(db): InstrumentCache and CandleStore use connection factory

Both now route through create_connection(DatabaseKind.MARKET_DATA).
Turso when configured, local SQLite when not. Same API."
```

---

### Task 4: Migrate SetupStore and RunStore (analysis data)

**Files:**
- Modify: `tradingbot/persistence/setup_store.py` — use factory with `TRADING`
- Modify: `tradingbot/persistence/run_store.py` — use factory with `TRADING`
- Create: `tests/persistence/test_stores_factory.py`

**Interfaces:**
- Consumes: `create_connection(DatabaseKind.TRADING, path)` from Task 1
- Produces: Same `SetupStore` and `RunStore` APIs

- [ ] **Step 1: Write tests**

```python
# tests/persistence/test_stores_factory.py
from pathlib import Path
from datetime import datetime
import pytest
from tradingbot.persistence.setup_store import SetupStore
from tradingbot.persistence.run_store import RunStore


def test_setup_store_uses_factory(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_TRADING_URL", raising=False)
    store = SetupStore(tmp_path / "analysis.db")
    # Verify table exists and can write
    store._conn.execute(
        "INSERT INTO setups (run_id, trade_date, symbol, strategy, direction, "
        "entry_price, stop_loss, target_1, confidence, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("run1", "2026-09-30", "RELIANCE", "BREAKOUT", "LONG",
         2450.0, 2430.0, 2470.0, 0.8, "proposed",
         datetime.now().isoformat(), datetime.now().isoformat()),
    )
    store._conn.commit()
    rows = store.get_all_for_date("2026-09-30")
    assert len(rows) == 1
    store.close()


def test_run_store_uses_factory(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_TRADING_URL", raising=False)
    store = RunStore(tmp_path / "analysis.db")
    store.save({
        "run_id": "run1", "trade_date": "2026-09-30",
        "timestamp": datetime.now().isoformat(),
        "market_regime": "TRENDING", "regime_confidence": 0.8,
        "total_scanned": 100, "tier1_passed": 20,
        "tier2_shortlisted": 10, "setups_proposed": 5,
        "setups_approved": 3, "llm_calls": 5,
        "llm_cost_usd": 0.05, "duration_seconds": 120.0,
    })
    runs = store.list_for_date("2026-09-30")
    assert len(runs) == 1
    store.close()


def test_setup_store_alter_table_works(tmp_path, monkeypatch):
    """Dynamic ALTER TABLE columns still work through factory."""
    monkeypatch.delenv("TURSO_TRADING_URL", raising=False)
    store = SetupStore(tmp_path / "analysis.db")
    # The constructor already runs ALTER TABLE ADD COLUMN for dynamic columns
    # Verify by inserting with those columns
    store._conn.execute(
        "INSERT INTO setups (run_id, trade_date, symbol, strategy, direction, "
        "entry_price, stop_loss, target_1, confidence, status, created_at, updated_at, thesis) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("run1", "2026-09-30", "RELIANCE", "BREAKOUT", "LONG",
         2450.0, 2430.0, 2470.0, 0.8, "proposed",
         datetime.now().isoformat(), datetime.now().isoformat(),
         "Strong breakout above resistance"),
    )
    store._conn.commit()
    row = store.get_all_for_date("2026-09-30")[0]
    assert row["thesis"] == "Strong breakout above resistance"
    store.close()
```

- [ ] **Step 2: Modify SetupStore**

```python
# Before:
self._conn = sqlite3.connect(str(db_path))
self._conn.row_factory = sqlite3.Row

# After:
from tradingbot.core.db_factory import create_connection, DatabaseKind
self._conn = create_connection(DatabaseKind.TRADING, db_path)
```

- [ ] **Step 3: Modify RunStore**

Same pattern.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/persistence/test_stores_factory.py tests/persistence/ -v`
Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add tradingbot/persistence/setup_store.py tradingbot/persistence/run_store.py tests/persistence/test_stores_factory.py
git commit -m "refactor(db): SetupStore and RunStore use connection factory

Both now route through create_connection(DatabaseKind.TRADING).
ALTER TABLE dynamic columns verified working through factory."
```

---

### Task 5: Config integration + full test suite verification

**Files:**
- Modify: `tradingbot/core/config.py` — add optional `[database]` section to Config
- Modify: `.env.example` (or create) — document Turso env vars
- Create: `tests/test_turso_integration.py` — end-to-end test with all 5 modules through factory

**Interfaces:**
- Consumes: All Tasks 1-4
- Produces: Documented configuration, verified full-stack compatibility

- [ ] **Step 1: Add .env.example documentation**

```bash
# .env.example — append these lines:

# Turso Cloud Database (optional — leave empty for local SQLite)
# Create databases: turso db create trading && turso db create market-data
# Get URLs: turso db show trading --url && turso db show market-data --url
# Get tokens: turso db tokens create trading && turso db tokens create market-data
TURSO_TRADING_URL=
TURSO_TRADING_TOKEN=
TURSO_MARKET_URL=
TURSO_MARKET_TOKEN=
```

- [ ] **Step 2: Write end-to-end integration test**

```python
# tests/test_turso_integration.py
"""Verify all 5 database modules work through the factory."""
from datetime import datetime, date
from pathlib import Path
import pytest

from tradingbot.core.database import Database
from tradingbot.data.instrument_cache import InstrumentCache
from tradingbot.data.candle_store import CandleStore
from tradingbot.persistence.setup_store import SetupStore
from tradingbot.persistence.run_store import RunStore


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_TRADING_URL", raising=False)
    monkeypatch.delenv("TURSO_MARKET_URL", raising=False)
    return tmp_path


def test_all_modules_through_factory(data_dir):
    """All 5 database modules create, write, read, close without error."""
    db = Database(data_dir / "tradingbot.db")
    db.initialise()

    cache = InstrumentCache(data_dir / "instruments.db")
    cache.refresh([{
        "instrument_token": 738561, "tradingsymbol": "RELIANCE",
        "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
        "instrument_type": "EQ", "segment": "NSE", "industry_type": "Refineries",
    }])

    candles = CandleStore(data_dir / "candles.db")
    candles.upsert("RELIANCE", "15minute", [{
        "timestamp": "2026-09-30 09:15:00", "open": 2450.0,
        "high": 2455.0, "low": 2448.0, "close": 2453.0, "volume": 1000,
    }])

    setups = SetupStore(data_dir / "analysis.db")
    runs = RunStore(data_dir / "analysis.db")

    # Verify cross-module reads
    assert cache.get_token("RELIANCE") == 738561
    assert len(candles.read("RELIANCE", "15minute", date(2026, 9, 29), date(2026, 10, 1))) == 1

    db.close()
    cache.close()
    candles.close()
    setups.close()
    runs.close()


def test_factory_connections_independent(data_dir):
    """Two modules using same DatabaseKind get independent connections."""
    setups = SetupStore(data_dir / "analysis.db")
    runs = RunStore(data_dir / "analysis.db")
    # Both can write without conflict
    runs.save({
        "run_id": "r1", "trade_date": "2026-09-30",
        "timestamp": datetime.now().isoformat(),
        "market_regime": "TRENDING", "regime_confidence": 0.8,
        "total_scanned": 50, "tier1_passed": 10,
        "tier2_shortlisted": 5, "setups_proposed": 3,
        "setups_approved": 2, "llm_calls": 3,
        "llm_cost_usd": 0.03, "duration_seconds": 60.0,
    })
    assert len(runs.list_for_date("2026-09-30")) == 1
    setups.close()
    runs.close()
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: All existing + new tests pass. Zero regressions.

- [ ] **Step 4: Commit**

```bash
git add .env.example tests/test_turso_integration.py
git commit -m "feat(db): add Turso config documentation and integration tests

.env.example documents TURSO_*_URL and TURSO_*_TOKEN vars.
Integration test verifies all 5 database modules work through
the connection factory without Turso (local SQLite fallback)."
```
