"""Volume profile scorer for Tier 1 screening.

Scores 0-100 based on where current price sits relative to the value area
(POC, VAH, VAL) computed from the candle history.

Zones:
  close > VAH  → bullish breakout (70-85)
  POC < close ≤ VAH → mild bullish (55-70)
  close ≈ POC  → equilibrium / neutral (45-55)
  VAL ≤ close < POC → mild bearish (35-50)
  close < VAL  → bearish breakdown (15-30)
"""

from __future__ import annotations

import pandas as pd

_MIN_CANDLES = 5


def score_from_levels(close: float, poc: float, vah: float, val: float) -> float:
    """Score 0-100 based on distance from value area (direction-neutral).

    Stocks far from the value area (above VAH or below VAL) score high
    regardless of direction — both breakouts and breakdowns are interesting.
    Exposed for direct testing. score_volume_profile calls this internally.
    """
    if vah <= val or (vah == poc == val):
        return 50.0

    va_range = vah - val

    if close > vah:
        excess = (close - vah) / va_range
        return min(100.0, 70.0 + excess * 30.0)

    if close < val:
        deficit = (val - close) / va_range
        return min(100.0, 70.0 + deficit * 30.0)

    # Inside value area: distance from POC determines interest
    dist_from_poc = abs(close - poc) / va_range
    return 50.0 + dist_from_poc * 20.0


def score_volume_profile(df: pd.DataFrame) -> float:
    """Return 0-100 volume profile position score.

    Uses the full df for profile computation. Returns 50.0 on
    insufficient data or degenerate profile (all closes identical).
    """
    if df.empty or len(df) < _MIN_CANDLES:
        return 50.0

    try:
        from tradingbot.strategy.indicators import volume_profile
        vp = volume_profile(df)
    except Exception:
        return 50.0

    return score_from_levels(
        close=float(df["close"].iloc[-1]),
        poc=vp["poc"],
        vah=vp["vah"],
        val=vp["val"],
    )
