from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.core.db_factory import DatabaseKind, create_connection


class CandleStore:
    """SQLite-backed store for OHLCV candle data across timeframes."""

    def __init__(self, db_path: Path):
        self._conn = create_connection(DatabaseKind.MARKET_DATA, Path(db_path))
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS candles (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER NOT NULL,
                PRIMARY KEY (symbol, interval, timestamp)
            )
        """)
        self._conn.commit()

    def upsert(self, symbol: str, interval: str, candles: list[dict[str, Any]]) -> int:
        self._conn.executemany(
            "INSERT OR REPLACE INTO candles "
            "(symbol, interval, timestamp, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(symbol, interval, c["date"].isoformat(), c["open"], c["high"],
              c["low"], c["close"], c["volume"]) for c in candles],
        )
        self._conn.commit()
        return len(candles)

    def read(
        self, symbol: str, interval: str,
        from_dt: datetime, to_dt: datetime,
    ) -> pd.DataFrame:
        rows = self._conn.execute(
            "SELECT timestamp, open, high, low, close, volume FROM candles "
            "WHERE symbol = ? AND interval = ? AND timestamp >= ? AND timestamp <= ? "
            "ORDER BY timestamp",
            (symbol, interval, from_dt.isoformat(), to_dt.isoformat()),
        ).fetchall()
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        return df

    def last_timestamp(self, symbol: str, interval: str) -> datetime | None:
        row = self._conn.execute(
            "SELECT MAX(timestamp) FROM candles WHERE symbol = ? AND interval = ?",
            (symbol, interval),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return datetime.fromisoformat(row[0])

    def close(self) -> None:
        self._conn.close()
