"""SQLite-backed store for analysis run metadata."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tradingbot.core.models import AnalysisRun


class RunStore:
    """Persist and query AnalysisRun records."""

    def __init__(self, db_path: Path):
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS analysis_runs (
                run_id TEXT PRIMARY KEY,
                trade_date TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                market_regime TEXT NOT NULL,
                regime_confidence REAL,
                total_scanned INTEGER,
                tier1_passed INTEGER,
                tier2_shortlisted INTEGER,
                setups_proposed INTEGER,
                setups_approved INTEGER,
                llm_calls INTEGER,
                llm_cost_usd REAL,
                duration_seconds REAL
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_run_date ON analysis_runs(trade_date)"
        )
        self._conn.commit()

    def save(self, run: AnalysisRun) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO analysis_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run.run_id,
                str(run.trade_date),
                run.timestamp.isoformat(),
                run.market_regime.value,
                run.regime_confidence,
                run.total_scanned,
                run.tier1_passed,
                run.tier2_shortlisted,
                run.setups_proposed,
                run.setups_approved,
                run.llm_calls,
                run.llm_cost_usd,
                run.duration_seconds,
            ),
        )
        self._conn.commit()

    def list_for_date(self, trade_date: date) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM analysis_runs WHERE trade_date = ? ORDER BY timestamp",
            (str(trade_date),),
        ).fetchall()
        return [dict(r) for r in rows]

    def archive_old(self, days: int = 7, setup_store: Any = None) -> int:
        """Move analysis runs older than `days` to archive table.

        Skips runs with active/approved setups when setup_store provided.
        Returns count of archived rows.
        """
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        # Create archive table mirroring schema
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS analysis_runs_archive AS
            SELECT * FROM analysis_runs WHERE 0
        """)

        # Find old rows
        rows = self._conn.execute(
            "SELECT * FROM analysis_runs WHERE trade_date < ?", (cutoff,)
        ).fetchall()

        if not rows:
            return 0

        # Filter out runs with active setups
        if setup_store:
            active_run_ids = {
                row["run_id"] for row in
                setup_store._conn.execute(
                    "SELECT DISTINCT run_id FROM setups WHERE status IN ('active', 'approved')"
                ).fetchall()
            }
            to_archive = [r for r in rows if dict(r)["run_id"] not in active_run_ids]
        else:
            to_archive = list(rows)

        if not to_archive:
            return 0

        for row in to_archive:
            d = dict(row)
            self._conn.execute(
                "INSERT OR REPLACE INTO analysis_runs_archive VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                tuple(d.values()),
            )
            self._conn.execute("DELETE FROM analysis_runs WHERE run_id = ?", (d["run_id"],))

        self._conn.commit()
        return len(to_archive)

    def close(self) -> None:
        self._conn.close()
