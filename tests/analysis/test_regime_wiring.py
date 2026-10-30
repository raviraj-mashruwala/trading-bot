"""Tests for pipeline's market context wiring."""

import pytest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo
from tradingbot.analysis.pipeline import AnalysisPipeline
from tradingbot.core.models import MarketContext, MarketRegime
from tradingbot.persistence.run_store import RunStore
from tradingbot.persistence.setup_store import SetupStore

IST = ZoneInfo("Asia/Kolkata")


def _mock_context():
    return MarketContext(
        nifty_level=19500.0, nifty_trend="bullish", banknifty_trend="bullish",
        india_vix=13.5, fii_net_cr=-500.0, dii_net_cr=800.0,
        global_cues="US futures flat", sector_leaders=["banking", "IT"],
        sector_laggards=["pharma"], regime=MarketRegime.TRENDING_UP,
    )


def _make_pipeline(context_fetcher=None, tmp_path=None):
    tier2 = AsyncMock()
    tier2.analyze_regime.return_value = {
        "regime": "trending_up", "regime_confidence": 0.82,
        "bias": "bullish", "sectors_in_play": ["banking"],
        "sectors_to_avoid": ["pharma"], "risk_appetite": "moderate",
        "reasoning": "test",
    }
    tier2.analyze_sectors.return_value = {"sectors": [], "reasoning": "test"}
    tier2.shortlist.return_value = {"shortlist": [], "max_positions_today": 3, "reasoning": "none"}

    db = (tmp_path or Path("/tmp")) / "test_regime.db"
    pipeline = AnalysisPipeline(
        data_sync=MagicMock(),
        candle_store=MagicMock(),
        screener=MagicMock(screen=MagicMock(return_value=[])),
        tier2=tier2,
        tier3=AsyncMock(),
        backtest_engine=MagicMock(),
        monte_carlo=MagicMock(),
        run_store=RunStore(db),
        setup_store=SetupStore(db),
        event_bus=MagicMock(emit=AsyncMock()),
        capital=400000,
        instrument_cache=MagicMock(get_all=MagicMock(return_value=[])),
        context_fetcher=context_fetcher,
    )
    return pipeline, tier2


async def test_pipeline_passes_real_market_data(tmp_path):
    ctx = MagicMock()
    ctx.fetch.return_value = _mock_context()
    pipeline, tier2 = _make_pipeline(context_fetcher=ctx, tmp_path=tmp_path)

    await pipeline.run(date(2026, 9, 28))

    tier2.analyze_regime.assert_called_once()
    kwargs = tier2.analyze_regime.call_args.kwargs
    assert kwargs["nifty"] == 19500.0
    assert kwargs["vix"] == 13.5
    assert kwargs["fii_5d_net"] == -500.0


async def test_pipeline_uses_defaults_on_fetch_failure(tmp_path):
    ctx = MagicMock()
    ctx.fetch.side_effect = Exception("Network error")
    pipeline, tier2 = _make_pipeline(context_fetcher=ctx, tmp_path=tmp_path)

    await pipeline.run(date(2026, 9, 28))

    tier2.analyze_regime.assert_called_once()
    kwargs = tier2.analyze_regime.call_args.kwargs
    assert kwargs["vix"] == 15.0  # safe default


async def test_pipeline_uses_defaults_when_no_fetcher(tmp_path):
    pipeline, tier2 = _make_pipeline(context_fetcher=None, tmp_path=tmp_path)

    await pipeline.run(date(2026, 9, 28))

    tier2.analyze_regime.assert_called_once()
    kwargs = tier2.analyze_regime.call_args.kwargs
    assert kwargs["vix"] == 15.0


