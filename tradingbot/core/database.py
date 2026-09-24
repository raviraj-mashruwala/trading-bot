"""SQLite persistence for executed trades and plan snapshots."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from tradingbot.core.models import (
    Direction,
    ExecutedTrade,
    Mode,
    StrategyName,
    TradePlan,
    TradeStatus,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    direction TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    target_1 REAL NOT NULL,
    target_2 REAL NOT NULL,
    entered_at TEXT NOT NULL,
    exited_at TEXT NOT NULL,
    pnl REAL NOT NULL,
    exit_reason TEXT NOT NULL,
    status TEXT NOT NULL,
    mode TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trades_date ON trades (trade_date);

CREATE TABLE IF NOT EXISTS plan_snapshots (
    trade_date TEXT PRIMARY KEY,
    generated_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


class Database:
    """Thin wrapper over a SQLite file. One instance per process."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row

    def initialise(self) -> None:
        """Create tables if they do not exist. Safe to call repeatedly."""
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def record_trade(self, trade: ExecutedTrade) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO trades (
                trade_date, symbol, strategy, direction, quantity,
                entry_price, exit_price, stop_loss, target_1, target_2,
                entered_at, exited_at, pnl, exit_reason, status, mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.trade_date,
                trade.symbol,
                trade.strategy.value,
                trade.direction.value,
                trade.quantity,
                trade.entry_price,
                trade.exit_price,
                trade.stop_loss,
                trade.target_1,
                trade.target_2,
                trade.entered_at.isoformat(),
                trade.exited_at.isoformat(),
                trade.pnl,
                trade.exit_reason,
                trade.status.value,
                trade.mode.value,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def trades_for_date(self, trade_date: str) -> list[ExecutedTrade]:
        rows = self.connection.execute(
            "SELECT * FROM trades WHERE trade_date = ? ORDER BY id",
            (trade_date,),
        ).fetchall()
        return [self._row_to_trade(row) for row in rows]

    def recent_trades(self, days: int, today: date) -> list[ExecutedTrade]:
        cutoff = (today - timedelta(days=days)).isoformat()
        rows = self.connection.execute(
            "SELECT * FROM trades WHERE trade_date >= ? ORDER BY trade_date, id",
            (cutoff,),
        ).fetchall()
        return [self._row_to_trade(row) for row in rows]

    def realised_pnl_for_date(self, trade_date: str) -> float:
        row = self.connection.execute(
            "SELECT COALESCE(SUM(pnl), 0.0) AS total FROM trades WHERE trade_date = ?",
            (trade_date,),
        ).fetchone()
        return float(row["total"])

    def save_plan_snapshot(self, plan: TradePlan) -> None:
        self.connection.execute(
            """
            INSERT INTO plan_snapshots (trade_date, generated_at, payload)
            VALUES (?, ?, ?)
            ON CONFLICT(trade_date) DO UPDATE SET
                generated_at = excluded.generated_at,
                payload = excluded.payload
            """,
            (plan.trade_date, plan.generated_at.isoformat(), json.dumps(plan.to_dict())),
        )
        self.connection.commit()

    @staticmethod
    def _row_to_trade(row: sqlite3.Row) -> ExecutedTrade:
        return ExecutedTrade(
            trade_date=row["trade_date"],
            symbol=row["symbol"],
            strategy=StrategyName(row["strategy"]),
            direction=Direction(row["direction"]),
            quantity=int(row["quantity"]),
            entry_price=float(row["entry_price"]),
            exit_price=float(row["exit_price"]),
            stop_loss=float(row["stop_loss"]),
            target_1=float(row["target_1"]),
            target_2=float(row["target_2"]),
            entered_at=datetime.fromisoformat(row["entered_at"]),
            exited_at=datetime.fromisoformat(row["exited_at"]),
            pnl=float(row["pnl"]),
            exit_reason=row["exit_reason"],
            status=TradeStatus(row["status"]),
            mode=Mode(row["mode"]),
        )
