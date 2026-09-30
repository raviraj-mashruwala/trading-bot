import sqlite3
from pathlib import Path

import pytest

from tradingbot.core.db_factory import create_connection, DatabaseKind, get_turso_config


def test_local_fallback_when_no_turso_env(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_TRADING_URL", raising=False)
    monkeypatch.delenv("TURSO_TRADING_TOKEN", raising=False)
    conn = create_connection(DatabaseKind.TRADING, tmp_path / "test.db")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO t (name) VALUES (?)", ("hello",))
    conn.commit()
    row = conn.execute("SELECT * FROM t").fetchone()
    assert row["name"] == "hello"
    conn.close()


def test_row_access_by_name(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_TRADING_URL", raising=False)
    conn = create_connection(DatabaseKind.TRADING, tmp_path / "test.db")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, symbol TEXT, price REAL)")
    conn.execute("INSERT INTO t (symbol, price) VALUES (?, ?)", ("RELIANCE", 2450.0))
    conn.commit()
    row = conn.execute("SELECT * FROM t").fetchone()
    assert row["symbol"] == "RELIANCE"
    assert row["price"] == 2450.0
    assert row[1] == "RELIANCE"
    conn.close()


def test_executemany_works(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_TRADING_URL", raising=False)
    conn = create_connection(DatabaseKind.TRADING, tmp_path / "test.db")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
    data = [(f"item_{i}",) for i in range(1000)]
    conn.executemany("INSERT INTO t (val) VALUES (?)", data)
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    assert count == 1000
    conn.close()


def test_executescript_works(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_TRADING_URL", raising=False)
    conn = create_connection(DatabaseKind.TRADING, tmp_path / "test.db")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS a (id INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS b (id INTEGER PRIMARY KEY);
    """)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r[0] for r in tables}
    assert "a" in names
    assert "b" in names
    conn.close()


def test_get_turso_config_returns_none_when_not_set(monkeypatch):
    monkeypatch.delenv("TURSO_TRADING_URL", raising=False)
    assert get_turso_config(DatabaseKind.TRADING) is None


def test_get_turso_config_returns_tuple_when_set(monkeypatch):
    monkeypatch.setenv("TURSO_TRADING_URL", "libsql://test.turso.io")
    monkeypatch.setenv("TURSO_TRADING_TOKEN", "secret123")
    result = get_turso_config(DatabaseKind.TRADING)
    assert result == ("libsql://test.turso.io", "secret123")


def test_alter_table_works(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_TRADING_URL", raising=False)
    conn = create_connection(DatabaseKind.TRADING, tmp_path / "test.db")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("ALTER TABLE t ADD COLUMN extra TEXT DEFAULT 'none'")
    conn.commit()
    conn.execute("INSERT INTO t (name, extra) VALUES (?, ?)", ("a", "b"))
    conn.commit()
    row = conn.execute("SELECT * FROM t").fetchone()
    assert row["extra"] == "b"
    conn.close()


def test_turso_unavailable_falls_back_to_local(tmp_path, monkeypatch):
    monkeypatch.setenv("TURSO_TRADING_URL", "libsql://unreachable.turso.io")
    monkeypatch.setenv("TURSO_TRADING_TOKEN", "fake-token")
    conn = create_connection(DatabaseKind.TRADING, tmp_path / "fallback.db")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO t (name) VALUES (?)", ("works",))
    conn.commit()
    row = conn.execute("SELECT * FROM t").fetchone()
    assert row["name"] == "works"
    conn.close()
