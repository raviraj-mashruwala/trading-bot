"""Tests for AnalysisPipeline orchestrator."""

import pytest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from tradingbot.analysis.pipeline import AnalysisPipeline
from tradingbot.core.models import MarketRegime

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def pipeline_deps(tmp_path):
    from tradingbot.persistence.run_store import RunStore
    from tradingbot.persistence.setup_store import SetupStore

    db = tmp_path / "test.db"
    return {
        "data_sync": MagicMock(),
        "candle_store": MagicMock(),
        "screener": MagicMock(),
        "tier2": AsyncMock(),
        "tier3": AsyncMock(),
        "backtest_engine": MagicMock(),
        "monte_carlo": MagicMock(),
        "quality_gates": MagicMock(),
        "run_store": RunStore(db),
        "setup_store": SetupStore(db),
        "event_bus": MagicMock(emit=AsyncMock()),
        "capital": 400000,
    }


def _configure_empty_pipeline(deps):
    """Configure mocks for pipeline that screens out everything at Tier 1."""
    deps["screener"].screen.return_value = []
    deps["tier2"].analyze_regime.return_value = {
        "regime": "trending_up",
        "regime_confidence": 0.82,
        "bias": "bullish",
        "sectors_in_play": [],
        "sectors_to_avoid": [],
        "risk_appetite": "moderate",
        "reasoning": "test",
    }
    deps["tier2"].analyze_sectors.return_value = {
        "sectors": [],
        "reasoning": "test",
    }
    deps["tier2"].shortlist.return_value = {
        "shortlist": [],
        "max_positions_today": 3,
        "reasoning": "none",
    }


async def test_pipeline_run_produces_analysis_run(pipeline_deps):
    """Pipeline returns AnalysisRun with correct run_id format and regime."""
    _configure_empty_pipeline(pipeline_deps)

    pipeline = AnalysisPipeline(**pipeline_deps)
    run = await pipeline.run(date(2026, 9, 27))

    assert run.run_id.startswith("run_20260927_")
    assert run.market_regime == MarketRegime.TRENDING_UP
    assert run.regime_confidence == 0.82
    assert run.tier1_passed == 0
    assert run.tier2_shortlisted == 0
    assert run.setups_proposed == 0
    assert run.setups_approved == 0
    assert run.duration_seconds > 0


async def test_pipeline_emits_lifecycle_events(pipeline_deps):
    """Pipeline emits started, tier1_complete, tier2_complete, complete events."""
    _configure_empty_pipeline(pipeline_deps)

    pipeline = AnalysisPipeline(**pipeline_deps)
    await pipeline.run(date(2026, 9, 27))

    bus = pipeline_deps["event_bus"]
    event_types = [call.args[0] for call in bus.emit.call_args_list]
    assert "analysis.started" in event_types
    assert "analysis.tier1_complete" in event_types
    assert "analysis.tier2_complete" in event_types
    assert "analysis.complete" in event_types


async def test_pipeline_persists_run_to_store(pipeline_deps):
    """Pipeline saves AnalysisRun to RunStore."""
    _configure_empty_pipeline(pipeline_deps)

    pipeline = AnalysisPipeline(**pipeline_deps)
    run = await pipeline.run(date(2026, 9, 27))

    saved = pipeline_deps["run_store"].list_for_date(date(2026, 9, 27))
    assert len(saved) == 1
    assert saved[0]["run_id"] == run.run_id


