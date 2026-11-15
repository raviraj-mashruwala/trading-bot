"""Rule executor persistence: its own two tables in tradingbot.db, separate from the plan executor's."""

from __future__ import annotations

import json
import threading
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS rule_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    mode TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    stop_price REAL NOT NULL,
    entered_at TEXT NOT NULL,
    exit_price REAL,
    exited_at TEXT,
    exit_reason TEXT,
    gross_pnl REAL,
    est_charges REAL,
    net_pnl REAL,
    status TEXT NOT NULL,
    signal TEXT,
    stop_order_id TEXT
);
CREATE TABLE IF NOT EXISTS rule_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    mode TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL
);
"""


def intraday_charges(entry: float, exit_: float, quantity: int, short: bool) -> float:
    """NSE cash intraday charges (Zerodha schedule), excluding slippage."""
    buy, sell = (exit_, entry) if short else (entry, exit_)
    buy_v, sell_v = buy * quantity, sell * quantity
    turnover = buy_v + sell_v
    brokerage = min(20.0, buy_v * .0003) + min(20.0, sell_v * .0003)
    exchange, sebi = turnover * .0000307, turnover * .000001
    return brokerage + exchange + sebi + .18 * (brokerage + exchange + sebi) + sell_v * .00025 + buy_v * .00003


class RuleStore:
    def __init__(self, connection, rule: str) -> None:
        self._conn = connection
        self._rule = rule
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def event(self, trade_date: str, mode: str, kind: str, message: str, now: datetime) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO rule_events (rule, trade_date, mode, timestamp, kind, message) VALUES (?,?,?,?,?,?)",
                (self._rule, trade_date, mode, now.isoformat(), kind, message))
            self._conn.commit()

    def open_trade(self, trade_date: str, mode: str, symbol: str, direction: str, quantity: int,
                   entry: float, stop: float, entered_at: datetime, signal: dict) -> int:
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO rule_trades (rule, trade_date, mode, symbol, direction, quantity, entry_price,
                   stop_price, entered_at, status, signal) VALUES (?,?,?,?,?,?,?,?,?, 'open', ?)""",
                (self._rule, trade_date, mode, symbol, direction, quantity, entry, stop,
                 entered_at.isoformat(), json.dumps(signal)))
            self._conn.commit()
            return int(cur.lastrowid)

    def set_stop_order(self, trade_id: int, order_id: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE rule_trades SET stop_order_id=? WHERE id=?", (order_id, trade_id))
            self._conn.commit()

    def close_trade(self, trade_id: int, exit_price: float, exited_at: datetime, reason: str) -> dict:
        with self._lock:
            row = self._conn.execute("SELECT * FROM rule_trades WHERE id=?", (trade_id,)).fetchone()
            short = row["direction"] == "short"
            qty, entry = row["quantity"], row["entry_price"]
            gross = (entry - exit_price) * qty if short else (exit_price - entry) * qty
            charges = intraday_charges(entry, exit_price, qty, short)
            self._conn.execute(
                """UPDATE rule_trades SET exit_price=?, exited_at=?, exit_reason=?, gross_pnl=?, est_charges=?,
                   net_pnl=?, status='closed' WHERE id=?""",
                (exit_price, exited_at.isoformat(), reason, gross, charges, gross - charges, trade_id))
            self._conn.commit()
            return {"gross_pnl": gross, "est_charges": charges, "net_pnl": gross - charges}

    def trade_for_day(self, trade_date: str, mode: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM rule_trades WHERE rule=? AND trade_date=? AND mode=? ORDER BY id DESC LIMIT 1",
                (self._rule, trade_date, mode)).fetchone()
        return dict(row) if row else None

    def trades(self, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM rule_trades WHERE rule=? ORDER BY id DESC LIMIT ?", (self._rule, limit)).fetchall()
        return [dict(r) for r in rows]

    def events(self, trade_date: str | None = None, limit: int = 200) -> list[dict]:
        with self._lock:
            if trade_date:
                rows = self._conn.execute(
                    "SELECT * FROM rule_events WHERE rule=? AND trade_date=? ORDER BY id DESC LIMIT ?",
                    (self._rule, trade_date, limit)).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM rule_events WHERE rule=? ORDER BY id DESC LIMIT ?", (self._rule, limit)).fetchall()
        return [dict(r) for r in rows]
