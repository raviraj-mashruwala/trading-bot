from datetime import datetime
import pytest
from tradingbot.executor.candle_aggregator import CandleAggregator, LiveCandle


def test_live_candle_is_frozen():
    c = LiveCandle(
        symbol="RELIANCE", timeframe="1min",
        timestamp=datetime(2026, 9, 29, 9, 15),
        open=2450.0, high=2455.0, low=2448.0, close=2453.0,
        volume=1000, is_complete=True,
    )
    assert c.symbol == "RELIANCE"
    with pytest.raises(AttributeError):
        c.open = 999.0


def test_single_tick_creates_current_candle():
    agg = CandleAggregator()
    agg.on_tick("RELIANCE", 2450.0, 100, datetime(2026, 9, 29, 9, 15, 10))
    current = agg.get_current("RELIANCE", "1min")
    assert current is not None
    assert current.open == 2450.0
    assert current.high == 2450.0
    assert current.low == 2450.0
    assert current.close == 2450.0
    assert current.volume == 100
    assert not current.is_complete


def test_last_price_returns_latest_tick():
    agg = CandleAggregator()
    agg.on_tick("RELIANCE", 2450.0, 100, datetime(2026, 9, 29, 9, 15, 10))
    agg.on_tick("RELIANCE", 2455.0, 200, datetime(2026, 9, 29, 9, 15, 20))
    assert agg.last_price("RELIANCE") == 2455.0


def test_last_price_returns_none_for_unknown_symbol():
    agg = CandleAggregator()
    assert agg.last_price("UNKNOWN") is None


def test_1min_candle_closes_on_boundary_cross():
    agg = CandleAggregator()
    closed = []
    agg.subscribe("1min_close", lambda sym, c: closed.append(c))
    # Ticks within 09:15
    agg.on_tick("RELIANCE", 2450.0, 100, datetime(2026, 9, 29, 9, 15, 10))
    agg.on_tick("RELIANCE", 2455.0, 200, datetime(2026, 9, 29, 9, 15, 40))
    agg.on_tick("RELIANCE", 2448.0, 150, datetime(2026, 9, 29, 9, 15, 55))
    assert len(closed) == 0
    # Tick at 09:16 closes the 09:15 candle
    agg.on_tick("RELIANCE", 2452.0, 100, datetime(2026, 9, 29, 9, 16, 5))
    assert len(closed) == 1
    c = closed[0]
    assert c.open == 2450.0
    assert c.high == 2455.0
    assert c.low == 2448.0
    assert c.close == 2448.0
    assert c.volume == 450
    assert c.is_complete
    assert c.timestamp == datetime(2026, 9, 29, 9, 15)


def test_5min_candle_closes_on_boundary_cross():
    agg = CandleAggregator()
    closed_5m = []
    agg.subscribe("5min_close", lambda sym, c: closed_5m.append(c))
    # Ticks at 09:15, 09:16, 09:17, 09:18, 09:19
    for minute in range(15, 20):
        agg.on_tick("RELIANCE", 2450.0 + minute, 100, datetime(2026, 9, 29, 9, minute, 30))
    assert len(closed_5m) == 0
    # Tick at 09:20 crosses the 5min boundary
    agg.on_tick("RELIANCE", 2470.0, 100, datetime(2026, 9, 29, 9, 20, 5))
    assert len(closed_5m) == 1
    c = closed_5m[0]
    assert c.timestamp == datetime(2026, 9, 29, 9, 15)
    assert c.timeframe == "5min"


def test_close_stale_candles_fills_empty():
    agg = CandleAggregator()
    closed = []
    agg.subscribe("1min_close", lambda sym, c: closed.append(c))
    agg.on_tick("RELIANCE", 2450.0, 100, datetime(2026, 9, 29, 9, 15, 10))
    # 2 minutes pass with no ticks
    agg.close_stale_candles("RELIANCE", datetime(2026, 9, 29, 9, 17, 0))
    assert len(closed) == 1
    assert closed[0].is_complete
    assert closed[0].has_gap is True
    assert closed[0].volume == 100
    assert closed[0].volume == 100


def test_seed_preloads_history():
    agg = CandleAggregator()
    candles = [
        LiveCandle("RELIANCE", "1min", datetime(2026, 9, 29, 9, 15),
                   2450.0, 2455.0, 2448.0, 2453.0, 1000, True),
    ]
    agg.seed("RELIANCE", "1min", candles)
    assert len(agg.get_candles("RELIANCE", "1min")) == 1


def test_history_bounded_to_50():
    from datetime import timedelta
    agg = CandleAggregator()
    base = datetime(2026, 9, 29, 9, 15, 10)
    for i in range(55):
        agg.on_tick("RELIANCE", 2450.0 + i, 100, base + timedelta(minutes=i))
    # 55 boundary crosses -> 54 closed candles, but capped at 50
    candles = agg.get_candles("RELIANCE", "1min")
    assert len(candles) <= 50


def test_multiple_symbols_independent():
    agg = CandleAggregator()
    agg.on_tick("RELIANCE", 2450.0, 100, datetime(2026, 9, 29, 9, 15, 10))
    agg.on_tick("INFY", 1800.0, 200, datetime(2026, 9, 29, 9, 15, 15))
    assert agg.last_price("RELIANCE") == 2450.0
    assert agg.last_price("INFY") == 1800.0
    assert agg.get_current("RELIANCE", "1min").open == 2450.0
    assert agg.get_current("INFY", "1min").open == 1800.0
