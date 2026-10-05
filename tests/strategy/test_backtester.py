import numpy as np
import pandas as pd
import pytest

from tradingbot.core.models import Direction, StrategyName
from tradingbot.strategy.backtester import Backtester
from tradingbot.strategy.strategies.base import Signal, Strategy


def make_candles(closes, spread=1.0):
    index = pd.date_range("2026-08-01 09:15", periods=len(closes), freq="15min", tz="Asia/Kolkata")
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes + spread,
            "low": closes - spread,
            "close": closes,
            "volume": np.full(len(closes), 10000.0),
        },
        index=index,
    )


class AlwaysLongStrategy(Strategy):
    """Fires on every bar with a fixed 10 point stop and 20 point first target."""

    name = StrategyName.BREAKOUT

    def generate_signal(self, df, snapshot):
        price = float(df["close"].iloc[-1])
        return Signal(
            direction=Direction.LONG,
            entry_price=price,
            stop_loss=price - 10.0,
            target_1=price + 20.0,
            target_2=price + 30.0,
            strength=0.8,
        )


class NeverFiresStrategy(Strategy):
    name = StrategyName.ORB

    def generate_signal(self, df, snapshot):
        return None


def test_a_relentless_uptrend_produces_a_perfect_win_rate():
    df = make_candles(np.arange(100, 500, dtype=float))

    result = Backtester().run("RELIANCE", df, AlwaysLongStrategy())

    assert result.trades > 0
    assert result.wins == result.trades
    assert result.win_rate == pytest.approx(1.0)


def test_a_relentless_downtrend_produces_a_zero_win_rate():
    df = make_candles(np.arange(500, 100, -1, dtype=float))

    result = Backtester().run("RELIANCE", df, AlwaysLongStrategy())

    assert result.trades > 0
    assert result.wins == 0
    assert result.win_rate == pytest.approx(0.0)


def test_a_strategy_that_never_fires_reports_zero_trades():
    df = make_candles(np.arange(100, 300, dtype=float))

    result = Backtester().run("RELIANCE", df, NeverFiresStrategy())

    assert result.trades == 0
    assert result.wins == 0
    assert result.win_rate == pytest.approx(0.0)
    assert result.avg_reward_risk == pytest.approx(0.0)


def test_the_result_carries_the_symbol_and_strategy_name():
    df = make_candles(np.arange(100, 400, dtype=float))

    result = Backtester().run("TCS", df, AlwaysLongStrategy())

    assert result.symbol == "TCS"
    assert result.strategy is StrategyName.BREAKOUT


def test_avg_reward_risk_reflects_the_configured_geometry():
    df = make_candles(np.arange(100, 500, dtype=float))

    result = Backtester().run("RELIANCE", df, AlwaysLongStrategy())

    # 20 points of reward against 10 points of risk.
    assert result.avg_reward_risk == pytest.approx(2.0)


def test_too_few_candles_yields_an_empty_result_rather_than_raising():
    df = make_candles([100.0, 101.0])

    result = Backtester().run("RELIANCE", df, AlwaysLongStrategy())

    assert result.trades == 0


def test_run_all_returns_one_result_per_registered_strategy():
    df = make_candles(np.arange(100, 400, dtype=float))

    results = Backtester().run_all("RELIANCE", df)

    assert len(results) == len(set(StrategyName))
    assert {result.strategy for result in results} == set(StrategyName)


def test_backtesting_never_mutates_the_candle_frame():
    df = make_candles(np.arange(100, 400, dtype=float))
    before = df.copy(deep=True)

    Backtester().run("RELIANCE", df, AlwaysLongStrategy())

    pd.testing.assert_frame_equal(df, before)


def test_backtest_2000_candles_completes_under_15_seconds():
    import time
    df = make_candles(np.arange(100, 2100, dtype=float))
    start = time.monotonic()
    result = Backtester().run("PERF", df, AlwaysLongStrategy())
    elapsed = time.monotonic() - start
    assert elapsed < 15.0, f"Backtest took {elapsed:.1f}s, expected < 15s"
    assert result.trades > 0


class SnapshotRecorder(Strategy):
    """Records the snapshot it receives so tests can inspect for lookahead."""
    name = StrategyName.BREAKOUT
    snapshots: list = []

    def generate_signal(self, df, snapshot):
        self.snapshots.append((len(df), snapshot.last_close))
        return None


def test_snapshot_does_not_leak_future_candle():
    closes = np.arange(100.0, 200.0)
    df = make_candles(closes)
    recorder = SnapshotRecorder()
    recorder.snapshots = []
    Backtester().run("TEST", df, recorder)
    for window_len, snap_close in recorder.snapshots:
        expected_close = closes[window_len - 1]
        assert snap_close == pytest.approx(expected_close, abs=0.01), \
            f"At window_len={window_len}: snapshot.last_close={snap_close} but last candle close={expected_close}"