async def test_regime_call_gets_the_banknifty_level(tmp_path):
    from datetime import date
    from unittest.mock import AsyncMock, MagicMock

    from tradingbot.analysis.pipeline import AnalysisPipeline
    from tradingbot.core.models import MarketRegime
    from tradingbot.persistence.run_store import RunStore
    from tradingbot.persistence.setup_store import SetupStore

    db = tmp_path / "t.db"
    context = MagicMock()
    context.fetch.return_value = MagicMock(
        nifty_level=24500.0, banknifty_level=52000.0, india_vix=14.0, fii_net_cr=1.0,
        dii_net_cr=1.0, sector_leaders=[], sector_laggards=[], regime=MarketRegime.RANGE_BOUND,
    )
    tier2 = AsyncMock()
    tier2.analyze_regime.return_value = {
        "regime": "range_bound", "regime_confidence": 0.5, "bias": "neutral",
        "sectors_in_play": [], "risk_appetite": "moderate", "reasoning": "x",
    }
    tier2.analyze_sectors.return_value = {"sectors": [], "reasoning": "x"}
    tier2.shortlist.return_value = {"shortlist": [], "max_positions_today": 1, "reasoning": "x"}
    screener = MagicMock()
    screener.screen.return_value = []
    pipeline = AnalysisPipeline(
        data_sync=MagicMock(), candle_store=MagicMock(), screener=screener, tier2=tier2,
        tier3=AsyncMock(), backtest_engine=MagicMock(), monte_carlo=MagicMock(),
        run_store=RunStore(db), setup_store=SetupStore(db),
        event_bus=MagicMock(emit=AsyncMock()), capital=400000, context_fetcher=context,
    )
    pipeline._fetch_delivery_data = lambda trade_date: {}

    await pipeline.run(date(2026, 9, 27))

    kwargs = tier2.analyze_regime.call_args.kwargs
    assert kwargs["banknifty"] == 52000.0
    assert kwargs["nifty"] == 24500.0


async def test_regime_call_gets_market_breadth_from_tier1_signals(tmp_path):
    from datetime import date
    from unittest.mock import AsyncMock, MagicMock

    from tradingbot.analysis.pipeline import AnalysisPipeline
    from tradingbot.core.models import MarketRegime
    from tradingbot.persistence.run_store import RunStore
    from tradingbot.persistence.setup_store import SetupStore

    db = tmp_path / "t.db"
    context = MagicMock()
    context.fetch.return_value = MagicMock(
        nifty_level=24500.0, banknifty_level=52000.0, india_vix=14.0, fii_net_cr=1.0,
        dii_net_cr=1.0, sector_leaders=[], sector_laggards=[], regime=MarketRegime.RANGE_BOUND,
    )
    tier2 = AsyncMock()
    tier2.analyze_regime.return_value = {
        "regime": "range_bound", "regime_confidence": 0.5, "bias": "neutral",
        "sectors_in_play": [], "risk_appetite": "moderate", "reasoning": "x",
    }
    tier2.analyze_sectors.return_value = {"sectors": [], "reasoning": "x"}
    tier2.shortlist.return_value = {"shortlist": [], "max_positions_today": 1, "reasoning": "x"}
    screener = MagicMock()
    screener.screen.return_value = []
    pipeline = AnalysisPipeline(
        data_sync=MagicMock(), candle_store=MagicMock(), screener=screener, tier2=tier2,
        tier3=AsyncMock(), backtest_engine=MagicMock(), monte_carlo=MagicMock(),
        run_store=RunStore(db), setup_store=SetupStore(db),
        event_bus=MagicMock(emit=AsyncMock()), capital=400000, context_fetcher=context,
    )
    pipeline._fetch_delivery_data = lambda trade_date: {}
    pipeline._fetch_universe = lambda: [{"symbol": "A"}]
    pipeline._build_stock_metrics_from_instruments = lambda instruments, nifty, delivery: [
        {"symbol": "A", "signals": {"change_1d_pct": 1.0}},
        {"symbol": "B", "signals": {"change_1d_pct": 2.0}},
        {"symbol": "C", "signals": {"change_1d_pct": 0.5}},
        {"symbol": "D", "signals": {"change_1d_pct": -3.0}},
        {"symbol": "E", "signals": {"change_1d_pct": 0.0}},  # unchanged counts as neither
    ]

    await pipeline.run(date(2026, 9, 27))

    assert tier2.analyze_regime.call_args.kwargs["advance_decline"] == pytest.approx(3.0)
