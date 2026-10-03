"""Tests for JevClient — graceful degradation when SDK or API key missing."""

from __future__ import annotations

from unittest.mock import patch

from tradingbot.core.config import JevConfig


def _config(**overrides) -> JevConfig:
    defaults = dict(
        enabled=True, model="jev-latest",
        entry_confidence_threshold=0.6,
        exit_confidence_threshold=0.75,
        uncertainty_threshold=0.3, timeout_ms=2000,
    )
    defaults.update(overrides)
    return JevConfig(**defaults)


def test_unavailable_when_no_api_key():
    with patch.dict("os.environ", {}, clear=True):
        from tradingbot.core.jev_client import JevClient
        client = JevClient(_config())
        assert client.available is False
        assert client.evaluate({"x": 1}, {}) is None


def test_unavailable_when_disabled():
    from tradingbot.core.jev_client import JevClient
    client = JevClient(_config(enabled=False))
    assert client.available is False


def test_stats_initial():
    from tradingbot.core.jev_client import JevClient
    client = JevClient(_config(enabled=False))
    s = client.stats()
    assert s["calls"] == 0
    assert s["avg_latency_ms"] == 0.0
