import numpy as np
import pandas as pd
import pytest

from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies import STRATEGY_REGISTRY, all_strategies
from tradingbot.strategy.strategies.base import Signal, Strategy
from tradingbot.strategy.strategies.breakout import BreakoutStrategy
from tradingbot.strategy.strategies.mean_reversion import MeanReversionStrategy
from tradingbot.strategy.strategies.momentum import MomentumStrategy
from tradingbot.strategy.strategies.orb import ORBStrategy
from tradingbot.strategy.strategies.vwap_bounce import VWAPBounceStrategy


def make_candles(closes, volumes=None, spread=1.0):
    index = pd.date_range("2026-09-24 09:15", periods=len(closes), freq="15min", tz="Asia/Kolkata")
    closes = np.asarray(closes, dtype=float)
    volumes = np.full(len(closes), 10000.0) if volumes is None else np.asarray(volumes, dtype=float)
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes + spread,
            "low": closes - spread,
            "close": closes,
            "volume": volumes,
        },
        index=index,
    )


def make_snapshot(**overrides) -> IndicatorSnapshot:
    defaults = {
        "symbol": "RELIANCE",
        "last_close": 100.0,
        "rsi_14": 55.0,
        "macd": 0.5,
        "macd_signal": 0.2,
        "bb_upper": 108.0,
        "bb_middle": 100.0,
        "bb_lower": 92.0,
        "atr_14": 2.0,
        "sma_20": 98.0,
        "sma_50": 95.0,
        "sma_200": 90.0,
        "ema_12": 99.0,
        "ema_26": 97.0,
        "vwap": 99.0,
        "pivot": 100.0,
        "support_levels": [95.0, 90.0],
        "resistance_levels": [105.0, 110.0],
    }
    defaults.update(overrides)
    return IndicatorSnapshot(**defaults)


def test_registry_contains_every_strategy_name():
    assert set(STRATEGY_REGISTRY) == set(StrategyName)


def test_all_strategies_returns_one_instance_per_name():
    strategies = all_strategies()

    assert len(strategies) == len(StrategyName)
    assert all(isinstance(strategy, Strategy) for strategy in strategies)


def test_strategy_abc_cannot_be_instantiated():
    with pytest.raises(TypeError):
        Strategy()


@pytest.mark.parametrize(
    "strategy",
    [
        BreakoutStrategy(),
        MomentumStrategy(),
        MeanReversionStrategy(),
        VWAPBounceStrategy(),
        ORBStrategy(),
    ],
)
def test_every_strategy_returns_none_or_a_well_formed_signal(strategy):
    df = make_candles(100 + np.cumsum(np.random.default_rng(3).normal(0, 1, 60)))
    signal = strategy.generate_signal(df, make_snapshot())

    if signal is not None:
        assert isinstance(signal, Signal)
        assert 0.0 <= signal.strength <= 1.0
        assert signal.stop_loss != signal.entry_price


@pytest.mark.parametrize(
    "strategy",
    [
        BreakoutStrategy(),
        MomentumStrategy(),
        MeanReversionStrategy(),
        VWAPBounceStrategy(),
        ORBStrategy(),
    ],
)
def test_no_strategy_mutates_the_candle_frame(strategy):
    df = make_candles(100 + np.cumsum(np.random.default_rng(5).normal(0, 1, 60)))
    before = df.copy(deep=True)

    strategy.generate_signal(df, make_snapshot())

    pd.testing.assert_frame_equal(df, before)


def test_breakout_goes_long_when_price_clears_resistance_on_volume():
    df = make_candles([100.0] * 30 + [106.0], volumes=[10000.0] * 30 + [50000.0])
    snapshot = make_snapshot(last_close=106.0, resistance_levels=[105.0], rsi_14=62.0)

    signal = BreakoutStrategy().generate_signal(df, snapshot)

    assert signal is not None
    assert signal.direction is Direction.LONG
    assert signal.entry_price == pytest.approx(106.0)


def test_breakout_is_silent_when_price_is_inside_the_range():
    df = make_candles([100.0] * 31)
    snapshot = make_snapshot(last_close=100.0, resistance_levels=[105.0], support_levels=[95.0])

    assert BreakoutStrategy().generate_signal(df, snapshot) is None


