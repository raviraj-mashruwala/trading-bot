"""SQLite persistence for executed trades and plan snapshots."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from tradingbot.core.db_factory import DatabaseKind, create_connection

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

CREATE TABLE IF NOT EXISTS execution_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    decision_type TEXT NOT NULL,
    reason TEXT,
    momentum_snapshot TEXT,
    candle_snapshot TEXT,
    escalated INTEGER DEFAULT 0,
    llm_response TEXT,
    outcome TEXT
);

CREATE INDEX IF NOT EXISTS idx_execution_decisions_date ON execution_decisions (trade_date);

CREATE TABLE IF NOT EXISTS scout_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    signal TEXT NOT NULL,
    direction TEXT NOT NULL,
    confidence REAL NOT NULL,
    entry_price REAL NOT NULL,
    target_price REAL NOT NULL,
    stop_price REAL NOT NULL,
    reasoning TEXT,
    outcome TEXT,
    outcome_pnl_pct REAL
);

CREATE INDEX IF NOT EXISTS idx_scout_alerts_date ON scout_alerts (trade_date);

CREATE TABLE IF NOT EXISTS nightly_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL UNIQUE,
    reviewed_at TEXT NOT NULL,
    total_pnl REAL NOT NULL,
    trades_count INTEGER NOT NULL,
    wins INTEGER NOT NULL,
    losses INTEGER NOT NULL,
    summary TEXT NOT NULL,
    lessons TEXT NOT NULL,
    improvements TEXT NOT NULL,
    grade TEXT NOT NULL,
    raw_response TEXT,
    llm_cost_usd REAL DEFAULT 0
);
"""