async def test_pipeline_with_shortlisted_stocks(pipeline_deps):
    """Pipeline processes shortlisted stocks through backtest and Tier 3."""
    deps = pipeline_deps
    deps["screener"].screen.return_value = []
    deps["tier2"].analyze_regime.return_value = {
        "regime": "trending_up",
        "regime_confidence": 0.82,
        "bias": "bullish",
        "sectors_in_play": ["IT"],
        "sectors_to_avoid": [],
        "risk_appetite": "moderate",
        "reasoning": "test",
    }
    deps["tier2"].analyze_sectors.return_value = {
        "sectors": [{"name": "IT", "bias": "bullish"}],
        "reasoning": "test",
    }
    deps["tier2"].shortlist.return_value = {
        "shortlist": [
            {"symbol": "INFY", "direction": "long", "reasoning": "strong"},
            {"symbol": "TCS", "direction": "long", "reasoning": "momentum"},
        ],
        "max_positions_today": 3,
        "reasoning": "good picks",
    }

    # Candle store returns empty df so backtest loop is skipped
    import pandas as pd

    deps["candle_store"].read.return_value = pd.DataFrame(
        columns=["open", "high", "low", "close", "volume"]
    )

    # Tier 3 returns setups for each stock
    deps["tier3"].deep_analyze.side_effect = [
        {
            "symbol": "INFY",
            "setups": [
                {
                    "strategy": "breakout",
                    "direction": "long",
                    "entry_price": 1500,
                    "stop_loss": 1480,
                    "target_1": 1540,
                    "target_2": 1560,
                    "confidence": 0.75,
                    "edge_description": "breakout above resistance",
                },
            ],
        },
        {
            "symbol": "TCS",
            "setups": [],
            "no_trade_reason": "weak structure",
        },
    ]

    # Adversarial validation approves INFY
    deps["tier3"].validate_portfolio.return_value = {
        "approved": [{"symbol": "INFY", "setup_index": 0, "reasoning": "valid"}],
        "rejected": [],
    }

    pipeline = AnalysisPipeline(**deps)
    run = await pipeline.run(date(2026, 9, 27))

    assert run.tier2_shortlisted == 2
    assert run.setups_proposed == 1
    assert run.setups_approved == 1

    # Check setup persisted
    setups = deps["setup_store"].get_for_symbol("INFY", date(2026, 9, 27))
    assert len(setups) == 1
    assert setups[0]["symbol"] == "INFY"
    assert setups[0]["status"] == "approved"
    assert setups[0]["entry_price"] == 1500


async def test_pipeline_counts_llm_calls(pipeline_deps):
    """Pipeline tracks LLM call count across tiers."""
    deps = pipeline_deps
    _configure_empty_pipeline(deps)

    pipeline = AnalysisPipeline(**deps)
    run = await pipeline.run(date(2026, 9, 27))

    # 3 LLM calls: regime + sectors + shortlist (no deep/adversarial since no shortlisted)
    assert run.llm_calls == 3


async def test_pipeline_no_adversarial_when_no_setups(pipeline_deps):
    """Pipeline skips adversarial validation when no setups exist."""
    deps = pipeline_deps
    deps["screener"].screen.return_value = []
    deps["tier2"].analyze_regime.return_value = {
        "regime": "range_bound",
        "regime_confidence": 0.60,
        "bias": "neutral",
        "sectors_in_play": [],
        "sectors_to_avoid": [],
        "risk_appetite": "low",
        "reasoning": "choppy",
    }
    deps["tier2"].analyze_sectors.return_value = {"sectors": [], "reasoning": "flat"}
    deps["tier2"].shortlist.return_value = {
        "shortlist": [{"symbol": "RELIANCE", "direction": "long", "reasoning": "ok"}],
        "max_positions_today": 1,
        "reasoning": "one pick",
    }

    import pandas as pd

    deps["candle_store"].read.return_value = pd.DataFrame(
        columns=["open", "high", "low", "close", "volume"]
    )
    deps["tier3"].deep_analyze.return_value = {
        "symbol": "RELIANCE",
        "setups": [],
        "no_trade_reason": "no confluence",
    }

    pipeline = AnalysisPipeline(**deps)
    run = await pipeline.run(date(2026, 9, 27))

    # 4 calls: regime + sectors + shortlist + 1 deep_analyze, no adversarial
    assert run.llm_calls == 4
    deps["tier3"].validate_portfolio.assert_not_called()
    assert run.setups_proposed == 0
    assert run.setups_approved == 0


