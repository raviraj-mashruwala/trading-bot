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
    conn.execute("PRAGMA journal_mode=WAL")
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