class Database:
    """Thin wrapper over a SQLite file. One instance per process."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.connection = create_connection(DatabaseKind.TRADING, self.db_path)

    def initialise(self) -> None:
        """Create tables if they do not exist. Safe to call repeatedly."""
        self.connection.executescript(SCHEMA)
        try:
            self.connection.execute("ALTER TABLE trades ADD COLUMN setup_id INTEGER")
        except Exception:
            pass
        try:
            self.connection.execute("ALTER TABLE trades ADD COLUMN notes TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            self.connection.execute("ALTER TABLE plan_snapshots ADD COLUMN reviewed INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            self.connection.execute("ALTER TABLE plan_snapshots ADD COLUMN reviewed_at TEXT")
        except Exception:
            pass
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def record_trade(self, trade: ExecutedTrade) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO trades (
                trade_date, symbol, strategy, direction, quantity,
                entry_price, exit_price, stop_loss, target_1, target_2,
                entered_at, exited_at, pnl, exit_reason, status, mode,
                setup_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                trade.setup_id,
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

    def update_trade_notes(self, trade_id: int, notes: str) -> None:
        self.connection.execute("UPDATE trades SET notes = ? WHERE id = ?", (notes, trade_id))
        self.connection.commit()

    def get_trade_notes(self, trade_id: int) -> str:
        row = self.connection.execute("SELECT notes FROM trades WHERE id = ?", (trade_id,)).fetchone()
        return row["notes"] if row and row["notes"] else ""

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

    def approve_plan(self, trade_date: str) -> None:
        self.connection.execute(
            "UPDATE plan_snapshots SET reviewed = 1, reviewed_at = ? WHERE trade_date = ?",
            (datetime.now().isoformat(), trade_date),
        )
        self.connection.commit()

    def is_plan_reviewed(self, trade_date: str) -> bool:
        row = self.connection.execute(
            "SELECT reviewed FROM plan_snapshots WHERE trade_date = ?", (trade_date,),
        ).fetchone()
        return bool(row and row["reviewed"]) if row else False

    def log_execution_decision(self, **kwargs) -> None:
        self.connection.execute(
            """INSERT INTO execution_decisions
               (trade_date, timestamp, symbol, decision_type, reason,
                momentum_snapshot, candle_snapshot, escalated, llm_response)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                kwargs["trade_date"],
                kwargs["timestamp"],
                kwargs["symbol"],
                kwargs["decision_type"],
                kwargs["reason"],
                kwargs.get("momentum_snapshot"),
                kwargs.get("candle_snapshot"),
                int(kwargs.get("escalated", False)),
                kwargs.get("llm_response"),
            ),
        )
        self.connection.commit()

    def update_decision_outcome(self, trade_date: str, symbol: str, outcome: str) -> None:
        self.connection.execute(
            """UPDATE execution_decisions SET outcome = ?
               WHERE trade_date = ? AND symbol = ? AND decision_type = 'ENTRY_ENTER'
               AND outcome IS NULL""",
            (outcome, trade_date, symbol),
        )
        self.connection.commit()

    def get_decisions_for_date(self, trade_date: str) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM execution_decisions WHERE trade_date = ? ORDER BY timestamp",
            (trade_date,),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_nightly_review(self, review: dict) -> None:
        self.connection.execute(
            """INSERT OR REPLACE INTO nightly_reviews
               (trade_date, reviewed_at, total_pnl, trades_count, wins, losses,
                summary, lessons, improvements, grade, raw_response, llm_cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                review["trade_date"], review["reviewed_at"],
                review["total_pnl"], review["trades_count"],
                review["wins"], review["losses"],
                review["summary"], review["lessons"],
                review["improvements"], review["grade"],
                review.get("raw_response"), review.get("llm_cost_usd", 0),
            ),
        )
        self.connection.commit()

    def get_nightly_review(self, trade_date: str) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM nightly_reviews WHERE trade_date = ?", (trade_date,),
        ).fetchone()
        return dict(row) if row else None

    def get_recent_reviews(self, limit: int = 10) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM nightly_reviews ORDER BY trade_date DESC LIMIT ?", (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_execution_decisions(self, limit: int = 20) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM execution_decisions ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def strategy_stats(self) -> list[dict]:
        rows = self.connection.execute("""
            SELECT strategy,
                   COUNT(*) as total,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losses,
                   SUM(pnl) as total_pnl,
                   AVG(pnl) as avg_pnl,
                   MAX(pnl) as best_trade,
                   MIN(pnl) as worst_trade
            FROM trades
            GROUP BY strategy
            ORDER BY total_pnl DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def plan_execution_report(self, trade_date: str) -> dict:
        plan_row = self.connection.execute(
            "SELECT payload FROM plan_snapshots WHERE trade_date = ?", (trade_date,),
        ).fetchone()
        if not plan_row:
            return {"trade_date": trade_date, "legs": [], "summary": "No plan snapshot found"}

        import json as _json
        plan_data = _json.loads(plan_row["payload"])
        plan_legs = plan_data.get("legs", [])

        trades = self.trades_for_date(trade_date)
        trade_by_symbol = {t.symbol: t for t in trades}

        decisions = self.get_decisions_for_date(trade_date)
        decisions_by_symbol: dict[str, list[dict]] = {}
        for d in decisions:
            sym = d.get("symbol", "")
            decisions_by_symbol.setdefault(sym, []).append(d)

        legs = []
        entered = 0
        vetoed = 0
        missed = 0
        total_pnl = 0.0

        for leg in plan_legs:
            sym = leg.get("symbol", "")
            trade = trade_by_symbol.get(sym)
            sym_decisions = decisions_by_symbol.get(sym, [])

            key_decisions = [
                f"{d['decision_type']}: {d.get('reason', '')}"
                for d in sym_decisions
                if d["decision_type"] not in ("ENTRY_WAIT",) or "Stale" not in d.get("reason", "")
            ][-5:]

            if trade:
                entered += 1
                drift_pct = abs(trade.entry_price - leg.get("entry_price", 0)) / leg.get("entry_price", 1) * 100
                pnl = trade.pnl
                total_pnl += pnl
                legs.append({
                    "symbol": sym,
                    "direction": leg.get("direction", ""),
                    "planned_entry": leg.get("entry_price", 0),
                    "status": "entered",
                    "actual_entry": trade.entry_price,
                    "actual_exit": trade.exit_price,
                    "drift_pct": round(drift_pct, 2),
                    "pnl": round(pnl, 2),
                    "exit_reason": trade.exit_reason,
                    "key_decisions": key_decisions,
                })
            else:
                veto_decisions = [d for d in sym_decisions if "VETO" in d.get("decision_type", "")]
                timeout_decisions = [d for d in sym_decisions if "timeout" in d.get("reason", "").lower()]

                if veto_decisions:
                    status = "vetoed"
                    vetoed += 1
                    reason = veto_decisions[-1].get("reason", "unknown")
                elif timeout_decisions:
                    status = "timeout"
                    missed += 1
                    reason = "Wait timeout"
                else:
                    status = "missed"
                    missed += 1
                    reason = "No entry signal"

                legs.append({
                    "symbol": sym,
                    "direction": leg.get("direction", ""),
                    "planned_entry": leg.get("entry_price", 0),
                    "status": status,
                    "actual_entry": None,
                    "actual_exit": None,
                    "drift_pct": None,
                    "pnl": None,
                    "exit_reason": reason,
                    "key_decisions": key_decisions,
                })

        wins = sum(1 for l in legs if l["pnl"] is not None and l["pnl"] > 0)
        losses = sum(1 for l in legs if l["pnl"] is not None and l["pnl"] <= 0)

        return {
            "trade_date": trade_date,
            "legs": legs,
            "summary": f"{len(plan_legs)} planned → {entered} entered → {wins} win → {losses} loss → {vetoed} vetoed → {missed} missed",
            "total_pnl": round(total_pnl, 2),
            "entered": entered,
            "vetoed": vetoed,
            "missed": missed,
        }

    def save_scout_alert(self, alert: dict) -> int:
        self.connection.execute(
            """INSERT INTO scout_alerts
            (trade_date, timestamp, symbol, signal, direction, confidence,
             entry_price, target_price, stop_price, reasoning)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                alert["trade_date"], alert["timestamp"], alert["symbol"],
                alert["signal"], alert["direction"], alert["confidence"],
                alert["entry_price"], alert["target_price"], alert["stop_price"],
                alert.get("reasoning"),
            ),
        )
        self.connection.commit()
        return self.connection.execute("SELECT last_insert_rowid()").fetchone()[0]

    def update_scout_outcome(self, alert_id: int, outcome: str, pnl_pct: float) -> None:
        self.connection.execute(
            "UPDATE scout_alerts SET outcome = ?, outcome_pnl_pct = ? WHERE id = ?",
            (outcome, pnl_pct, alert_id),
        )
        self.connection.commit()

    def get_scout_alerts(self, trade_date: str | None = None, limit: int = 50) -> list[dict]:
        if trade_date:
            rows = self.connection.execute(
                "SELECT * FROM scout_alerts WHERE trade_date = ? ORDER BY timestamp DESC",
                (trade_date,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM scout_alerts ORDER BY timestamp DESC LIMIT ?", (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def scout_alert_stats(self) -> dict:
        row = self.connection.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN outcome = 'target_hit' THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN outcome = 'stop_hit' THEN 1 ELSE 0 END) as losses,
                   SUM(CASE WHEN outcome = 'timeout' THEN 1 ELSE 0 END) as timeouts,
                   AVG(outcome_pnl_pct) as avg_pnl_pct
            FROM scout_alerts WHERE outcome IS NOT NULL
        """).fetchone()
        if not row or row[0] == 0:
            return {"total": 0, "wins": 0, "losses": 0, "timeouts": 0, "win_rate": 0, "avg_pnl_pct": 0}
        return {
            "total": row[0], "wins": row[1] or 0, "losses": row[2] or 0,
            "timeouts": row[3] or 0,
            "win_rate": (row[1] or 0) / row[0] * 100 if row[0] > 0 else 0,
            "avg_pnl_pct": row[4] or 0,
        }

    @staticmethod
    def _row_to_trade(row) -> ExecutedTrade:
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
            setup_id=row["setup_id"] if row["setup_id"] is not None else None,
        )
