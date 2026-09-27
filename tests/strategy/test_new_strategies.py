"""Tests for 5 new strategies and ConfluenceScorer."""

import numpy as np
import pandas as pd
import pytest
from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.gap_and_go import GapAndGoStrategy
from tradingbot.strategy.strategies.pivot_point import PivotPointStrategy
from tradingbot.strategy.strategies.bollinger_squeeze import BollingerSqueezeStrategy
from tradingbot.strategy.strategies.supply_demand import SupplyDemandStrategy
from tradingbot.strategy.strategies.relative_strength import RelativeStrengthStrategy
from tradingbot.strategy.strategies.confluence import ConfluenceScorer


def _make_snapshot(**overrides):
    defaults = dict(
        symbol="TEST", last_close=500.0, rsi_14=55.0, macd=1.0,
        macd_signal=0.5, bb_upper=520.0, bb_middle=500.0, bb_lower=480.0,
        atr_14=8.0, sma_20=498.0, sma_50=495.0, sma_200=490.0,
        ema_12=501.0, ema_26=499.0, vwap=500.0, pivot=500.0,
        support_levels=[490.0, 480.0], resistance_levels=[510.0, 520.0],
        adx_14=30.0, supertrend=495.0, supertrend_direction=1,
        bb_bandwidth=4.0, vwap_upper_1=505.0, vwap_lower_1=495.0,
        poc=500.0, vah=510.0, val=490.0, ema_9=501.0, sma_9=500.5,
    )
    defaults.update(overrides)
    return IndicatorSnapshot(**defaults)


def _trending_up_df(n=50, base=500):
    close = base + np.arange(n) * 1.5 + np.random.randn(n) * 2
    return pd.DataFrame({
        "open": close - 1, "high": close + 3, "low": close - 3,
        "close": close,
        "volume": np.random.randint(500000, 1500000, n),
    })


# ----- Strategy name tests -----

def test_gap_and_go_strategy_has_correct_name():
    assert GapAndGoStrategy().name == StrategyName.GAP_AND_GO


def test_pivot_point_strategy_has_correct_name():
    assert PivotPointStrategy().name == StrategyName.PIVOT_POINT


def test_bollinger_squeeze_strategy_has_correct_name():
    assert BollingerSqueezeStrategy().name == StrategyName.BOLLINGER_SQUEEZE


def test_supply_demand_strategy_has_correct_name():
    assert SupplyDemandStrategy().name == StrategyName.SUPPLY_DEMAND


def test_relative_strength_strategy_has_correct_name():
    assert RelativeStrengthStrategy().name == StrategyName.RELATIVE_STRENGTH


# ----- Signal generation tests -----

def test_gap_and_go_returns_signal_or_none():
    strategy = GapAndGoStrategy()
    df = _trending_up_df()
    snapshot = _make_snapshot()
    result = strategy.generate_signal(df, snapshot)
    assert result is None or hasattr(result, "direction")


def test_gap_and_go_needs_gap():
    """No gap => no signal."""
    strategy = GapAndGoStrategy()
    n = 30
    close = np.full(n, 500.0)
    df = pd.DataFrame({
        "open": close, "high": close + 1, "low": close - 1,
        "close": close,
        "volume": np.full(n, 1_000_000),
    })
    snapshot = _make_snapshot(last_close=500.0)
    assert strategy.generate_signal(df, snapshot) is None


def test_gap_and_go_long_on_bullish_gap():
    """Big gap up with volume surge and price holding above gap => LONG."""
    strategy = GapAndGoStrategy()
    n = 30
    close = np.full(n, 500.0)
    # Set previous close to 500, current open gaps to 510 (2% gap)
    close[-1] = 512.0  # holds above 510 open
    df = pd.DataFrame({
        "open": np.append(close[:-1], [510.0]),
        "high": close + 5,
        "low": close - 2,
        "close": close,
        "volume": np.append(np.full(n - 1, 500_000), [2_000_000]),
    })
    snapshot = _make_snapshot(last_close=512.0)
    result = strategy.generate_signal(df, snapshot)
    assert result is not None
    assert result.direction == Direction.LONG


def test_pivot_point_returns_signal_or_none():
    strategy = PivotPointStrategy()
    df = _trending_up_df()
    snapshot = _make_snapshot()
    result = strategy.generate_signal(df, snapshot)
    assert result is None or hasattr(result, "direction")


def test_pivot_point_long_near_support():
    """Price near support with low RSI => LONG."""
    strategy = PivotPointStrategy()
    df = _trending_up_df()
    snapshot = _make_snapshot(
        last_close=490.5,  # near support 490.0 (0.1% away)
        rsi_14=35.0,
        support_levels=[490.0, 480.0],
    )
    result = strategy.generate_signal(df, snapshot)
    assert result is not None
    assert result.direction == Direction.LONG


def test_pivot_point_short_near_resistance():
    """Price near resistance with high RSI => SHORT."""
    strategy = PivotPointStrategy()
    df = _trending_up_df()
    snapshot = _make_snapshot(
        last_close=509.8,  # near resistance 510.0
        rsi_14=65.0,
        resistance_levels=[510.0, 520.0],
    )
    result = strategy.generate_signal(df, snapshot)
    assert result is not None
    assert result.direction == Direction.SHORT


def test_bollinger_squeeze_detects_low_bandwidth():
    strategy = BollingerSqueezeStrategy()
    df = _trending_up_df()
    snapshot = _make_snapshot(bb_bandwidth=1.5)  # low bandwidth = squeeze
    result = strategy.generate_signal(df, snapshot)
    # With low bandwidth and uptrend, might generate long signal
    assert result is None or result.direction in (Direction.LONG, Direction.SHORT)