async def test_pipeline_multiple_runs_different_ids(pipeline_deps):
    """Each pipeline run gets a unique run_id."""
    _configure_empty_pipeline(pipeline_deps)

    pipeline = AnalysisPipeline(**pipeline_deps)
    run1 = await pipeline.run(date(2026, 9, 27))
    run2 = await pipeline.run(date(2026, 9, 27))

    assert run1.run_id != run2.run_id


async def test_pipeline_range_bound_regime(pipeline_deps):
    """Pipeline correctly maps range_bound regime string to enum."""
    deps = pipeline_deps
    deps["screener"].screen.return_value = []
    deps["tier2"].analyze_regime.return_value = {
        "regime": "range_bound",
        "regime_confidence": 0.55,
        "bias": "neutral",
        "sectors_in_play": [],
        "sectors_to_avoid": [],
        "risk_appetite": "low",
        "reasoning": "sideways",
    }
    deps["tier2"].analyze_sectors.return_value = {"sectors": [], "reasoning": "test"}
    deps["tier2"].shortlist.return_value = {
        "shortlist": [],
        "max_positions_today": 0,
        "reasoning": "no trades",
    }

    pipeline = AnalysisPipeline(**deps)
    run = await pipeline.run(date(2026, 9, 27))

    assert run.market_regime == MarketRegime.RANGE_BOUND


# ── WalkForwardEngine usage test ──────────────────────────────────────────────

import numpy as np
import pandas as pd
from tradingbot.core.models import StrategyName

def _make_candle_df(n=300):
    closes = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "open": closes - 0.3, "high": closes + 1,
        "low": closes - 1, "close": closes,
        "volume": [1_000_000] * n,
    })


def test_run_backtests_uses_injected_engine(pipeline_deps):
    """_run_backtests must call self._backtest.run(), not import Backtester internally."""
    from tradingbot.backtest.walk_forward import WalkForwardEngine

    wf_engine = MagicMock(spec=WalkForwardEngine)
    mock_report = MagicMock()
    mock_report.total_trades = 10
    mock_report.winners = 6
    mock_report.losers = 4
    mock_report.avg_winner = 2.0
    mock_report.avg_loser = -1.0
    wf_engine.run.return_value = mock_report

    pipeline_deps["backtest_engine"] = wf_engine
    pipeline_deps["candle_store"].read.return_value = _make_candle_df(300)

    p = AnalysisPipeline(**pipeline_deps)
    results = []
    p._run_backtests("TCS", results, regime={"regime": "trending_up"})

    assert wf_engine.run.called


def test_run_backtests_reads_candles_once_not_per_strategy(pipeline_deps):
    """candle_store.read must be called exactly once per symbol, not once per strategy."""
    from tradingbot.backtest.walk_forward import WalkForwardEngine

    wf = MagicMock(spec=WalkForwardEngine)
    mock_report = MagicMock()
    mock_report.total_trades = 0  # gate rejects — not the point
    wf.run.return_value = mock_report

    pipeline_deps["backtest_engine"] = wf
    pipeline_deps["candle_store"].read.return_value = _make_candle_df(300)

    p = AnalysisPipeline(**pipeline_deps)
    results = []
    p._run_backtests("TCS", results, regime={"regime": "trending_up"})

    # trending_up has 5 eligible strategies — read must still be called only once
    read_calls = [
        c for c in pipeline_deps["candle_store"].read.call_args_list
        if c.args[0] == "TCS" and c.args[1] == "15minute"
    ]
    assert len(read_calls) == 1, (
        f"Expected 1 candle read for TCS/15minute, got {len(read_calls)}"
    )


# ── Lookback days tests ───────────────────────────────────────────────────────

def test_pipeline_accepts_lookback_days_param(pipeline_deps):
    """AnalysisPipeline must accept lookback_days kwarg without raising."""
    p = AnalysisPipeline(**pipeline_deps, lookback_days=90)
    assert p._lookback_days == 90


