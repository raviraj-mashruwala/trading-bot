from __future__ import annotations

from tradingbot.executor.candle_aggregator import LiveCandle


def detect_pattern(candles: list[LiveCandle]) -> str:
    if len(candles) == 0:
        return "none"
    curr = candles[-1]
    prev = candles[-2] if len(candles) >= 2 else None
    prev2 = candles[-3] if len(candles) >= 3 else None

    if prev2 is not None:
        if _is_morning_star(prev2, prev, curr):
            return "morning_star"
        if _is_evening_star(prev2, prev, curr):
            return "evening_star"

    if prev is not None:
        if _is_bullish_engulfing(prev, curr):
            return "bullish_engulf"
        if _is_bearish_engulfing(prev, curr):
            return "bearish_engulf"

    if _is_bullish_marubozu(curr):
        return "bullish_marubozu"
    if _is_bearish_marubozu(curr):
        return "bearish_marubozu"
    if _is_hammer(curr):
        return "hammer"
    if _is_shooting_star(curr):
        return "shooting_star"
    if _is_doji(curr):
        return "doji"
    return "none"


def _body(c: LiveCandle) -> float:
    return abs(c.close - c.open)


def _range(c: LiveCandle) -> float:
    return c.high - c.low if c.high != c.low else 0.0001


def _is_bullish(c: LiveCandle) -> bool:
    return c.close > c.open


def _is_bearish(c: LiveCandle) -> bool:
    return c.close < c.open


def _is_bullish_marubozu(c: LiveCandle) -> bool:
    r = _range(c)
    return _is_bullish(c) and _body(c) / r > 0.9


def _is_bearish_marubozu(c: LiveCandle) -> bool:
    r = _range(c)
    return _is_bearish(c) and _body(c) / r > 0.9


def _is_hammer(c: LiveCandle) -> bool:
    r = _range(c)
    b = _body(c)
    lower_shadow = min(c.open, c.close) - c.low
    upper_shadow = c.high - max(c.open, c.close)
    return b / r < 0.35 and lower_shadow / r > 0.5 and upper_shadow / r < 0.15


def _is_shooting_star(c: LiveCandle) -> bool:
    r = _range(c)
    b = _body(c)
    lower_shadow = min(c.open, c.close) - c.low
    upper_shadow = c.high - max(c.open, c.close)
    return b / r < 0.35 and upper_shadow / r > 0.5 and lower_shadow / r < 0.15


def _is_doji(c: LiveCandle) -> bool:
    return _body(c) / _range(c) < 0.1


def _is_bullish_engulfing(prev: LiveCandle, curr: LiveCandle) -> bool:
    return (_is_bearish(prev) and _is_bullish(curr)
            and curr.open <= prev.close and curr.close >= prev.open)


def _is_bearish_engulfing(prev: LiveCandle, curr: LiveCandle) -> bool:
    return (_is_bullish(prev) and _is_bearish(curr)
            and curr.open >= prev.close and curr.close <= prev.open)


def _is_morning_star(c0: LiveCandle, c1: LiveCandle, c2: LiveCandle) -> bool:
    return (_is_bearish(c0) and _body(c0) / _range(c0) > 0.5
            and _body(c1) / _range(c1) < 0.3
            and _is_bullish(c2) and c2.close > (c0.open + c0.close) / 2)


def _is_evening_star(c0: LiveCandle, c1: LiveCandle, c2: LiveCandle) -> bool:
    return (_is_bullish(c0) and _body(c0) / _range(c0) > 0.5
            and _body(c1) / _range(c1) < 0.3
            and _is_bearish(c2) and c2.close < (c0.open + c0.close) / 2)
