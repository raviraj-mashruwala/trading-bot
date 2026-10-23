import threading
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


def test_tick_flows_to_aggregator_string_token():
    """Without instrument_cache, tokens are strings — tick mapping works."""
    ticker = FakeTicker()
    intel = ExecutionIntelligence(ticker, _make_config())
    with patch.object(intel, '_fetch_historical_candles', return_value=[]):
        intel.start(["RELIANCE"])
    tick = {"instrument_token": "RELIANCE", "last_price": 2450.0,
            "volume_traded": 1000, "exchange_timestamp": datetime(2026, 9, 29, 9, 15, 10)}
    intel._on_ticks(None, [tick])
    assert intel.aggregator.last_price("RELIANCE") == 2450.0


def test_tick_flows_to_aggregator_int_token():
    """With instrument_cache, tokens are ints — reverse lookup maps to symbol."""
    ticker = FakeTicker()
    cache = MagicMock()
    cache.get_token.return_value = 738561
    intel = ExecutionIntelligence(ticker, _make_config(), instrument_cache=cache)
    with patch.object(intel, '_fetch_historical_candles', return_value=[]):
        intel.start(["RELIANCE"])
    # Kite sends int token in real ticks
    tick = {"instrument_token": 738561, "last_price": 2450.0,
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


def test_fetch_historical_candles_with_kite_client():
    """With kite_client + instrument_cache, historical candles are fetched and seeded."""
    ticker = FakeTicker()
    cache = MagicMock()
    cache.get_token.return_value = 738561
    kite_client = MagicMock()
    kite_client.fetch_historical.return_value = [
        {"date": datetime(2026, 9, 29, 9, 15), "open": 2450.0, "high": 2455.0,
         "low": 2448.0, "close": 2453.0, "volume": 1000},
        {"date": datetime(2026, 9, 29, 9, 16), "open": 2453.0, "high": 2458.0,
         "low": 2451.0, "close": 2456.0, "volume": 1200},
    ]
    intel = ExecutionIntelligence(ticker, _make_config(),
                                  instrument_cache=cache, kite_client=kite_client)
    intel.start(["RELIANCE"])
    # fetch_historical called twice (minute + 5minute)
    assert kite_client.fetch_historical.call_count == 2
    # Candles seeded into aggregator
    candles_1m = intel.aggregator.get_candles("RELIANCE", "1min")
    assert len(candles_1m) == 2


def test_fetch_historical_candles_without_kite_client():
    """Without kite_client, _fetch_historical_candles returns empty."""
    ticker = FakeTicker()
    intel = ExecutionIntelligence(ticker, _make_config())
    with patch.object(intel, '_fetch_historical_candles', wraps=intel._fetch_historical_candles):
        intel.start(["RELIANCE"])
    assert len(intel.aggregator.get_candles("RELIANCE", "1min")) == 0


def test_start_subscribes_int_tokens_with_cache():
    """With instrument_cache, start subscribes int tokens to ticker."""
    ticker = FakeTicker()
    cache = MagicMock()
    cache.get_token.side_effect = lambda s: {"RELIANCE": 738561, "INFY": 408065}[s]
    kite_client = MagicMock()
    kite_client.fetch_historical.return_value = []
    intel = ExecutionIntelligence(ticker, _make_config(),
                                  instrument_cache=cache, kite_client=kite_client)
    intel.start(["RELIANCE", "INFY"])
    assert 738561 in ticker.subscribed
    assert 408065 in ticker.subscribed


def test_degraded_status_not_reset_by_ticks():
    """When status is 'degraded', incoming ticks should NOT reset it to 'healthy'."""
    ticker = FakeTicker()
    intel = ExecutionIntelligence(ticker, _make_config())
    with patch.object(intel, '_fetch_historical_candles', return_value=[]):
        intel.start(["RELIANCE"])
    intel.mark_degraded(30)
    assert intel.health.status == "degraded"
    tick = {"instrument_token": "RELIANCE", "last_price": 2450.0,
            "volume_traded": 1000, "exchange_timestamp": datetime(2026, 9, 29, 9, 15, 10)}
    intel._on_ticks(None, [tick])
    assert intel.health.status == "degraded"


def test_reconnecting_status_reset_by_ticks():
    """When status is 'reconnecting', incoming ticks SHOULD reset to 'healthy'."""
    ticker = FakeTicker()
    intel = ExecutionIntelligence(ticker, _make_config())
    with patch.object(intel, '_fetch_historical_candles', return_value=[]):
        intel.start(["RELIANCE"])
    intel.on_disconnect()
    assert intel.health.status == "reconnecting"
    tick = {"instrument_token": "RELIANCE", "last_price": 2450.0,
            "volume_traded": 1000, "exchange_timestamp": datetime(2026, 9, 29, 9, 15, 10)}
    intel._on_ticks(None, [tick])
    assert intel.health.status == "healthy"


def test_on_disconnect_increments_reconnect_count():
    ticker = FakeTicker()
    intel = ExecutionIntelligence(ticker, _make_config())
    intel.on_disconnect()
    assert intel.health.reconnect_count == 1
    assert intel.health.status == "reconnecting"
    intel.on_disconnect()
    assert intel.health.reconnect_count == 2


def test_mark_degraded_accumulates_gap():
    ticker = FakeTicker()
    intel = ExecutionIntelligence(ticker, _make_config())
    intel.mark_degraded(30)
    intel.mark_degraded(45)
    assert intel.health.gap_seconds_today == 75
    assert intel.health.status == "degraded"


def test_first_minute_close_does_not_freeze_tick_processing():
    """Regression: the 1-minute close callback re-reads candles from the aggregator
    while on_tick still held its symbol lock, freezing the ticker thread for good."""
    ticker = FakeTicker()
    intel = ExecutionIntelligence(ticker, _make_config())
    with patch.object(intel, '_fetch_historical_candles', return_value=[]):
        intel.start(["RELIANCE"])

    def tick(second_of_day: tuple[int, int, int], price: float) -> dict:
        return {"instrument_token": "RELIANCE", "last_price": price, "volume_traded": 100,
                "exchange_timestamp": datetime(2026, 9, 29, *second_of_day)}

    def feed():
        intel._on_ticks(None, [tick((9, 15, 10), 2450.0)])
        intel._on_ticks(None, [tick((9, 16, 5), 2455.0)])   # closes the 09:15 candle
        intel._on_ticks(None, [tick((9, 16, 20), 2457.0)])  # must still be processed

    worker = threading.Thread(target=feed, daemon=True)
    worker.start()
    worker.join(2.0)

    assert not worker.is_alive(), "tick processing froze at the first 1-minute candle close"
    assert intel.aggregator.last_price("RELIANCE") == 2457.0
    assert len(intel.aggregator.get_candles("RELIANCE", "1min")) == 1


class WatchdogTicker(FakeTicker):
    """FakeTicker with the liveness and reconnect surface the watchdog uses."""

    def __init__(self, responsive: bool = True, last_tick_time: datetime | None = None):
        super().__init__()
        self.responsive = responsive
        self.last_tick_time = last_tick_time
        self.probes = 0
        self.restarts = 0
        self.reconnects = 0

    def is_loop_responsive(self, timeout: float = 1.0) -> bool:
        self.probes += 1
        return self.responsive

    def restart(self) -> None:
        self.restarts += 1

    def force_reconnect(self) -> None:
        self.reconnects += 1


def _watchdog_intel(ticker, alerts: list | None = None) -> ExecutionIntelligence:
    intel = ExecutionIntelligence(ticker, _make_config())
    if alerts is not None:
        intel.alert = alerts.append
    return intel


def test_watchdog_restarts_wedged_ticker_even_before_market_open():
    ticker = WatchdogTicker(responsive=False)
    alerts: list[str] = []
    intel = _watchdog_intel(ticker, alerts)

    assert intel.check_and_reconnect(now=datetime(2026, 9, 29, 9, 5)) is True

    assert ticker.restarts == 1
    assert intel.health.status == "reconnecting"
    assert intel.health.reconnect_count == 1
    assert len(alerts) == 1 and "frozen" in alerts[0]


def test_watchdog_probes_liveness_at_most_every_interval():
    ticker = WatchdogTicker(responsive=True)
    intel = _watchdog_intel(ticker)

    intel.check_and_reconnect(now=datetime(2026, 9, 29, 9, 5))
    intel.check_and_reconnect(now=datetime(2026, 9, 29, 9, 5, 5))

    assert ticker.probes == 1


def test_watchdog_leaves_healthy_ticker_alone():
    ticker = WatchdogTicker(responsive=True, last_tick_time=datetime(2026, 9, 29, 9, 20, 0))
    intel = _watchdog_intel(ticker)

    assert intel.check_and_reconnect(now=datetime(2026, 9, 29, 9, 20, 30)) is False

    assert ticker.restarts == 0 and ticker.reconnects == 0


def test_stale_ticks_force_reconnect_and_alert_once_per_episode():
    ticker = WatchdogTicker(responsive=True, last_tick_time=datetime(2026, 9, 29, 9, 3, 2))
    alerts: list[str] = []
    intel = _watchdog_intel(ticker, alerts)

    assert intel.check_and_reconnect(now=datetime(2026, 9, 29, 9, 15, 1)) is True
    intel._last_reconnect_at = 0.0  # let the reconnect cooldown pass
    assert intel.check_and_reconnect(now=datetime(2026, 9, 29, 9, 17, 2)) is True

    assert ticker.reconnects == 2
    assert len(alerts) == 1 and "No ticks" in alerts[0]


def test_stale_alert_rearms_after_ticks_resume():
    ticker = WatchdogTicker(responsive=True, last_tick_time=datetime(2026, 9, 29, 9, 3, 2))
    alerts: list[str] = []
    intel = _watchdog_intel(ticker, alerts)

    intel.check_and_reconnect(now=datetime(2026, 9, 29, 9, 15, 1))
    ticker.last_tick_time = datetime(2026, 9, 29, 9, 16, 0)
    intel.check_and_reconnect(now=datetime(2026, 9, 29, 9, 16, 10))  # ticks are back
    intel._last_reconnect_at = 0.0
    ticker.last_tick_time = datetime(2026, 9, 29, 9, 20, 0)
    intel.check_and_reconnect(now=datetime(2026, 9, 29, 9, 30, 0))  # stale again

    assert len(alerts) == 2


def test_alert_failure_does_not_break_the_watchdog():
    ticker = WatchdogTicker(responsive=False)
    intel = _watchdog_intel(ticker)

    def broken_alert(message: str) -> None:
        raise RuntimeError("telegram down")

    intel.alert = broken_alert

    assert intel.check_and_reconnect(now=datetime(2026, 9, 29, 9, 5)) is True
    assert ticker.restarts == 1
