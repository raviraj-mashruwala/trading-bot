"""SQLite-backed store for trade setups with lifecycle tracking."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

STALE_HOURS_VOLATILE = 2
STALE_HOURS_NORMAL = 4


class SetupStore:
    """Persist and query trade setups across multiple analysis runs."""

    def __init__(self, db_path: Path):
        from tradingbot.core.db_factory import DatabaseKind, create_connection
        self._conn = create_connection(DatabaseKind.TRADING, Path(db_path))
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS setups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                strategy TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                target_1 REAL NOT NULL,
                target_2 REAL,
                confidence REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'proposed',
                reasoning TEXT,
                rejection_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_setup_date ON setups(trade_date)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_setup_symbol ON setups(symbol, trade_date)"
        )
        # Idempotent migrations for analytics columns
        for col, coltype in [
            ("thesis", "TEXT"),
            ("invalidation_condition", "TEXT"),
            ("bear_case", "TEXT"),
            ("confluence_count", "INTEGER"),
            ("entry_trigger", "TEXT"),
            ("regime_at_generation", "TEXT"),
            ("timeframe_alignment", "TEXT"),
        ]:
            try:
                self._conn.execute(f"ALTER TABLE setups ADD COLUMN {col} {coltype}")
            except Exception:
                pass  # column already exists
        self._conn.commit()

    def save(self, setup: dict[str, Any]) -> int:
        import json
        now = datetime.now(tz=IST).isoformat()
        tfa = setup.get("timeframe_alignment", [])
        cursor = self._conn.execute(
            "INSERT INTO setups (run_id, trade_date, symbol, strategy, direction, "
            "entry_price, stop_loss, target_1, target_2, confidence, status, reasoning, "
            "thesis, invalidation_condition, bear_case, confluence_count, "
            "entry_trigger, regime_at_generation, timeframe_alignment, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                setup["run_id"],
                setup["trade_date"],
                setup["symbol"],
                setup["strategy"],
                setup["direction"],
                setup["entry_price"],
                setup["stop_loss"],
                setup["target_1"],
                setup.get("target_2"),
                setup["confidence"],
                setup.get("status", "proposed"),
                setup.get("reasoning", ""),
                setup.get("thesis", ""),
                setup.get("invalidation_condition", ""),
                setup.get("bear_case", ""),
                setup.get("confluence_count", 0),
                setup.get("entry_trigger", ""),
                setup.get("regime_at_generation", ""),
                json.dumps(tfa) if isinstance(tfa, list) else (tfa or "[]"),
                now,
                now,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_active(self, trade_date: date) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM setups WHERE trade_date = ? AND status IN ('approved', 'active') "
            "ORDER BY confidence DESC",
            (str(trade_date),),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_for_date(self, trade_date: date) -> list[dict[str, Any]]:
        """Return every setup for a date regardless of status."""
        rows = self._conn.execute(
            "SELECT * FROM setups WHERE trade_date = ? ORDER BY created_at",
            (str(trade_date),),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_for_symbol(self, symbol: str, trade_date: date) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM setups WHERE symbol = ? AND trade_date = ? ORDER BY created_at",
            (symbol, str(trade_date)),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_by_id(self, setup_id: int) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM setups WHERE id = ?", (setup_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Setup {setup_id} not found")
        return dict(row)

    def update_status(
        self, setup_id: int, status: str, reason: str = ""
    ) -> None:
        now = datetime.now(tz=IST).isoformat()
        self._conn.execute(
            "UPDATE setups SET status = ?, rejection_reason = ?, updated_at = ? WHERE id = ?",
            (status, reason, now, setup_id),
        )
        self._conn.commit()

    def supersede_approved(self, trade_date: date, reason: str) -> int:
        """Retire a date's approved setups (not active ones) so a rerun does not duplicate them."""
        cursor = self._conn.execute(
            "UPDATE setups SET status = 'superseded', rejection_reason = ?, updated_at = ? "
            "WHERE trade_date = ? AND status = 'approved'",
            (reason, datetime.now(tz=IST).isoformat(), str(trade_date)),
        )
        self._conn.commit()
        return cursor.rowcount

    def mark_stale(self, regime: str, now: datetime) -> int:
        """Mark approved/active setups older than threshold as stale.

        Threshold: >2h for volatile regime, >4h otherwise.
        Returns count of setups marked stale.
        """
        threshold_hours = STALE_HOURS_VOLATILE if regime == "volatile" else STALE_HOURS_NORMAL
        cutoff = (now - timedelta(hours=threshold_hours)).isoformat()
        cursor = self._conn.execute(
            "UPDATE setups SET status = 'stale', updated_at = ? "
            "WHERE status IN ('approved', 'active') AND created_at < ?",
            (now.isoformat(), cutoff),
        )
        self._conn.commit()
        return cursor.rowcount

    def close(self) -> None:
        self._conn.close()
