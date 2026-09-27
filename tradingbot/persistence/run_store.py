"""SQLite-backed store for analysis run metadata."""

from __future__ import annotations

import sqlite3
from datetime import date
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

    def close(self) -> None:
        self._conn.close()
