"""Deterministic technical indicators. Pure pandas and numpy, no LLM involvement."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

from tradingbot.core.models import IndicatorSnapshot

MIN_CANDLES = 200


class InsufficientDataError(Exception):
    """Raised when there are not enough candles to compute a full snapshot."""


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI. A flat series returns 50 rather than NaN."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    result = 100.0 - (100.0 / (1.0 + rs))
    both_flat = (avg_gain == 0.0) & (avg_loss == 0.0)
    result = result.mask(both_flat, 50.0)
    result = result.mask((avg_loss == 0.0) & (avg_gain > 0.0), 100.0)
    return result


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series]:
    """Return the MACD line and its signal line."""
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def bollinger_bands(
    close: pd.Series,
    period: int = 20,
    std: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (upper, middle, lower) bands."""
    middle = close.rolling(window=period).mean()
    deviation = close.rolling(window=period).std(ddof=0)
    return middle + std * deviation, middle, middle - std * deviation


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range using Wilder's smoothing."""
    high, low, prev_close = df["high"], df["low"], df["close"].shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(window=period).mean()


def ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def vwap(df: pd.DataFrame) -> pd.Series:
    """Cumulative volume weighted average price across the supplied frame."""
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    cumulative_volume = df["volume"].cumsum()
    return (typical * df["volume"]).cumsum() / cumulative_volume


def pivot_points(df: pd.DataFrame) -> dict[str, float]:
    """Classic floor-trader pivots derived from the most recent candle."""
    last = df.iloc[-1]
    high, low, close = float(last["high"]), float(last["low"]), float(last["close"])
    pivot = (high + low + close) / 3.0
    return {
        "pivot": pivot,
        "r1": 2 * pivot - low,
        "r2": pivot + (high - low),
        "s1": 2 * pivot - high,
        "s2": pivot - (high - low),
    }


def support_resistance(
    df: pd.DataFrame,
    eps_pct: float = 0.5,
    min_samples: int = 3,
) -> tuple[list[float], list[float]]:
    """Cluster swing highs and lows with DBSCAN into support and resistance levels.

    eps_pct is expressed as a percentage of the last close so the same setting
    behaves consistently across a 90 rupee stock and a 3000 rupee one.
    """
    last_close = float(df["close"].iloc[-1])
    pivots = np.concatenate([df["high"].to_numpy(), df["low"].to_numpy()]).reshape(-1, 1)
    if len(pivots) < min_samples:
        return [], []

    eps = last_close * (eps_pct / 100.0)
    labels = DBSCAN(eps=eps, min_samples=min_samples).fit(pivots).labels_

    levels = [
        float(pivots[labels == label].mean())
        for label in sorted(set(labels))
        if label != -1
    ]

    supports = sorted(level for level in levels if level < last_close)
    resistances = sorted(level for level in levels if level > last_close)
    return supports, resistances


def compute_snapshot(symbol: str, df: pd.DataFrame) -> IndicatorSnapshot:
    """Compute every indicator the strategy layer needs for one symbol."""
    if len(df) < MIN_CANDLES:
        raise InsufficientDataError(
            f"{symbol}: need at least {MIN_CANDLES} candles to compute a snapshot, got {len(df)}"
        )

    close = df["close"]
    macd_line, signal_line = macd(close)
    upper, middle, lower = bollinger_bands(close)
    supports, resistances = support_resistance(df)

    return IndicatorSnapshot(
        symbol=symbol,
        last_close=float(close.iloc[-1]),
        rsi_14=float(rsi(close).iloc[-1]),
        macd=float(macd_line.iloc[-1]),
        macd_signal=float(signal_line.iloc[-1]),
        bb_upper=float(upper.iloc[-1]),
        bb_middle=float(middle.iloc[-1]),
        bb_lower=float(lower.iloc[-1]),
        atr_14=float(atr(df).iloc[-1]),
        sma_20=float(sma(close, 20).iloc[-1]),
        sma_50=float(sma(close, 50).iloc[-1]),
        sma_200=float(sma(close, 200).iloc[-1]),
        ema_12=float(ema(close, 12).iloc[-1]),
        ema_26=float(ema(close, 26).iloc[-1]),
        vwap=float(vwap(df).iloc[-1]),
        pivot=float(pivot_points(df)["pivot"]),
        support_levels=supports,
        resistance_levels=resistances,
    )
