from datetime import datetime, time
from unittest.mock import MagicMock, patch
import pytest
from tradingbot.executor.execution_intelligence import ExecutionIntelligence, TickerHealth


class FakeTicker:
    def __init__(self):
        self.subscribed = []
        self.started = False
        self.stopped = False
        self._tick_callback = None

    def subscribe(self, tokens, callback):
        self.subscribed.extend(tokens)
        self._tick_callback = callback

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def inject_tick(self, ticks):
        if self._tick_callback:
            self._tick_callback(None, ticks)


def _make_config():
    return MagicMock(
        square_off_time=time(15, 15),
        max_entry_price_drift_pct=1.5,
    )


def test_start_subscribes_and_seeds():
    ticker = FakeTicker()
    intel = ExecutionIntelligence(ticker, _make_config())
    # Mock the historical candle fetch
    with patch.object(intel, '_fetch_historical_candles', return_value=[]):
        intel.start(["RELIANCE", "INFY"])
    assert len(ticker.subscribed) == 2


def test_stop_cleans_up():
    ticker = FakeTicker()
    intel = ExecutionIntelligence(ticker, _make_config())
    with patch.object(intel, '_fetch_historical_candles', return_value=[]):
        intel.start(["RELIANCE"])
    intel.stop()
    assert ticker.stopped


def test_tick_flows_to_aggregator():
    ticker = FakeTicker()
    intel = ExecutionIntelligence(ticker, _make_config())
    with patch.object(intel, '_fetch_historical_candles', return_value=[]):
        intel.start(["RELIANCE"])
    tick = {"instrument_token": "RELIANCE", "last_price": 2450.0,
            "volume_traded": 1000, "exchange_timestamp": datetime(2026, 9, 29, 9, 15, 10)}
    intel._on_ticks(None, [tick])
    assert intel.aggregator.last_price("RELIANCE") == 2450.0


def test_health_starts_healthy():
    ticker = FakeTicker()
    intel = ExecutionIntelligence(ticker, _make_config())
    assert intel.health.status == "healthy"
    assert not intel.is_degraded


def test_ticker_health_dataclass():
    h = TickerHealth()
    assert h.status == "healthy"
    assert h.reconnect_count == 0
    assert h.gap_seconds_today == 0


def test_components_wired():
    ticker = FakeTicker()
    intel = ExecutionIntelligence(ticker, _make_config())
    assert intel.aggregator is not None
    assert intel.scorer is not None
    assert intel.entry_guard is not None
    assert intel.adaptive_exit is not None
    assert intel.escalator is not None
