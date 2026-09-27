"""Tests for extended data models added in the analysis pipeline redesign."""

from tradingbot.core.models import (
    StrategyName, MarketRegime, SetupStatus, ExecutionMode,
    ScoredStock, AnalysisRun, BacktestReport, MonteCarloResult,
    QualityGateResult, MarketContext,
)
from datetime import datetime, date
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def test_strategy_name_includes_new_strategies():
    assert StrategyName.GAP_AND_GO.value == "gap_and_go"
    assert StrategyName.PIVOT_POINT.value == "pivot_point"
    assert StrategyName.RELATIVE_STRENGTH.value == "relative_strength"
    assert StrategyName.BOLLINGER_SQUEEZE.value == "bollinger_squeeze"
    assert StrategyName.SUPPLY_DEMAND.value == "supply_demand"
    assert len(StrategyName) == 10


def test_market_regime_includes_low_vol_squeeze():
    assert MarketRegime.LOW_VOL_SQUEEZE.value == "low_vol_squeeze"
    assert MarketRegime.TRENDING_UP.value == "trending_up"
    assert MarketRegime.TRENDING_DOWN.value == "trending_down"
    assert len(MarketRegime) == 5


def test_setup_status_lifecycle():
    assert SetupStatus.PROPOSED.value == "proposed"
    assert SetupStatus.APPROVED.value == "approved"
    assert SetupStatus.REJECTED.value == "rejected"
    assert SetupStatus.ACTIVE.value == "active"
    assert SetupStatus.FILLED.value == "filled"
    assert SetupStatus.EXPIRED.value == "expired"
    assert SetupStatus.CLOSED.value == "closed"


def test_execution_mode():
    assert ExecutionMode.PAPER.value == "paper"
    assert ExecutionMode.LIVE.value == "live"
    assert ExecutionMode.SHADOW.value == "shadow"


def test_scored_stock():
    stock = ScoredStock(
        symbol="RELIANCE", exchange="NSE", last_price=2500.0,
        avg_volume=5_000_000, market_cap_cr=17_00_000, atr_pct=1.2,
        sector="energy", composite_score=78.5,
        factor_scores={"volume_surge": 85, "relative_strength": 72},
        instrument_token=738561,
    )
    assert stock.composite_score == 78.5
    assert stock.factor_scores["volume_surge"] == 85


def test_analysis_run():
    run = AnalysisRun(
        run_id="run_20260927_093015_abc123",
        timestamp=datetime.now(tz=IST),
        trade_date=date(2026, 9, 27),
        market_regime=MarketRegime.TRENDING_UP,
        regime_confidence=0.82,
        total_scanned=1500, tier1_passed=80,
        tier2_shortlisted=12, setups_proposed=8,
        setups_approved=5, llm_calls=16,
        llm_cost_usd=0.18, duration_seconds=45.2,
    )
    assert run.run_id.startswith("run_")
    assert run.tier1_passed == 80


def test_backtest_report():
    report = BacktestReport(
        symbol="RELIANCE", strategy=StrategyName.VWAP_BOUNCE,
        period_start=date(2025, 9, 27), period_end=date(2026, 9, 27),
        total_trades=47, winners=29, losers=18,
        win_rate=0.617, avg_winner=4850.0, avg_loser=-2890.0,
        profit_factor=2.70, expectancy=1740.0, expectancy_r=0.62,
        sharpe_ratio=1.85, max_drawdown_pct=4.2,
        max_consecutive_losses=4, avg_hold_minutes=47,
        oos_degradation=0.12, calmar_ratio=2.1,
    )
    assert report.profit_factor == 2.70
    assert report.win_rate == 0.617


def test_monte_carlo_result():
    mc = MonteCarloResult(
        simulations=10000, median_return_pct=18.4,
        p10_return_pct=6.2, p90_return_pct=34.1,
        median_max_drawdown=5.8, p95_max_drawdown=12.4,
        risk_of_ruin_pct=0.3, confidence_score=0.78,
    )
    assert mc.simulations == 10000
    assert mc.confidence_score == 0.78


def test_quality_gate_result():
    gate = QualityGateResult(
        passed=True,
        total_trades_ok=True, win_rate_ok=True,
        profit_factor_ok=True, expectancy_ok=True,
        oos_ok=True, monte_carlo_p10_ok=True,
        ruin_risk_ok=True, consecutive_losses_ok=True,
        failures=[],
    )
    assert gate.passed is True
    assert len(gate.failures) == 0

    gate_fail = QualityGateResult(
        passed=False,
        total_trades_ok=False, win_rate_ok=True,
        profit_factor_ok=True, expectancy_ok=True,
        oos_ok=True, monte_carlo_p10_ok=True,
        ruin_risk_ok=True, consecutive_losses_ok=True,
        failures=["total_trades: 12 < 30 minimum"],
    )
    assert gate_fail.passed is False


def test_market_regime_backward_compat_from_dict():
    """Old regime string values should deserialize via _REGIME_COMPAT."""
    base = {
        "nifty_level": 24000.0,
        "nifty_trend": "bullish",
        "banknifty_trend": "bearish",
        "india_vix": 14.0,
        "fii_net_cr": -500.0,
        "dii_net_cr": 300.0,
        "global_cues": "mixed",
        "sector_leaders": ["IT"],
        "sector_laggards": ["metals"],
    }
    # Old "trending" -> TRENDING_UP
    ctx = MarketContext.from_dict({**base, "regime": "trending"})
    assert ctx.regime is MarketRegime.TRENDING_UP

    # Old "ranging" -> RANGE_BOUND
    ctx2 = MarketContext.from_dict({**base, "regime": "ranging"})
    assert ctx2.regime is MarketRegime.RANGE_BOUND

    # Old "low_vol" -> LOW_VOL_SQUEEZE
    ctx3 = MarketContext.from_dict({**base, "regime": "low_vol"})
    assert ctx3.regime is MarketRegime.LOW_VOL_SQUEEZE

    # New values pass through
    ctx4 = MarketContext.from_dict({**base, "regime": "trending_up"})
    assert ctx4.regime is MarketRegime.TRENDING_UP


def test_market_regime_roundtrip():
    """New MarketRegime values serialize/deserialize cleanly."""
    base = {
        "nifty_level": 24000.0,
        "nifty_trend": "bullish",
        "banknifty_trend": "bearish",
        "india_vix": 14.0,
        "fii_net_cr": -500.0,
        "dii_net_cr": 300.0,
        "global_cues": "mixed",
        "sector_leaders": ["IT"],
        "sector_laggards": ["metals"],
        "regime": "volatile",
    }
    ctx = MarketContext.from_dict(base)
    roundtripped = MarketContext.from_dict(ctx.to_dict())
    assert roundtripped.regime is MarketRegime.VOLATILE