def test_run_backtests_uses_lookback_days_for_from_dt(pipeline_deps):
    """from_dt passed to candle_store.read must be approximately now - lookback_days."""
    from datetime import timedelta

    pipeline_deps["candle_store"].read.return_value = pd.DataFrame()
    p = AnalysisPipeline(**pipeline_deps, lookback_days=60)
    p._run_backtests("TCS", [], regime={"regime": "trending_up"})

    call = next(
        c for c in pipeline_deps["candle_store"].read.call_args_list
        if c.args[0] == "TCS" and c.args[1] == "15minute"
    )
    from_dt = call.args[2]
    expected_approx = datetime.now(tz=IST) - timedelta(days=60)
    delta = abs((from_dt - expected_approx).total_seconds())
    assert delta < 5, f"from_dt off by {delta:.1f}s — expected ~60 days ago"


# ── Indicator fetch tests ─────────────────────────────────────────────────────

def test_fetch_indicators_returns_dict_with_rsi(pipeline_deps):
    pipeline_deps["candle_store"].read.return_value = _make_candle_df(300)
    p = AnalysisPipeline(**pipeline_deps)
    indicators, price_action = p._fetch_indicators_for_symbol("TCS")
    assert "rsi_14" in indicators
    assert "vwap" in indicators
    assert "TCS" in price_action


def test_fetch_indicators_returns_empty_on_empty_df(pipeline_deps):
    """Empty candle df must not propagate — returns ({}, fallback string)."""
    pipeline_deps["candle_store"].read.return_value = pd.DataFrame()
    p = AnalysisPipeline(**pipeline_deps)
    indicators, price_action = p._fetch_indicators_for_symbol("TCS")
    assert indicators == {}
    assert "TCS" in price_action
    assert "insufficient" in price_action.lower() or "failed" in price_action.lower(), (
        f"Fallback message must say why it failed, got: {price_action!r}"
    )


def test_fetch_indicators_price_action_contains_key_levels(pipeline_deps):
    pipeline_deps["candle_store"].read.return_value = _make_candle_df(300)
    p = AnalysisPipeline(**pipeline_deps)
    _, price_action = p._fetch_indicators_for_symbol("TCS")
    assert "VWAP" in price_action or "vwap" in price_action.lower()
    assert "RSI" in price_action or "rsi" in price_action.lower()


# ── Correlation filter tests ──────────────────────────────────────────────────

def _make_close_df(closes):
    n = len(closes)
    return pd.DataFrame({
        "open": closes - 0.3, "high": closes + 1,
        "low": closes - 1, "close": closes, "volume": [1_000_000] * n,
    })


def _setup_entry(symbol, confidence):
    return {"symbol": symbol, "setups": [{"confidence": confidence}]}


def test_correlated_pair_drops_lower_confidence(pipeline_deps):
    rng = np.random.default_rng(42)
    base = rng.standard_normal(25)
    c1 = 100 + np.cumsum(base)
    c2 = 100 + np.cumsum(base + rng.standard_normal(25) * 0.01)  # ρ ≈ 1.0

    pipeline_deps["candle_store"].read.side_effect = (
        lambda sym, *a, **kw: _make_close_df(c1) if sym == "TCS" else _make_close_df(c2)
    )
    p = AnalysisPipeline(**pipeline_deps)
    result = p._drop_correlated_setups([
        _setup_entry("TCS", 0.85),
        _setup_entry("INFY", 0.65),
    ])
    syms = [s["symbol"] for s in result]
    assert "TCS" in syms and "INFY" not in syms


def test_uncorrelated_pair_both_kept(pipeline_deps):
    c_a = 100 + np.cumsum(np.random.default_rng(0).standard_normal(25))
    c_b = 200 + np.cumsum(np.random.default_rng(99).standard_normal(25))
    pipeline_deps["candle_store"].read.side_effect = (
        lambda sym, *a, **kw: _make_close_df(c_a) if sym == "HDFC" else _make_close_df(c_b)
    )
    p = AnalysisPipeline(**pipeline_deps)
    result = p._drop_correlated_setups([
        _setup_entry("HDFC", 0.8),
        _setup_entry("ONGC", 0.75),
    ])
    assert len(result) == 2


