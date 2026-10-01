"""Root test conftest — ensure tests use local SQLite, not Turso cloud."""

import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_from_turso(monkeypatch):
    """Prevent load_dotenv() from restoring Turso env vars during tests."""
    monkeypatch.setenv("TURSO_TRADING_URL", "")
    monkeypatch.setenv("TURSO_TRADING_TOKEN", "")
    monkeypatch.setenv("TURSO_MARKET_URL", "")
    monkeypatch.setenv("TURSO_MARKET_TOKEN", "")
