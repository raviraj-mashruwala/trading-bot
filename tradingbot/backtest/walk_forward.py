"""Walk-forward backtesting engine with OOS validation and transaction costs.

Splits data into configurable windows, trains on train_pct%, validates on
the rest, and reports out-of-sample degradation.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date

import numpy as np
import pandas as pd

from tradingbot.backtest.costs import ZerodhaCosts
from tradingbot.core.models import BacktestReport, StrategyName
from tradingbot.strategy.indicators import InsufficientDataError, compute_snapshot
from tradingbot.strategy.strategies.base import Signal, Strategy

WARMUP = 200
MAX_HOLD = 26


class WalkForwardEngine:
    """Walk-forward backtesting with OOS validation and transaction costs."""

    def __init__(
        self,
        windows: int = 10,
        train_pct: int = 70,
        include_costs: bool = True,
        slippage_pct: float = 0.02,
    ):
        self._windows = windows
        self._train_pct = train_pct / 100.0
        self._costs = ZerodhaCosts(slippage_pct) if include_costs else None

    def run(
        self, symbol: str, df: pd.DataFrame, strategy: Strategy
    ) -> BacktestReport:
        """Run walk-forward backtest, return aggregated report."""
        if len(df) < WARMUP + 50:
            return self._empty_report(symbol, strategy.name, df)

        usable = df.iloc[WARMUP:]
        window_size = len(usable) // self._windows
        if window_size < 20:
            return self._empty_report(symbol, strategy.name, df)

        is_wins: list[float] = []
        oos_wins: list[float] = []
        all_trades: list[dict] = []

        for w in range(self._windows):
            start = w * window_size
            end = min(start + window_size, len(usable))
            window = usable.iloc[start:end]
            split = int(len(window) * self._train_pct)

            is_data = df.iloc[: WARMUP + start + split]
            oos_data = df.iloc[: WARMUP + start + end]

            is_trades = self._simulate(
                symbol, is_data, strategy, WARMUP + start, WARMUP + start + split
            )
            oos_trades = self._simulate(
                symbol, oos_data, strategy, WARMUP + start + split, WARMUP + start + end
            )

            if is_trades:
                is_wins.append(
                    sum(1 for t in is_trades if t["pnl"] > 0) / len(is_trades)
                )
            if oos_trades:
                oos_wins.append(
                    sum(1 for t in oos_trades if t["pnl"] > 0) / len(oos_trades)
                )
            all_trades.extend(oos_trades)

        return self._build_report(symbol, strategy.name, df, all_trades, is_wins, oos_wins)

    def _simulate(
        self,
        symbol: str,
        full_df: pd.DataFrame,
        strategy: Strategy,
        start_idx: int,
        end_idx: int,
    ) -> list[dict]:
        trades: list[dict] = []
        i = start_idx
        while i < end_idx - 1:
            window = full_df.iloc[: i + 1]
            try:
                snapshot = compute_snapshot(symbol, window)
            except InsufficientDataError:
                i += 1
                continue

            signal = strategy.generate_signal(window, snapshot)
            if signal is None:
                i += 1
                continue

            won, exit_idx, exit_price = self._resolve(full_df, i, signal, end_idx)
            if signal.direction.value == "long":
                pnl = exit_price - signal.entry_price
            else:
                pnl = signal.entry_price - exit_price

            if self._costs:
                cost = self._costs.round_trip_cost(signal.entry_price, exit_price, 1)
                pnl -= cost

            trades.append(
                {
                    "pnl": pnl,
                    "won": pnl > 0,
                    "entry": signal.entry_price,
                    "exit": exit_price,
                    "regime": self._tag_regime(full_df, i),
                }
            )
            i = exit_idx + 1

        return trades

    def _tag_regime(self, df: pd.DataFrame, idx: int) -> str:
        """Classify market regime at index based on SMA20/50 relationship."""
        if idx < 50:
            return "unknown"
        close = float(df["close"].iloc[idx])
        sma20 = float(df["close"].iloc[idx - 20:idx].mean())
        sma50 = float(df["close"].iloc[idx - 50:idx].mean())
        if close > sma20 > sma50:
            return "trending_up"
        if close < sma20 < sma50:
            return "trending_down"
        return "range_bound"

    def _resolve(
        self,
        df: pd.DataFrame,
        entry_idx: int,
        signal: Signal,
        max_idx: int,
    ) -> tuple[bool, int, float]:
        for j in range(entry_idx + 1, min(entry_idx + MAX_HOLD + 1, max_idx)):
            price = float(df.iloc[j]["close"])
            if signal.direction.value == "long":
                if price <= signal.stop_loss:
                    return False, j, signal.stop_loss
                if price >= signal.target_1:
                    return True, j, signal.target_1
            else:
                if price >= signal.stop_loss:
                    return False, j, signal.stop_loss
                if price <= signal.target_1:
                    return True, j, signal.target_1

        last_idx = min(entry_idx + MAX_HOLD, max_idx - 1)
        last = float(df.iloc[last_idx]["close"])
        if signal.direction.value == "long":
            won = last > signal.entry_price
        else:
            won = last < signal.entry_price
        return won, last_idx, last

    def _build_report(
        self,
        symbol: str,
        strategy_name: StrategyName,
        df: pd.DataFrame,
        trades: list[dict],
        is_wins: list[float],
        oos_wins: list[float],
    ) -> BacktestReport:
        if not trades:
            return self._empty_report(symbol, strategy_name, df)

        winners = [t for t in trades if t["pnl"] > 0]
        losers = [t for t in trades if t["pnl"] <= 0]
        win_rate = len(winners) / len(trades) if trades else 0
        avg_w = float(np.mean([t["pnl"] for t in winners])) if winners else 0.0
        avg_l = float(np.mean([t["pnl"] for t in losers])) if losers else 0.0
        gross_profit = sum(t["pnl"] for t in winners)
        gross_loss = abs(sum(t["pnl"] for t in losers))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        expectancy = float(np.mean([t["pnl"] for t in trades]))

        avg_risk = float(
            np.mean([abs(t["entry"] - t["exit"]) for t in trades])
        ) if trades else 1.0
        expectancy_r = expectancy / avg_risk if avg_risk > 0 else 0.0

        pnls = [t["pnl"] for t in trades]
        std = float(np.std(pnls))
        sharpe = (float(np.mean(pnls)) / std * math.sqrt(252)) if std > 0 else 0.0

        equity = np.cumsum(pnls)
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / np.where(peak > 0, peak, 1) * 100
        max_dd = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0

        max_consec = 0
        current = 0
        for t in trades:
            if t["pnl"] <= 0:
                current += 1
                max_consec = max(max_consec, current)
            else:
                current = 0

        is_mean = float(np.mean(is_wins)) if is_wins else 0.0
        oos_mean = float(np.mean(oos_wins)) if oos_wins else 0.0
        oos_deg = max(0.0, is_mean - oos_mean) if is_mean > 0 else 0.0

        calmar = (expectancy * 252 / max_dd) if max_dd > 0 else 0.0

        # Aggregate per-regime performance stats
        regime_buckets: dict[str, list[dict]] = defaultdict(list)
        for t in trades:
            regime_buckets[t.get("regime", "unknown")].append(t)

        regime_performance: dict[str, dict] = {}
        for regime, bucket in regime_buckets.items():
            w = [t for t in bucket if t["pnl"] > 0]
            l = [t for t in bucket if t["pnl"] <= 0]
            gross_loss_regime = abs(sum(t["pnl"] for t in l))
            gross_profit_regime = sum(t["pnl"] for t in w)
            regime_performance[regime] = {
                "trades": len(bucket),
                "win_rate": len(w) / len(bucket) if bucket else 0,
                "profit_factor": (
                    gross_profit_regime / gross_loss_regime
                    if gross_loss_regime > 0
                    else float("inf") if gross_profit_regime > 0 else 0.0
                ),
            }

        return BacktestReport(
            symbol=symbol,
            strategy=strategy_name,
            period_start=date.today(),
            period_end=date.today(),
            total_trades=len(trades),
            winners=len(winners),
            losers=len(losers),
            win_rate=win_rate,
            avg_winner=avg_w,
            avg_loser=avg_l,
            profit_factor=profit_factor,
            expectancy=expectancy,
            expectancy_r=expectancy_r,
            sharpe_ratio=sharpe,
            max_drawdown_pct=max_dd,
            max_consecutive_losses=max_consec,
            avg_hold_minutes=0.0,
            oos_degradation=oos_deg,
            calmar_ratio=calmar,
            regime_performance=regime_performance,
        )

    def _empty_report(
        self, symbol: str, strategy_name: StrategyName, df: pd.DataFrame
    ) -> BacktestReport:
        return BacktestReport(
            symbol=symbol,
            strategy=strategy_name,
            period_start=date.today(),
            period_end=date.today(),
            total_trades=0,
            winners=0,
            losers=0,
            win_rate=0.0,
            avg_winner=0.0,
            avg_loser=0.0,
            profit_factor=0.0,
            expectancy=0.0,
            expectancy_r=0.0,
            sharpe_ratio=0.0,
            max_drawdown_pct=0.0,
            max_consecutive_losses=0,
            avg_hold_minutes=0.0,
            oos_degradation=0.0,
            calmar_ratio=0.0,
        )