def test_breakout_stop_and_targets_follow_the_atr_geometry():
    df = make_candles([100.0] * 30 + [106.0], volumes=[10000.0] * 30 + [50000.0])
    snapshot = make_snapshot(last_close=106.0, resistance_levels=[105.0], rsi_14=62.0, atr_14=2.0)

    signal = BreakoutStrategy().generate_signal(df, snapshot)

    assert signal.stop_loss == pytest.approx(104.0)
    assert signal.target_1 == pytest.approx(110.0)
    assert signal.target_2 == pytest.approx(112.0)


def test_momentum_goes_long_when_trend_and_macd_agree():
    df = make_candles(np.arange(100, 160, dtype=float))
    snapshot = make_snapshot(
        last_close=159.0, sma_20=150.0, sma_50=140.0, macd=1.5, macd_signal=0.8, rsi_14=65.0
    )

    signal = MomentumStrategy().generate_signal(df, snapshot)

    assert signal is not None
    assert signal.direction is Direction.LONG


def test_momentum_is_silent_when_rsi_is_already_overbought():
    df = make_candles(np.arange(100, 160, dtype=float))
    snapshot = make_snapshot(
        last_close=159.0, sma_20=150.0, sma_50=140.0, macd=1.5, macd_signal=0.8, rsi_14=85.0
    )

    assert MomentumStrategy().generate_signal(df, snapshot) is None


def test_mean_reversion_goes_long_when_price_is_oversold_at_the_lower_band():
    df = make_candles([100.0] * 30 + [91.0])
    snapshot = make_snapshot(last_close=91.0, bb_lower=92.0, bb_middle=100.0, rsi_14=25.0)

    signal = MeanReversionStrategy().generate_signal(df, snapshot)

    assert signal is not None
    assert signal.direction is Direction.LONG


def test_mean_reversion_goes_short_when_price_is_overbought_at_the_upper_band():
    df = make_candles([100.0] * 30 + [109.0])
    snapshot = make_snapshot(last_close=109.0, bb_upper=108.0, bb_middle=100.0, rsi_14=78.0)

    signal = MeanReversionStrategy().generate_signal(df, snapshot)

    assert signal is not None
    assert signal.direction is Direction.SHORT


def test_mean_reversion_is_silent_inside_the_bands():
    df = make_candles([100.0] * 31)
    snapshot = make_snapshot(last_close=100.0, rsi_14=50.0)

    assert MeanReversionStrategy().generate_signal(df, snapshot) is None


def test_vwap_bounce_goes_long_when_price_reclaims_vwap_in_an_uptrend():
    df = make_candles([100.0] * 30 + [99.2])
    snapshot = make_snapshot(last_close=99.2, vwap=99.0, sma_20=95.0, sma_50=92.0, rsi_14=52.0)

    signal = VWAPBounceStrategy().generate_signal(df, snapshot)

    assert signal is not None
    assert signal.direction is Direction.LONG


def test_vwap_bounce_is_silent_when_price_is_far_from_vwap():
    df = make_candles([100.0] * 30 + [130.0])
    snapshot = make_snapshot(last_close=130.0, vwap=99.0, sma_20=95.0, sma_50=92.0)

    assert VWAPBounceStrategy().generate_signal(df, snapshot) is None


def test_orb_goes_long_when_price_breaks_the_opening_range_high():
    closes = [100.0, 101.0, 100.5, 100.8] + [103.0]
    df = make_candles(closes, spread=0.5)
    snapshot = make_snapshot(last_close=103.0)

    signal = ORBStrategy().generate_signal(df, snapshot)

    assert signal is not None
    assert signal.direction is Direction.LONG


def test_orb_goes_short_when_price_breaks_the_opening_range_low():
    closes = [100.0, 101.0, 100.5, 100.8] + [97.0]
    df = make_candles(closes, spread=0.5)
    snapshot = make_snapshot(last_close=97.0)

    signal = ORBStrategy().generate_signal(df, snapshot)

    assert signal is not None
    assert signal.direction is Direction.SHORT


def test_orb_needs_more_candles_than_the_opening_range():
    df = make_candles([100.0, 101.0])

    assert ORBStrategy().generate_signal(df, make_snapshot()) is None
