"""Walk-forward backtest: replay candles, let the strategy speak, score the outcome.

This exists to give the LLM evidence about which strategy has been working on a
given symbol recently. It is deliberately simple: one position at a time, exit on
whichever of stop or target 1 is touched first, no pyramiding and no costs model.
"""

from __future__ import annotations

import logging

import pandas as pd

from tradingbot.core.models import BacktestResult, Direction, StrategyName
from tradingbot.strategy.indicators import InsufficientDataError, compute_snapshot
from tradingbot.strategy.strategies import Strategy, all_strategies

logger = logging.getLogger(__name__)

WARMUP_CANDLES = 50
MAX_HOLD_CANDLES = 26  # roughly one session of 15 minute bars
SUPPORT_RESISTANCE_INTERVAL = 25


class Backtester:
    """Replays history one candle at a time and records simulated outcomes."""

    def __init__(self, strategies: list[Strategy] | None = None) -> None:
        self.strategies = strategies if strategies is not None else all_strategies()

    def run(self, symbol: str, df: pd.DataFrame, strategy: Strategy) -> BacktestResult:
        """Score one strategy on one symbol over the supplied candles."""
        if len(df) <= WARMUP_CANDLES:
            return BacktestResult(
                symbol=symbol,
                strategy=strategy.name,
                trades=0,
                wins=0,
                win_rate=0.0,
                avg_reward_risk=0.0,
            )

        from tradingbot.strategy.indicators import precompute_indicator_series

        indicator_series = precompute_indicator_series(symbol, df)

        trades = 0
        wins = 0
        reward_risks: list[float] = []
        index = WARMUP_CANDLES
        last_sr_index = -SUPPORT_RESISTANCE_INTERVAL
        supports: list[float] = []
        resistances: list[float] = []
        vol_prof = {"poc": 0.0, "vah": 0.0, "val": 0.0}

        while index < len(df):
            if index - last_sr_index >= SUPPORT_RESISTANCE_INTERVAL:
                from tradingbot.strategy.indicators import support_resistance, volume_profile
                window = df.iloc[:index]
                try:
                    supports, resistances = support_resistance(window)
                except Exception:
                    supports, resistances = [], []
                try:
                    vol_prof = volume_profile(window)
                except Exception:
                    vol_prof = {"poc": 0.0, "vah": 0.0, "val": 0.0}
                last_sr_index = index

            snapshot = self._snapshot_at(symbol, indicator_series, index,
                                         supports, resistances, vol_prof)

            signal = strategy.generate_signal(df.iloc[:index], snapshot)
            if signal is None:
                index += 1
                continue

            outcome, exit_index = self._resolve(df, index, signal)
            if outcome is None:
                break

            trades += 1
            wins += 1 if outcome else 0
            risk = abs(signal.entry_price - signal.stop_loss)
            if risk > 0:
                reward_risks.append(abs(signal.target_1 - signal.entry_price) / risk)

            index = exit_index + 1

        return BacktestResult(
            symbol=symbol,
            strategy=strategy.name,
            trades=trades,
            wins=wins,
            win_rate=wins / trades if trades else 0.0,
            avg_reward_risk=sum(reward_risks) / len(reward_risks) if reward_risks else 0.0,
        )

    @staticmethod
    def _snapshot_at(
        symbol: str,
        series: dict,
        index: int,
        supports: list[float],
        resistances: list[float],
        vol_prof: dict,
    ):
        import numpy as np
        from tradingbot.core.models import IndicatorSnapshot

        def safe(s, idx, fallback=0.0):
            if isinstance(s, pd.Series) and idx < len(s):
                val = s.iloc[idx]
                return float(val) if not (isinstance(val, float) and np.isnan(val)) else fallback
            return fallback

        last_close = safe(series["last_close"], index, 100.0)
        return IndicatorSnapshot(
            symbol=symbol,
            last_close=last_close,
            rsi_14=safe(series["rsi_14"], index, 50.0),
            macd=safe(series["macd"], index),
            macd_signal=safe(series["macd_signal"], index),
            bb_upper=safe(series["bb_upper"], index, last_close),
            bb_middle=safe(series["bb_middle"], index, last_close),
            bb_lower=safe(series["bb_lower"], index, last_close),
            atr_14=safe(series["atr_14"], index, 1.0),
            sma_9=safe(series.get("sma_9", pd.Series(dtype=float)), index, last_close),
            sma_20=safe(series["sma_20"], index, last_close),
            sma_50=safe(series["sma_50"], index, last_close),
            sma_200=safe(series["sma_200"], index, last_close),
            ema_9=safe(series.get("ema_9", pd.Series(dtype=float)), index, last_close),
            ema_12=safe(series["ema_12"], index, last_close),
            ema_26=safe(series["ema_26"], index, last_close),
            vwap=safe(series["vwap"], index, last_close),
            pivot=safe(series["pivot"], index, last_close),
            support_levels=supports,
            resistance_levels=resistances,
            adx_14=safe(series["adx_14"], index),
            supertrend=safe(series["supertrend"], index),
            supertrend_direction=int(safe(series["supertrend_direction"], index, 1)),
            bb_bandwidth=safe(series["bb_bandwidth"], index),
            vwap_upper_1=safe(series["vwap_upper_1"], index),
            vwap_lower_1=safe(series["vwap_lower_1"], index),
            poc=vol_prof.get("poc", 0.0),
            vah=vol_prof.get("vah", 0.0),
            val=vol_prof.get("val", 0.0),
        )

    def run_all(self, symbol: str, df: pd.DataFrame) -> list[BacktestResult]:
        """Score every registered strategy on one symbol."""
        return [self.run(symbol, df, strategy) for strategy in self.strategies]

    @staticmethod
    def _resolve(df: pd.DataFrame, entry_index: int, signal) -> tuple[bool | None, int]:
        """Walk forward until stop or target 1 is touched. True means the target won."""
        end = min(entry_index + MAX_HOLD_CANDLES, len(df))

        for position in range(entry_index, end):
            candle = df.iloc[position]
            high, low = float(candle["high"]), float(candle["low"])

            if signal.direction is Direction.LONG:
                if low <= signal.stop_loss:
                    return False, position
                if high >= signal.target_1:
                    return True, position
            else:
                if high >= signal.stop_loss:
                    return False, position
                if low <= signal.target_1:
                    return True, position

        if end <= entry_index:
            return None, entry_index

        # Ran out of holding time: score on where the close finished.
        final_close = float(df.iloc[end - 1]["close"])
        if signal.direction is Direction.LONG:
            return final_close > signal.entry_price, end - 1
        return final_close < signal.entry_price, end - 1

    @staticmethod
    def _lenient_snapshot(symbol: str, window: pd.DataFrame):
        """A reduced snapshot for early windows, so warmup does not abort the run."""
        from tradingbot.core.models import IndicatorSnapshot
        from tradingbot.strategy.indicators import (
            atr,
            bollinger_bands,
            ema,
            macd,
            pivot_points,
            rsi,
            sma,
            vwap,
        )

        close = window["close"]
        macd_line, signal_line = macd(close)
        upper, middle, lower = bollinger_bands(close)

        def last(series: pd.Series, fallback: float) -> float:
            value = series.iloc[-1]
            return float(value) if pd.notna(value) else fallback

        last_close = float(close.iloc[-1])
        return IndicatorSnapshot(
            symbol=symbol,
            last_close=last_close,
            rsi_14=last(rsi(close), 50.0),
            macd=last(macd_line, 0.0),
            macd_signal=last(signal_line, 0.0),
            bb_upper=last(upper, last_close),
            bb_middle=last(middle, last_close),
            bb_lower=last(lower, last_close),
            atr_14=last(atr(window), 1.0),
            sma_20=last(sma(close, 20), last_close),
            sma_50=last(sma(close, 50), last_close),
            sma_200=last(sma(close, 200), last_close),
            ema_12=last(ema(close, 12), last_close),
            ema_26=last(ema(close, 26), last_close),
            vwap=last(vwap(window), last_close),
            pivot=float(pivot_points(window)["pivot"]),
            support_levels=[],
            resistance_levels=[],
        )
