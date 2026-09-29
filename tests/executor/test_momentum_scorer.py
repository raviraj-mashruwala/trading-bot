from datetime import datetime
import pytest
from tradingbot.executor.candle_aggregator import LiveCandle
from tradingbot.executor.candle_patterns import detect_pattern


def _candle(o, h, l, c, vol=1000):
    return LiveCandle("TEST", "1min", datetime(2026, 9, 29, 9, 15),
                      o, h, l, c, vol, True)


def test_detect_bullish_engulfing():
    prev = _candle(2460.0, 2462.0, 2448.0, 2450.0)  # bearish
    curr = _candle(2448.0, 2465.0, 2447.0, 2463.0)   # bullish engulfs
    assert detect_pattern([prev, curr]) == "bullish_engulf"


def test_detect_bearish_engulfing():
    prev = _candle(2450.0, 2463.0, 2449.0, 2460.0)  # bullish
    curr = _candle(2462.0, 2464.0, 2445.0, 2447.0)   # bearish engulfs
    assert detect_pattern([prev, curr]) == "bearish_engulf"


def test_detect_hammer():
    c = _candle(2455.0, 2457.0, 2440.0, 2456.0)  # small body, long lower shadow
    assert detect_pattern([c]) == "hammer"


def test_detect_no_pattern():
    c = _candle(2450.0, 2455.0, 2448.0, 2452.0)  # normal candle
    assert detect_pattern([c]) == "none"


def test_detect_needs_at_least_one_candle():
    assert detect_pattern([]) == "none"


# --- MomentumScorer tests ---

from tradingbot.executor.momentum_scorer import MomentumScorer, SymbolState


def _make_candles(prices, timeframe="1min", base_minute=15, vol=1000):
    """Make a list of completed LiveCandles from (open, close) tuples."""
    candles = []
    for i, (o, c) in enumerate(prices):
        h = max(o, c) + 1.0
        l = min(o, c) - 1.0
        candles.append(LiveCandle(
            "TEST", timeframe, datetime(2026, 9, 29, 9, base_minute + i),
            o, h, l, c, vol, True,
        ))
    return candles


def test_momentum_bullish_trending():
    scorer = MomentumScorer()
    # 5 consecutive bullish candles
    candles_1m = _make_candles([
        (100, 102), (102, 104), (104, 107), (107, 110), (110, 114),
    ])
    candles_5m = _make_candles([(100, 114)], timeframe="5min")
    state = scorer.update("TEST", candles_1m, candles_5m)
    assert state.momentum_1m > 40
    assert state.momentum_5m > 0
    assert state.trend_alignment is True
    assert state.strength in ("strong", "moderate")


def test_momentum_bearish_trending():
    scorer = MomentumScorer()
    candles_1m = _make_candles([
        (114, 112), (112, 110), (110, 107), (107, 104), (104, 100),
    ])
    candles_5m = _make_candles([(114, 100)], timeframe="5min")
    state = scorer.update("TEST", candles_1m, candles_5m)
    assert state.momentum_1m < -40
    assert state.momentum_5m < 0
    assert state.trend_alignment is True


def test_momentum_conflicting():
    scorer = MomentumScorer()
    # 1m bearish, 5m bullish
    candles_1m = _make_candles([
        (110, 108), (108, 106), (106, 104), (104, 102), (102, 100),
    ])
    candles_5m = _make_candles([(95, 105)], timeframe="5min")
    state = scorer.update("TEST", candles_1m, candles_5m)
    assert state.trend_alignment is False


def test_volume_ratio():
    scorer = MomentumScorer()
    # Normal volume candles then a 3x volume candle
    candles = []
    for i in range(20):
        candles.append(LiveCandle(
            "TEST", "1min", datetime(2026, 9, 29, 9, 15 + i),
            100.0, 101.0, 99.0, 100.5, 1000, True,
        ))
    candles.append(LiveCandle(
        "TEST", "1min", datetime(2026, 9, 29, 9, 35),
        100.0, 101.0, 99.0, 100.5, 3000, True,
    ))
    state = scorer.update("TEST", candles, [])
    assert state.volume_ratio > 2.5


def test_body_dominance_trending():
    scorer = MomentumScorer()
    # Large bodies = trending
    candles_1m = _make_candles([
        (100, 110), (110, 120), (120, 130), (130, 140), (140, 150),
    ])
    state = scorer.update("TEST", candles_1m, [])
    assert state.body_dominance > 0.7


def test_symbol_state_is_frozen():
    scorer = MomentumScorer()
    candles_1m = _make_candles([(100, 102)])
    state = scorer.update("TEST", candles_1m, [])
    with pytest.raises(AttributeError):
        state.momentum_1m = 999.0


def test_vwap_update():
    scorer = MomentumScorer()
    scorer.update_vwap("TEST", 100.0, 1000)
    scorer.update_vwap("TEST", 110.0, 1000)
    # VWAP should be (100*1000 + 110*1000) / 2000 = 105.0
    candles_1m = _make_candles([(100, 105)])
    state = scorer.update("TEST", candles_1m, [])
    assert abs(state.vwap - 105.0) < 0.01


def test_gap_candles_skipped_in_momentum():
    scorer = MomentumScorer()
    candles = [
        LiveCandle("TEST", "1min", datetime(2026, 9, 29, 9, 15),
                   100.0, 101.0, 99.0, 100.5, 0, True, has_gap=True),
        LiveCandle("TEST", "1min", datetime(2026, 9, 29, 9, 16),
                   100.0, 101.0, 99.0, 100.5, 0, True, has_gap=True),
        LiveCandle("TEST", "1min", datetime(2026, 9, 29, 9, 17),
                   100.0, 105.0, 99.0, 104.0, 1000, True, has_gap=False),
    ]
    state = scorer.update("TEST", candles, [])
    # Only the non-gap candle should be used — momentum should reflect just that one
    assert state.momentum_1m != 0.0  # would be 0 if gap candles were counted


def test_get_state_returns_none_for_unknown():
    scorer = MomentumScorer()
    assert scorer.get_state("UNKNOWN") is None
