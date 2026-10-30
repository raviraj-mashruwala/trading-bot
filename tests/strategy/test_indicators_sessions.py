"""VWAP, volume profile and levels are per trading session, not one blob of 60 days."""

import numpy as np
import pandas as pd
import pytest

from tradingbot.strategy.indicators import (
    compute_snapshot,
    support_resistance,
    volume_profile,
    vwap,
    vwap_bands,
)


def sessions_frame(specs, candles_per_session=25, start="2026-09-01"):
    """specs: one dict per session with close/high/low/volume (scalars). 15m candles from 09:15."""
    rows = []
    day = pd.Timestamp(start)
    for spec in specs:
        while day.weekday() >= 5:
            day += pd.Timedelta(days=1)
        for k in range(candles_per_session):
            rows.append({
                "timestamp": day + pd.Timedelta(hours=9, minutes=15) + pd.Timedelta(minutes=15 * k),
                "open": spec["close"],
                "high": spec.get("high", spec["close"] + 0.5),
                "low": spec.get("low", spec["close"] - 0.5),
                "close": spec["close"],
                "volume": spec.get("volume", 1000.0),
            })
        day += pd.Timedelta(days=1)
    return pd.DataFrame(rows)


def test_vwap_resets_each_session():
    df = sessions_frame([{"close": 100.0}, {"close": 200.0}], candles_per_session=10)

    line = vwap(df)

    assert line.iloc[0] == pytest.approx(100.0)
    assert line.iloc[10] == pytest.approx(200.0)  # first candle of session 2: not a 150 blend


def test_vwap_last_value_is_the_last_sessions_vwap():
    df = sessions_frame([{"close": 100.0}, {"close": 200.0}], candles_per_session=10)

    assert vwap(df).iloc[-1] == pytest.approx(200.0)


def test_vwap_bands_are_anchored_per_session():
    df = sessions_frame([{"close": 100.0}, {"close": 200.0}], candles_per_session=10)

    line, upper1, lower1, upper2, lower2 = vwap_bands(df)

    assert line.iloc[10] == pytest.approx(200.0)
    assert (upper1 - line).iloc[10] == pytest.approx(0.0, abs=1e-6)  # one sample: no deviation yet
    assert upper2.iloc[-1] >= upper1.iloc[-1] >= line.iloc[-1] >= lower1.iloc[-1] >= lower2.iloc[-1]


def test_vwap_without_timestamp_is_one_session():
    closes = np.array([100.0, 110.0, 120.0])
    df = pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes,
                       "volume": [10.0, 10.0, 10.0]})

    assert vwap(df).iloc[-1] == pytest.approx(110.0)


def test_volume_profile_uses_only_recent_sessions():
    old = [{"close": 300.0, "volume": 1_000_000.0}] * 20
    recent = [{"close": 100.0 + i * 0.1, "volume": 1000.0} for i in range(10)]
    df = sessions_frame(old + recent)

    profile = volume_profile(df)

    assert profile["poc"] < 150  # the huge old volume at 300 is outside the window
    assert profile["val"] < profile["poc"] < profile["vah"] or profile["val"] <= profile["poc"] <= profile["vah"]


def test_support_resistance_ignores_sessions_older_than_the_window():
    old = [{"close": 300.0, "high": 301.0, "low": 299.0}] * 20
    recent = [{"close": 100.0, "high": 101.0, "low": 99.0}] * 10
    df = sessions_frame(old + recent)

    supports, resistances = support_resistance(df)

    assert all(90 <= level <= 110 for level in supports + resistances)


def reference_frame():
    # Session i (0..24): every candle open=close=95+i, high=100+i, low=90+i.
    specs = [{"close": 95.0 + i, "high": 100.0 + i, "low": 90.0 + i} for i in range(25)]
    return sessions_frame(specs, candles_per_session=10)


def test_snapshot_exposes_reference_levels():
    snap = compute_snapshot("TEST", reference_frame())

    assert snap.last_session_high == pytest.approx(124.0)
    assert snap.last_session_low == pytest.approx(114.0)
    assert snap.last_session_close == pytest.approx(119.0)
    assert snap.high_5d == pytest.approx(124.0)
    assert snap.low_5d == pytest.approx(110.0)   # session 20: 90 + 20
    assert snap.high_20d == pytest.approx(124.0)
    assert snap.low_20d == pytest.approx(95.0)   # session 5: 90 + 5


def test_pivot_comes_from_the_last_session_not_the_last_candle():
    snap = compute_snapshot("TEST", reference_frame())

    assert snap.pivot == pytest.approx((124.0 + 114.0 + 119.0) / 3)
    assert snap.pivot_r1 == pytest.approx(2 * snap.pivot - 114.0)
    assert snap.pivot_s1 == pytest.approx(2 * snap.pivot - 124.0)


def test_reference_levels_reach_the_dict_the_prompt_prints():
    data = compute_snapshot("TEST", reference_frame()).to_dict()

    for key in ("last_session_high", "last_session_low", "last_session_close",
                "high_5d", "low_5d", "high_20d", "low_20d", "pivot_r1", "pivot_s1"):
        assert key in data, key


def test_snapshot_vwap_is_inside_the_last_sessions_range_after_a_long_fall():
    # The NOCIL case: 250 down to 136 over many sessions. The old whole-frame VWAP was 178.
    specs = [{"close": 250.0 - (114.0 * i / 11), "volume": 1000.0 + 50 * i} for i in range(12)]
    df = sessions_frame(specs)

    snap = compute_snapshot("NOCIL", df)

    assert snap.last_session_low <= snap.vwap <= snap.last_session_high
    assert abs(snap.vwap - snap.last_close) < 2.0


def daily_frame(closes, volumes):
    """One row per trading day, the shape Tier 1 passes (read_batch(..., 'day'))."""
    days = pd.bdate_range("2026-06-01", periods=len(closes))
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "timestamp": days, "open": closes, "high": closes + 1, "low": closes - 1,
        "close": closes, "volume": np.asarray(volumes, dtype=float),
    })


def test_volume_profile_on_daily_frames_uses_every_row():
    # A daily bar is its own session, so "last 10 sessions" would mean 10 days and silently
    # change the Tier-1 volume-profile score, which has always looked at the whole frame.
    closes = [300.0] * 50 + [100.0] * 10
    volumes = [1_000_000.0] * 50 + [1000.0] * 10

    profile = volume_profile(daily_frame(closes, volumes))

    assert profile["poc"] > 250  # the 50 heavy days at 300 are still counted


def test_support_resistance_on_daily_frames_uses_every_row():
    closes = [300.0] * 50 + [100.0] * 10

    supports, resistances = support_resistance(daily_frame(closes, [1000.0] * 60))

    assert any(level > 250 for level in supports + resistances)


def test_intraday_frames_are_still_windowed():
    # Guard against the fix above disabling the window for the data it is meant for.
    old = [{"close": 300.0, "volume": 1_000_000.0}] * 20
    recent = [{"close": 100.0 + i * 0.1, "volume": 1000.0} for i in range(10)]

    assert volume_profile(sessions_frame(old + recent))["poc"] < 150
