"""Monte Carlo simulation over trade PnL sequences.

Shuffles the trade PnL order N times, builds equity curves, and reports
percentile returns, max drawdowns, and risk of ruin.
"""

from __future__ import annotations

import numpy as np

from tradingbot.core.models import MonteCarloResult


class MonteCarloSimulator:
    """Shuffle trade PnLs to estimate return distribution and ruin risk."""

    def __init__(
        self,
        simulations: int = 10000,
        capital: float = 400000,
        ruin_threshold: float = 0.25,
    ):
        self._sims = simulations
        self._capital = capital
        self._ruin_threshold = ruin_threshold

    def run(self, trade_pnls: list[float]) -> MonteCarloResult:
        """Run Monte Carlo simulation over trade PnL sequence."""
        if len(trade_pnls) < 5:
            return MonteCarloResult(
                simulations=self._sims,
                median_return_pct=0.0,
                p10_return_pct=0.0,
                p90_return_pct=0.0,
                median_max_drawdown=0.0,
                p95_max_drawdown=0.0,
                risk_of_ruin_pct=100.0 if not trade_pnls else 50.0,
                confidence_score=0.0,
            )

        pnls = np.array(trade_pnls)
        returns: list[float] = []
        max_drawdowns: list[float] = []
        ruin_count = 0

        for _ in range(self._sims):
            shuffled = np.random.permutation(pnls)
            equity = np.cumsum(shuffled)
            final_return = float(equity[-1] / self._capital * 100)
            returns.append(final_return)

            peak = np.maximum.accumulate(self._capital + equity)
            dd = (peak - (self._capital + equity)) / peak * 100
            max_drawdowns.append(float(np.max(dd)))

            if np.min(self._capital + equity) <= self._capital * (
                1 - self._ruin_threshold
            ):
                ruin_count += 1

        returns_arr = np.array(returns)
        dd_arr = np.array(max_drawdowns)

        win_rate = float(np.mean(pnls > 0))
        negative_sum = abs(float(np.sum(pnls[pnls < 0])))
        pf = (
            float(np.sum(pnls[pnls > 0])) / negative_sum
            if negative_sum > 0
            else 10.0
        )
        ruin_pct = ruin_count / self._sims * 100
        confidence = float(win_rate * min(pf, 5) / 5 * (1 - ruin_pct / 100))

        return MonteCarloResult(
            simulations=self._sims,
            median_return_pct=float(np.median(returns_arr)),
            p10_return_pct=float(np.percentile(returns_arr, 10)),
            p90_return_pct=float(np.percentile(returns_arr, 90)),
            median_max_drawdown=float(np.median(dd_arr)),
            p95_max_drawdown=float(np.percentile(dd_arr, 95)),
            risk_of_ruin_pct=float(ruin_pct),
            confidence_score=max(0.0, min(1.0, confidence)),
        )
