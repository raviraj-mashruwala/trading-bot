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

    def _ensure_connected(self) -> duckdb.DuckDBPyConnection:
        try:
            self._conn.execute("SELECT 1")
        except Exception:
            log.warning("DuckDB connection lost, reconnecting to %s", self._path)
            self._conn = duckdb.connect(self._path)
            self._conn.execute(_SCHEMA)
        return self._conn

    def read(
        self,
        symbol: str,
        interval: str,
        days: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> pd.DataFrame:
        conditions = ["symbol = $1 AND interval = $2"]
        params: list[Any] = [symbol, interval]
        idx = 3

        if from_date is not None:
            conditions.append(f"timestamp >= ${idx}")
            params.append(datetime.combine(from_date, datetime.min.time()))
            idx += 1
        if to_date is not None:
            conditions.append(f"timestamp <= ${idx}")
            params.append(datetime.combine(to_date, datetime.max.time().replace(microsecond=0)))
            idx += 1

        where = " AND ".join(conditions)
        query = f"SELECT timestamp, open, high, low, close, volume FROM candles WHERE {where} ORDER BY timestamp"
        df = self._ensure_connected().execute(query, params).fetchdf()

        if days is not None and not df.empty:
            if interval == "day":
                df = df.tail(days)
            else:
                cutoff = df["timestamp"].max() - timedelta(days=days * 2)
                df = df[df["timestamp"] >= cutoff]

        return df.reset_index(drop=True)

    def read_batch(
        self,
        symbols: list[str],
        interval: str,
        days: int = 30,
    ) -> dict[str, pd.DataFrame]:
        if not symbols:
            return {}
        cutoff = datetime.now() - timedelta(days=days * 2)
        query = """
            SELECT symbol, timestamp, open, high, low, close, volume
            FROM candles
            WHERE symbol IN (SELECT UNNEST($1::VARCHAR[]))
              AND interval = $2
              AND timestamp >= $3
            ORDER BY symbol, timestamp
        """
        df = self._ensure_connected().execute(query, [symbols, interval, cutoff]).fetchdf()
        if df.empty:
            return {}
        result = {}
        for sym, group in df.groupby("symbol"):
            result[str(sym)] = group.drop(columns=["symbol"]).reset_index(drop=True)
        return result

    def write(self, symbol: str, interval: str, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        before = self._count(symbol, interval)
        records = []
        for _, row in df.iterrows():
            records.append((
                symbol, interval,
                row["timestamp"] if isinstance(row["timestamp"], datetime) else datetime.combine(row["timestamp"], datetime.min.time()),
                float(row["open"]), float(row["high"]),
                float(row["low"]), float(row["close"]),
                int(row["volume"]),
            ))
        self._ensure_connected().executemany(
            "INSERT OR IGNORE INTO candles (symbol, interval, timestamp, open, high, low, close, volume) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            records,
        )
        after = self._count(symbol, interval)
        return after - before

    def write_batch(self, data: dict[str, pd.DataFrame], interval: str) -> int:
        total = 0
        for symbol, df in data.items():
            total += self.write(symbol, interval, df)
        return total

    def last_date(self, symbol: str, interval: str) -> date | None:
        row = self._ensure_connected().execute(
            "SELECT MAX(timestamp) as last_ts FROM candles WHERE symbol = $1 AND interval = $2",
            [symbol, interval],
        ).fetchone()
        if row and row[0] is not None:
            ts = row[0]
            return ts.date() if isinstance(ts, datetime) else ts
        return None

    def symbols_with_data(self, interval: str) -> list[str]:
        rows = self._ensure_connected().execute(
            "SELECT DISTINCT symbol FROM candles WHERE interval = $1 ORDER BY symbol",
            [interval],
        ).fetchall()
        return [r[0] for r in rows]

    def freshness(self) -> dict[str, date]:
        rows = self._ensure_connected().execute(
            "SELECT interval, MAX(timestamp) as latest FROM candles GROUP BY interval"
        ).fetchall()
        result = {}
        for r in rows:
            ts = r[1]
            result[r[0]] = ts.date() if isinstance(ts, datetime) else ts
        return result

    def row_count(self) -> dict[str, int]:
        rows = self._ensure_connected().execute(
            "SELECT interval, COUNT(*) as cnt FROM candles GROUP BY interval"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    # Expected candles per full trading day (NSE 9:15–15:30 = 6h15m)
    _EXPECTED_PER_DAY = {"15m": 25, "5m": 75, "1m": 375, "day": 1}

    def find_gaps(
        self,
        symbol: str,
        interval: str,
        threshold: float = 0.08,
    ) -> list[tuple[date, int, int]]:
        """Find trading days with fewer candles than expected.

        Returns list of (date, actual_count, expected_count) for days below
        threshold * expected. Only checks days between the first and last
        candle for this symbol/interval.
        """
        expected = self._EXPECTED_PER_DAY.get(interval, 25)
        min_count = int(expected * threshold)
        rows = self._ensure_connected().execute(
            """
            SELECT CAST(timestamp AS DATE) AS day, COUNT(*) AS cnt
            FROM candles
            WHERE symbol = $1 AND interval = $2
            GROUP BY day
            HAVING cnt < $3
            ORDER BY day
            """,
            [symbol, interval, min_count],
        ).fetchall()
        return [(r[0], r[1], expected) for r in rows]

    def date_range(self, symbol: str, interval: str) -> tuple[date | None, date | None]:
        """Return (first_date, last_date) for a symbol/interval."""
        row = self._ensure_connected().execute(
            "SELECT MIN(CAST(timestamp AS DATE)), MAX(CAST(timestamp AS DATE)) "
            "FROM candles WHERE symbol = $1 AND interval = $2",
            [symbol, interval],
        ).fetchone()
        if row and row[0] is not None:
            return (row[0], row[1])
        return (None, None)

    def gap_summary(self, interval: str, threshold: float = 0.08) -> dict[str, list[tuple[date, int, int]]]:
        """Find gaps across all symbols for a given interval."""
        symbols = self.symbols_with_data(interval)
        result = {}
        for sym in symbols:
            gaps = self.find_gaps(sym, interval, threshold)
            if gaps:
                result[sym] = gaps
        return result

    def purge_intervals(self, intervals: list[str]) -> dict[str, int]:
        """Delete all rows for given intervals. Returns {interval: rows_deleted}."""
        result = {}
        for iv in intervals:
            before = self._ensure_connected().execute(
                "SELECT COUNT(*) FROM candles WHERE interval = $1", [iv]
            ).fetchone()[0]
            self._ensure_connected().execute("DELETE FROM candles WHERE interval = $1", [iv])
            result[iv] = before
        return result

    def _count(self, symbol: str, interval: str) -> int:
        row = self._ensure_connected().execute(
            "SELECT COUNT(*) FROM candles WHERE symbol = $1 AND interval = $2",
            [symbol, interval],
        ).fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        self._conn.close()
