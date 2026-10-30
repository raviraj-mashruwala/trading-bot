"""Deterministic technical indicators. Pure pandas and numpy, no LLM involvement."""

from __future__ import annotations

from typing import Any

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


PROFILE_SESSIONS = 10  # sessions behind the volume profile and the support/resistance clusters


def session_keys(df: pd.DataFrame) -> pd.Series:
    """The trading date of every row. A frame with no timestamps is one session."""
    if "timestamp" in df.columns:
        stamps = pd.to_datetime(df["timestamp"])
    elif isinstance(df.index, pd.DatetimeIndex):
        stamps = df.index.to_series()
    else:
        return pd.Series(0, index=df.index)
    return stamps.dt.normalize()


def recent_sessions(df: pd.DataFrame, sessions: int = PROFILE_SESSIONS) -> pd.DataFrame:
    """Only the rows of the last `sessions` trading sessions."""
    keys = session_keys(df)
    return df[keys.isin(sorted(keys.unique())[-sessions:])]


def session_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """One OHLCV row per session, oldest first."""
    grouped = df.groupby(session_keys(df), sort=True)
    return pd.DataFrame({
        "open": grouped["open"].first(),
        "high": grouped["high"].max(),
        "low": grouped["low"].min(),
        "close": grouped["close"].last(),
        "volume": grouped["volume"].sum(),
    })


def vwap(df: pd.DataFrame) -> pd.Series:
    """Volume weighted average price, anchored to each trading session.

    VWAP is an intraday reference: it restarts every session. Accumulating across
    weeks (as this once did) gives a multi-week average that sits nowhere near price.
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    keys = session_keys(df)
    cumulative_volume = df["volume"].groupby(keys).cumsum()
    return (typical * df["volume"]).groupby(keys).cumsum() / cumulative_volume


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

    Only the last PROFILE_SESSIONS sessions count: levels from weeks ago are not
    where price is trading now.

    eps_pct is expressed as a percentage of the last close so the same setting
    behaves consistently across a 90 rupee stock and a 3000 rupee one.
    """
    df = recent_sessions(df)
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


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index -- trend strength (0-100)."""
    high, low, close = df["high"], df["low"], df["close"]
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    # Zero out when opposite DM is larger
    plus_dm = plus_dm.where(plus_dm >= minus_dm, 0)
    minus_dm = minus_dm.where(minus_dm >= plus_dm, 0)

    true_range = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    smoothed_tr = true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / smoothed_tr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / smoothed_tr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def supertrend(
    df: pd.DataFrame, period: int = 10, multiplier: float = 3.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Supertrend indicator. Returns (upper_band, lower_band, direction).

    direction is +1 (uptrend, the lower band is the line) or -1 (downtrend, the
    upper band is the line). Rows before the ATR has enough history are NaN with
    direction +1 by convention. The recursion starts at the first valid ATR, since
    comparing against a NaN band is always False and would leave the bands NaN and
    the direction frozen at its initial value.
    """
    high, low, close = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
    atr_val = atr(df, period).to_numpy(float)
    n = len(df)

    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    direction = np.ones(n, dtype=int)

    valid = np.flatnonzero(~np.isnan(atr_val))
    if len(valid):
        start = int(valid[0])
        hl2 = (high + low) / 2.0
        basic_upper = hl2 + multiplier * atr_val
        basic_lower = hl2 - multiplier * atr_val

        final_upper[start] = basic_upper[start]
        final_lower[start] = basic_lower[start]
        for i in range(start + 1, n):
            # A band only moves in its tightening direction, unless price broke through it.
            if basic_upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]:
                final_upper[i] = basic_upper[i]
            else:
                final_upper[i] = final_upper[i - 1]
            if basic_lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]:
                final_lower[i] = basic_lower[i]
            else:
                final_lower[i] = final_lower[i - 1]

            if direction[i - 1] == 1:
                direction[i] = -1 if close[i] < final_lower[i] else 1
            else:
                direction[i] = 1 if close[i] > final_upper[i] else -1

    return (
        pd.Series(final_upper, index=df.index),
        pd.Series(final_lower, index=df.index),
        pd.Series(direction, index=df.index, dtype=int),
    )


def camarilla_pivots(df: pd.DataFrame) -> dict[str, float]:
    """Camarilla pivot levels from previous session's high/low/close."""
    last = df.iloc[-1]
    h, l, c = float(last["high"]), float(last["low"]), float(last["close"])
    diff = h - l
    return {
        "h4": c + diff * 1.1 / 2,
        "h3": c + diff * 1.1 / 4,
        "h2": c + diff * 1.1 / 6,
        "h1": c + diff * 1.1 / 12,
        "l1": c - diff * 1.1 / 12,
        "l2": c - diff * 1.1 / 6,
        "l3": c - diff * 1.1 / 4,
        "l4": c - diff * 1.1 / 2,
    }


