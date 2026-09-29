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
    """Score 0-100 given exact volume profile levels and current close.

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
        return max(0.0, 30.0 - deficit * 30.0)

    # Inside value area: val→35, poc→50, vah→65
    if close >= poc:
        t = (close - poc) / (vah - poc) if vah > poc else 0.5
        return 50.0 + t * 15.0
    else:
        t = (close - val) / (poc - val) if poc > val else 0.5
        return 35.0 + t * 15.0


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
