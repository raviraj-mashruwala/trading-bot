"""Tests for TickReplayer: replay feeds ticks correctly, preserves order, handles empty."""

import json
import tempfile
from datetime import datetime

import pytest

from tradingbot.executor.candle_aggregator import CandleAggregator
from tradingbot.executor.tick_replayer import TickReplayer


def test_replay_feeds_ticks_to_aggregator():
    """Ticks spanning two 1min boundaries produce 1 closed candle and set last_price."""
    ticks = [
        {"symbol": "RELIANCE", "price": 2450.0, "volume": 100,
         "timestamp": datetime(2026, 9, 29, 9, 15, 10)},
        {"symbol": "RELIANCE", "price": 2455.0, "volume": 200,
         "timestamp": datetime(2026, 9, 29, 9, 15, 30)},
        {"symbol": "RELIANCE", "price": 2452.0, "volume": 150,
         "timestamp": datetime(2026, 9, 29, 9, 16, 5)},
    ]
    agg = CandleAggregator()
    replayer = TickReplayer(ticks)
    replayer.replay(agg)

    assert agg.last_price("RELIANCE") == 2452.0
    candles = agg.get_candles("RELIANCE", "1min")
    assert len(candles) == 1
    # Closed candle is minute 15: open=2450, high=2455, close=2455
    assert candles[0].open == 2450.0
    assert candles[0].high == 2455.0
    assert candles[0].is_complete


def test_replay_preserves_order():
    """Out-of-order ticks fed in sequence; last_price reflects final tick by timestamp."""
    # Create ticks already sorted -- replayer should keep them sorted
    ticks = [
        {"symbol": "RELIANCE", "price": float(i), "volume": 100,
         "timestamp": datetime(2026, 9, 29, 9, 15, i)}
        for i in range(1, 10)
    ]
    agg = CandleAggregator()
    replayer = TickReplayer(ticks)
    replayer.replay(agg)
    assert agg.last_price("RELIANCE") == 9.0


def test_replay_sorts_unsorted_ticks():
    """Ticks supplied out of order still replayed in timestamp order."""
    ticks = [
        {"symbol": "RELIANCE", "price": 100.0, "volume": 50,
         "timestamp": datetime(2026, 9, 29, 9, 15, 30)},
        {"symbol": "RELIANCE", "price": 95.0, "volume": 50,
         "timestamp": datetime(2026, 9, 29, 9, 15, 10)},
        {"symbol": "RELIANCE", "price": 105.0, "volume": 50,
         "timestamp": datetime(2026, 9, 29, 9, 15, 50)},
    ]
    agg = CandleAggregator()
    TickReplayer(ticks).replay(agg)
    # Sorted: 95 -> 100 -> 105. Last price = 105
    assert agg.last_price("RELIANCE") == 105.0
    # All in same minute, no closed candles yet
    assert len(agg.get_candles("RELIANCE", "1min")) == 0
    # Current candle: open=95 (first after sort), close=105 (last)
    current = agg.get_current("RELIANCE", "1min")
    assert current is not None
    assert current.open == 95.0
    assert current.close == 105.0


def test_replay_empty_ticks():
    """Empty tick list: no error, no price set."""
    agg = CandleAggregator()
    replayer = TickReplayer([])
    replayer.replay(agg)
    assert agg.last_price("RELIANCE") is None


def test_tick_count():
    ticks = [
        {"symbol": "X", "price": 1.0, "volume": 1,
         "timestamp": datetime(2026, 1, 1, 9, 15, i)}
        for i in range(5)
    ]
    assert TickReplayer(ticks).tick_count == 5
    assert TickReplayer([]).tick_count == 0


def test_from_file():
    """Load ticks from a JSON file and replay."""
    ticks_data = [
        {"symbol": "INFY", "price": 1500.0, "volume": 200,
         "timestamp": "2026-09-29T09:15:10"},
        {"symbol": "INFY", "price": 1505.0, "volume": 300,
         "timestamp": "2026-09-29T09:15:30"},
        {"symbol": "INFY", "price": 1502.0, "volume": 100,
         "timestamp": "2026-09-29T09:16:05"},
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(ticks_data, f)
        path = f.name

    replayer = TickReplayer.from_file(path)
    assert replayer.tick_count == 3

    agg = CandleAggregator()
    replayer.replay(agg)
    assert agg.last_price("INFY") == 1502.0
