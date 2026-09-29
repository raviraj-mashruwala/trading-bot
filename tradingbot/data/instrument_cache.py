from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class InstrumentCache:
    """SQLite-backed cache for NSE instrument metadata."""

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS instruments (
                token INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                exchange TEXT NOT NULL,
                lot_size INTEGER NOT NULL,
                tick_size REAL NOT NULL
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_symbol ON instruments(symbol)"
        )
        try:
            self._conn.execute("ALTER TABLE instruments ADD COLUMN sector TEXT NOT NULL DEFAULT 'unknown'")
        except sqlite3.OperationalError:
            pass  # column already exists
        self._conn.commit()

    def refresh(self, raw_instruments: list[dict[str, Any]]) -> int:
        equities = [
            i for i in raw_instruments
            if i.get("instrument_type") == "EQ" and i.get("segment") == "NSE"
        ]
        self._conn.execute("DELETE FROM instruments")
        self._conn.executemany(
            "INSERT INTO instruments (token, symbol, exchange, lot_size, tick_size, sector) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(i["instrument_token"], i["tradingsymbol"], i["exchange"],
              i["lot_size"], i["tick_size"],
              i.get("industry_type") or "unknown") for i in equities],
        )
        self._conn.commit()
        return len(equities)

    def get_all(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM instruments").fetchall()
        return [{"token": r["token"], "symbol": r["symbol"],
                 "exchange": r["exchange"], "lot_size": r["lot_size"],
                 "tick_size": r["tick_size"],
                 "sector": r["sector"]} for r in rows]

    def get_token(self, symbol: str) -> int:
        row = self._conn.execute(
            "SELECT token FROM instruments WHERE symbol = ?", (symbol,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Instrument not found: {symbol}")
        return row["token"]

    def close(self) -> None:
        self._conn.close()