def test_bollinger_squeeze_long_on_breakout():
    """Low bandwidth + price above upper band + ADX > 20 => LONG."""
    strategy = BollingerSqueezeStrategy()
    df = _trending_up_df()
    snapshot = _make_snapshot(
        bb_bandwidth=2.0, bb_upper=505.0, bb_lower=495.0,
        last_close=506.0, adx_14=25.0,
    )
    result = strategy.generate_signal(df, snapshot)
    assert result is not None
    assert result.direction == Direction.LONG


def test_bollinger_squeeze_no_signal_high_bandwidth():
    """High bandwidth (no squeeze) => no signal."""
    strategy = BollingerSqueezeStrategy()
    df = _trending_up_df()
    snapshot = _make_snapshot(bb_bandwidth=5.0)
    assert strategy.generate_signal(df, snapshot) is None


def test_supply_demand_returns_signal_or_none():
    strategy = SupplyDemandStrategy()
    df = _trending_up_df()
    snapshot = _make_snapshot()
    result = strategy.generate_signal(df, snapshot)
    assert result is None or hasattr(result, "direction")


def test_supply_demand_needs_data():
    """Not enough data => no signal."""
    strategy = SupplyDemandStrategy()
    df = _trending_up_df(n=10)
    snapshot = _make_snapshot()
    assert strategy.generate_signal(df, snapshot) is None


def test_relative_strength_returns_signal_or_none():
    strategy = RelativeStrengthStrategy()
    df = _trending_up_df()
    snapshot = _make_snapshot()
    result = strategy.generate_signal(df, snapshot)
    assert result is None or hasattr(result, "direction")


def test_relative_strength_long_trending():
    """Price above all MAs + ADX > 25 + MACD confirms => LONG."""
    strategy = RelativeStrengthStrategy()
    df = _trending_up_df()
    snapshot = _make_snapshot(
        last_close=510.0, sma_20=505.0, sma_50=500.0, sma_200=490.0,
        adx_14=30.0, macd=2.0, macd_signal=1.0,
    )
    result = strategy.generate_signal(df, snapshot)
    assert result is not None
    assert result.direction == Direction.LONG


def test_relative_strength_short_downtrend():
    """Price below all MAs + ADX > 25 + MACD confirms => SHORT."""
    strategy = RelativeStrengthStrategy()
    df = _trending_up_df()
    snapshot = _make_snapshot(
        last_close=480.0, sma_20=485.0, sma_50=490.0, sma_200=495.0,
        adx_14=30.0, macd=-2.0, macd_signal=-1.0,
    )
    result = strategy.generate_signal(df, snapshot)
    assert result is not None
    assert result.direction == Direction.SHORT


def test_relative_strength_no_signal_weak_adx():
    """ADX too low => no signal despite MA alignment."""
    strategy = RelativeStrengthStrategy()
    df = _trending_up_df()
    snapshot = _make_snapshot(
        last_close=510.0, sma_20=505.0, sma_50=500.0,
        adx_14=15.0, macd=2.0, macd_signal=1.0,
    )
    assert strategy.generate_signal(df, snapshot) is None


# ----- Confluence tests -----

def test_confluence_scorer():
    scorer = ConfluenceScorer()
    snapshot = _make_snapshot(
        last_close=505.0, sma_50=495.0, sma_200=490.0,
        macd=2.0, macd_signal=1.0, rsi_14=60.0,
        ema_9=504.0, ema_12=503.0,
    )
    score = scorer.score(snapshot, Direction.LONG)
    assert isinstance(score, int)
    assert 0 <= score <= 5


def test_confluence_scorer_max_long():
    """All dimensions agree LONG => score 5."""
    scorer = ConfluenceScorer()
    snapshot = _make_snapshot(
        last_close=510.0, sma_50=495.0,  # above 50 SMA
        macd=3.0, macd_signal=1.0,        # MACD bullish
        rsi_14=55.0,                       # RSI in 40-70
        supertrend_direction=1,            # bullish supertrend
        vwap=500.0,                        # above VWAP
    )
    assert scorer.score(snapshot, Direction.LONG) == 5


def test_confluence_scorer_max_short():
    """All dimensions agree SHORT => score 5."""
    scorer = ConfluenceScorer()
    snapshot = _make_snapshot(
        last_close=480.0, sma_50=495.0,   # below 50 SMA
        macd=-3.0, macd_signal=-1.0,       # MACD bearish
        rsi_14=45.0,                        # RSI in 30-60
        supertrend_direction=-1,            # bearish supertrend
        vwap=500.0,                         # below VWAP
    )
    assert scorer.score(snapshot, Direction.SHORT) == 5


def test_confluence_scorer_no_agreement():
    """Nothing aligns for LONG => score 0."""
    scorer = ConfluenceScorer()
    snapshot = _make_snapshot(
        last_close=480.0, sma_50=500.0,    # below 50 SMA (not LONG)
        macd=-2.0, macd_signal=-1.0,        # MACD bearish (not LONG)
        rsi_14=75.0,                         # RSI > 70 (not LONG range)
        supertrend_direction=-1,             # bearish (not LONG)
        vwap=500.0,                          # below VWAP (not LONG)
    )
    assert scorer.score(snapshot, Direction.LONG) == 0


# ----- Registry test -----

def test_strategy_registry_has_10_strategies():
    from tradingbot.strategy.strategies import STRATEGY_REGISTRY
    assert len(STRATEGY_REGISTRY) == 10