def test_single_symbol_unchanged(pipeline_deps):
    closes = 100 + np.cumsum(np.random.default_rng(7).standard_normal(25))
    pipeline_deps["candle_store"].read.return_value = _make_close_df(closes)
    p = AnalysisPipeline(**pipeline_deps)
    result = p._drop_correlated_setups([_setup_entry("TCS", 0.8)])
    assert len(result) == 1 and result[0]["symbol"] == "TCS"


def test_hub_and_spoke_drops_hub_not_spokes():
    """A(conf=0.90) is hub: ρ(A,B)>0.7 and ρ(A,C)>0.7 but ρ(B,C)≤0.7.
    C(0.92) is highest confidence. A must be dropped (correlated with C).
    B must survive — it has no qualifying correlation with C.
    Greedy pair-iteration bug: B dropped via A→B pair before A itself is dropped.
    Correct fix: confidence-sorted greedy (keep highest-conf first).
    """
    rng = np.random.default_rng(7)
    n = 25
    # Construct returns via 3-factor model: ρ(A,B)=ρ(A,C)=0.8, ρ(B,C)=0.64<0.7
    a_ret = rng.standard_normal(n)
    e1 = rng.standard_normal(n)
    e2 = rng.standard_normal(n)
    b_ret = 0.8 * a_ret + 0.6 * e1   # ρ(A,B) ≈ 0.8
    c_ret = 0.8 * a_ret + 0.6 * e2   # ρ(A,C) ≈ 0.8; ρ(B,C) ≈ 0.64

    # Verify the construction before asserting pipeline behavior
    rho_ab = float(np.corrcoef(a_ret, b_ret)[0, 1])
    rho_ac = float(np.corrcoef(a_ret, c_ret)[0, 1])
    rho_bc = float(np.corrcoef(b_ret, c_ret)[0, 1])
    assert rho_ab > 0.7 and rho_ac > 0.7 and rho_bc <= 0.7, (
        f"Test construction invalid: ρ(A,B)={rho_ab:.2f} ρ(A,C)={rho_ac:.2f} ρ(B,C)={rho_bc:.2f}"
    )

    # Build price series as cumsum of returns
    make = lambda ret: _make_close_df(100 + np.cumsum(ret))
    dfs = {"A": make(a_ret), "B": make(b_ret), "C": make(c_ret)}

    candle_store = MagicMock()
    candle_store.read.side_effect = lambda sym, *a, **kw: dfs[sym]

    from tradingbot.persistence.run_store import RunStore
    from tradingbot.persistence.setup_store import SetupStore
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as tmp:
        db = pathlib.Path(tmp) / "t.db"
        deps = {
            "data_sync": MagicMock(), "candle_store": candle_store,
            "screener": MagicMock(), "tier2": MagicMock(), "tier3": MagicMock(),
            "backtest_engine": MagicMock(), "monte_carlo": MagicMock(),
            "quality_gates": MagicMock(), "run_store": RunStore(db),
            "setup_store": SetupStore(db), "event_bus": MagicMock(), "capital": 100_000,
        }
        p = AnalysisPipeline(**deps)
        result = p._drop_correlated_setups([
            _setup_entry("A", 0.90),   # hub — correlated with both, mid confidence
            _setup_entry("B", 0.85),   # spoke — correlated with A, not with C
            _setup_entry("C", 0.92),   # spoke — correlated with A, highest confidence
        ])
        syms = {s["symbol"] for s in result}
        assert "C" in syms, "Highest-confidence symbol must always survive"
        assert "A" not in syms, "A must be dropped (correlated with C, lower confidence)"
        assert "B" in syms, "B must survive — not correlated with C; only correlated with dropped A"
