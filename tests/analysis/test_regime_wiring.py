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
        quality_gates=MagicMock(),
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