def vwap_bands(
    df: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """Session-anchored VWAP with +/-1 sigma and +/-2 sigma bands.

    Returns (vwap, upper1, lower1, upper2, lower2).
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3
    keys = session_keys(df)
    cum_vol = df["volume"].groupby(keys).cumsum()
    vwap_line = (typical * df["volume"]).groupby(keys).cumsum() / cum_vol

    cum_sq = (((typical - vwap_line) ** 2) * df["volume"]).groupby(keys).cumsum()
    std = np.sqrt(cum_sq / cum_vol)

    return vwap_line, vwap_line + std, vwap_line - std, vwap_line + 2 * std, vwap_line - 2 * std


def bollinger_bandwidth(close: pd.Series, period: int = 20, std: float = 2.0) -> pd.Series:
    """Bollinger Band width as percentage of middle band."""
    upper, middle, lower = bollinger_bands(close, period, std)
    return ((upper - lower) / middle) * 100


def volume_profile(df: pd.DataFrame, bins: int = 20) -> dict[str, float]:
    """Volume profile: POC, VAH, VAL from the last PROFILE_SESSIONS sessions."""
    df = recent_sessions(df)
    prices = df["close"].values
    volumes = df["volume"].values.astype(float)

    price_min, price_max = prices.min(), prices.max()
    bin_edges = np.linspace(price_min, price_max, bins + 1)
    vol_by_bin = np.zeros(bins)
    bin_centers = np.zeros(bins)

    for i in range(bins):
        if i == bins - 1:
            mask = (prices >= bin_edges[i]) & (prices <= bin_edges[i + 1])
        else:
            mask = (prices >= bin_edges[i]) & (prices < bin_edges[i + 1])
        vol_by_bin[i] = volumes[mask].sum()
        bin_centers[i] = (bin_edges[i] + bin_edges[i + 1]) / 2

    poc_idx = vol_by_bin.argmax()
    poc = float(bin_centers[poc_idx])

    total_vol = vol_by_bin.sum()
    target = total_vol * 0.7
    sorted_indices = np.argsort(vol_by_bin)[::-1]
    cumulative = 0.0
    va_bins: list[int] = []
    for idx in sorted_indices:
        va_bins.append(int(idx))
        cumulative += vol_by_bin[idx]
        if cumulative >= target:
            break

    va_prices = [bin_centers[i] for i in va_bins]
    vah = float(max(va_prices))
    val = float(min(va_prices))

    return {"poc": poc, "vah": vah, "val": val}


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

    # New indicators
    adx_val = adx(df, period=14)
    st_upper, st_lower, st_dir = supertrend(df, period=10, multiplier=3.0)
    bb_bw = bollinger_bandwidth(close)
    vwap_line, vwap_u1, vwap_l1, _, _ = vwap_bands(df)
    vol_prof = volume_profile(df)

    sessions_df = session_ohlc(df)
    last_session = sessions_df.iloc[-1]
    pivots = pivot_points(sessions_df)  # from the last session, not the last 15m candle
    last_5 = sessions_df.tail(5)
    last_20 = sessions_df.tail(20)

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
        vwap=float(vwap_line.iloc[-1]),
        pivot=float(pivots["pivot"]),
        pivot_r1=float(pivots["r1"]),
        pivot_s1=float(pivots["s1"]),
        last_session_high=float(last_session["high"]),
        last_session_low=float(last_session["low"]),
        last_session_close=float(last_session["close"]),
        high_5d=float(last_5["high"].max()),
        low_5d=float(last_5["low"].min()),
        high_20d=float(last_20["high"].max()),
        low_20d=float(last_20["low"].min()),
        support_levels=supports,
        resistance_levels=resistances,
        adx_14=float(adx_val.iloc[-1]) if not np.isnan(adx_val.iloc[-1]) else 0.0,
        supertrend=float(st_upper.iloc[-1]) if st_dir.iloc[-1] == -1 else float(st_lower.iloc[-1]),
        supertrend_direction=int(st_dir.iloc[-1]),
        bb_bandwidth=float(bb_bw.iloc[-1]) if not np.isnan(bb_bw.iloc[-1]) else 0.0,
        vwap_upper_1=float(vwap_u1.iloc[-1]),
        vwap_lower_1=float(vwap_l1.iloc[-1]),
        poc=vol_prof["poc"],
        vah=vol_prof["vah"],
        val=vol_prof["val"],
        ema_9=float(ema(close, 9).iloc[-1]),
        sma_9=float(sma(close, 9).iloc[-1]),
    )


def precompute_indicator_series(symbol: str, df: pd.DataFrame) -> dict[str, Any]:
    """Compute all indicator Series once over the full dataframe.

    Returns a dict of indicator_name -> pd.Series (same length as df).
    Used by the backtester to avoid recomputing per candle.
    """
    close = df["close"]

    macd_line, signal_line = macd(close)
    upper, middle, lower = bollinger_bands(close)
    atr_series = atr(df)
    adx_series = adx(df, period=14)
    st_upper, st_lower, st_dir = supertrend(df, period=10, multiplier=3.0)
    bb_bw = bollinger_bandwidth(close)
    vwap_line, vwap_u1, vwap_l1, _, _ = vwap_bands(df)
    pivot_series = (df["high"] + df["low"] + df["close"]) / 3

    st_values = pd.Series(
        [float(st_upper.iloc[i]) if st_dir.iloc[i] == -1 else float(st_lower.iloc[i])
         for i in range(len(df))],
        index=df.index,
    )

    return {
        "last_close": close.astype(float),
        "rsi_14": rsi(close),
        "macd": macd_line,
        "macd_signal": signal_line,
        "bb_upper": upper,
        "bb_middle": middle,
        "bb_lower": lower,
        "atr_14": atr_series,
        "sma_9": sma(close, 9),
        "sma_20": sma(close, 20),
        "sma_50": sma(close, 50),
        "sma_200": sma(close, 200),
        "ema_9": ema(close, 9),
        "ema_12": ema(close, 12),
        "ema_26": ema(close, 26),
        "vwap": vwap_line,
        "vwap_upper_1": vwap_u1,
        "vwap_lower_1": vwap_l1,
        "pivot": pivot_series,
        "adx_14": adx_series,
        "supertrend": st_values,
        "supertrend_direction": st_dir,
        "bb_bandwidth": bb_bw,
    }
