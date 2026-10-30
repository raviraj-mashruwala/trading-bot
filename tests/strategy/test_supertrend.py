"""Supertrend must follow the textbook algorithm: finite bands after warmup, real flips."""

import numpy as np
import pandas as pd

from tradingbot.strategy.indicators import compute_snapshot, supertrend

PERIOD = 10


def frame(closes) -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "open": closes, "high": closes + 1.0, "low": closes - 1.0,
        "close": closes, "volume": np.full(len(closes), 100_000.0),
    })


def noisy(closes, seed=1):
    return np.asarray(closes, dtype=float) + np.random.default_rng(seed).normal(0, 0.3, len(closes))


def test_supertrend_has_no_nan_after_warmup():
    upper, lower, direction = supertrend(frame(noisy(np.linspace(200, 100, 300))), period=PERIOD)

    assert upper.iloc[PERIOD:].notna().all()
    assert lower.iloc[PERIOD:].notna().all()
    assert direction.notna().all()


def test_supertrend_direction_is_down_in_a_steady_downtrend():
    _, _, direction = supertrend(frame(noisy(np.linspace(200, 100, 300))), period=PERIOD)

    assert direction.iloc[-1] == -1
    assert (direction.iloc[PERIOD * 3:] == -1).all()


def test_supertrend_direction_is_up_in_a_steady_uptrend():
    _, _, direction = supertrend(frame(noisy(np.linspace(100, 200, 300))), period=PERIOD)

    assert direction.iloc[-1] == 1
    assert (direction.iloc[PERIOD * 3:] == 1).all()


def test_supertrend_flips_when_the_trend_reverses():
    closes = noisy(np.concatenate([np.linspace(200, 120, 150), np.linspace(120, 220, 150)]))

    _, _, direction = supertrend(frame(closes), period=PERIOD)

    assert (direction.iloc[:150] == -1).any()
    assert direction.iloc[-1] == 1
    first_down = direction[direction == -1].index[0]
    assert (direction.loc[first_down:] == 1).any()  # it came back up


def test_supertrend_band_sits_on_the_correct_side_of_price():
    df = frame(noisy(np.concatenate([np.linspace(200, 120, 150), np.linspace(120, 220, 150)])))
    upper, lower, direction = supertrend(df, period=PERIOD)
    valid = slice(PERIOD, None)

    down = direction.iloc[valid] == -1
    up = direction.iloc[valid] == 1
    assert (df["close"].iloc[valid][down] <= upper.iloc[valid][down]).all()
    assert (df["close"].iloc[valid][up] >= lower.iloc[valid][up]).all()


def test_supertrend_bands_never_loosen_while_the_trend_holds():
    upper, lower, direction = supertrend(frame(noisy(np.linspace(100, 200, 300))), period=PERIOD)

    held = lower.iloc[PERIOD:]  # steady uptrend: the lower band only ratchets up
    assert (held.diff().dropna() >= -1e-9).all()


def test_short_frames_return_neutral_values_not_errors():
    upper, lower, direction = supertrend(frame(np.linspace(100, 110, 5)), period=PERIOD)

    assert len(direction) == 5
    assert (direction == 1).all()
    assert upper.isna().all() and lower.isna().all()


def test_snapshot_supertrend_value_and_direction_are_usable():
    closes = noisy(np.linspace(300, 100, 300))
    snapshot = compute_snapshot("TEST", frame(closes))

    assert np.isfinite(snapshot.supertrend)
    assert snapshot.supertrend_direction == -1
    assert snapshot.supertrend >= snapshot.last_close  # downtrend line sits above price
