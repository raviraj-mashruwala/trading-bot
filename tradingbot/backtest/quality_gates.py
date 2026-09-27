"""Eight non-negotiable quality gates for strategy approval.

Gates: min trades, win rate, profit factor, expectancy R, OOS degradation,
Monte Carlo P10 > 0, ruin risk, and max consecutive losses.
"""

from __future__ import annotations

from tradingbot.core.models import BacktestReport, MonteCarloResult, QualityGateResult


class QualityGates:
    """Evaluate a backtest + MC result against non-negotiable thresholds."""

    def __init__(
        self,
        min_trades: int = 30,
        min_win_rate: float = 0.45,
        min_profit_factor: float = 1.5,
        min_expectancy_r: float = 0.3,
        max_oos_degradation: float = 0.3,
        max_risk_of_ruin: float = 5.0,
        max_consecutive_losses: int = 8,
    ):
        self._min_trades = min_trades
        self._min_wr = min_win_rate
        self._min_pf = min_profit_factor
        self._min_er = min_expectancy_r
        self._max_oos = max_oos_degradation
        self._max_ruin = max_risk_of_ruin
        self._max_consec = max_consecutive_losses

    def evaluate(
        self, report: BacktestReport, mc: MonteCarloResult
    ) -> QualityGateResult:
        """Run all 8 gates, return pass/fail with per-criterion flags."""
        failures: list[str] = []

        trades_ok = report.total_trades >= self._min_trades
        if not trades_ok:
            failures.append(
                f"total_trades: {report.total_trades} < {self._min_trades}"
            )

        wr_ok = report.win_rate >= self._min_wr
        if not wr_ok:
            failures.append(f"win_rate: {report.win_rate:.2f} < {self._min_wr}")

        pf_ok = report.profit_factor >= self._min_pf
        if not pf_ok:
            failures.append(
                f"profit_factor: {report.profit_factor:.2f} < {self._min_pf}"
            )

        er_ok = report.expectancy_r >= self._min_er
        if not er_ok:
            failures.append(
                f"expectancy_r: {report.expectancy_r:.2f} < {self._min_er}"
            )

        oos_ok = report.oos_degradation <= self._max_oos
        if not oos_ok:
            failures.append(
                f"oos_degradation: {report.oos_degradation:.2f} > {self._max_oos}"
            )

        mc_p10_ok = mc.p10_return_pct > 0
        if not mc_p10_ok:
            failures.append(f"monte_carlo_p10: {mc.p10_return_pct:.2f}% <= 0")

        ruin_ok = mc.risk_of_ruin_pct <= self._max_ruin
        if not ruin_ok:
            failures.append(
                f"risk_of_ruin: {mc.risk_of_ruin_pct:.1f}% > {self._max_ruin}%"
            )

        consec_ok = report.max_consecutive_losses <= self._max_consec
        if not consec_ok:
            failures.append(
                f"max_consecutive_losses: {report.max_consecutive_losses} > {self._max_consec}"
            )

        return QualityGateResult(
            passed=len(failures) == 0,
            total_trades_ok=trades_ok,
            win_rate_ok=wr_ok,
            profit_factor_ok=pf_ok,
            expectancy_ok=er_ok,
            oos_ok=oos_ok,
            monte_carlo_p10_ok=mc_p10_ok,
            ruin_risk_ok=ruin_ok,
            consecutive_losses_ok=consec_ok,
            failures=failures,
        )
