"""One regime for the whole run: the one Tier 2 (Jev, else the LLM) gives, used by Tier 1 too.

The screener used to adapt its weights to a rule-based regime (VIX and index averages) while
the shortlist, deep analysis and the saved plan used Jev's, so one run held two regimes.
"""

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tradingbot.analysis.pipeline import AnalysisPipeline
from tradingbot.core.llm.file_provider import AnswersNeeded
from tradingbot.core.models import MarketRegime

TRADE_DATE = date(2026, 9, 27)


def regime(name, confidence=0.29):
    r = {
        "regime": name, "bias": "neutral", "sectors_in_play": [], "sectors_to_avoid": [],
        "risk_appetite": "moderate", "reasoning": name,
    }
    if confidence is not None:
        r["regime_confidence"] = confidence
    return r


def make(tmp_path, jev_regime=None, llm_regime=None, order=None):
    from tradingbot.persistence.run_store import RunStore
    from tradingbot.persistence.setup_store import SetupStore

    order = order if order is not None else []
    db = tmp_path / "t.db"

    context = MagicMock()
    context.fetch.return_value = MagicMock(
        nifty_level=24500.0, banknifty_level=52000.0, india_vix=14.0, fii_net_cr=1.0,
        dii_net_cr=1.0, sector_leaders=[], sector_laggards=[],
        regime=MarketRegime.RANGE_BOUND,  # the rule-based label that used to drive Tier 1
    )

    tier2 = AsyncMock()

    async def llm_analyze_regime(**kwargs):
        order.append("llm_regime")
        return llm_regime
    tier2.analyze_regime.side_effect = llm_analyze_regime
    tier2.analyze_sectors.return_value = {"sectors": [], "reasoning": "x"}
    tier2.shortlist.side_effect = AnswersNeeded([Path("shortlist.json")])

    bus = MagicMock(emit=AsyncMock())
    pipeline = AnalysisPipeline(
        data_sync=MagicMock(), candle_store=MagicMock(), screener=MagicMock(), tier2=tier2,
        tier3=AsyncMock(), backtest_engine=MagicMock(), monte_carlo=MagicMock(),
        run_store=RunStore(db), setup_store=SetupStore(db), event_bus=bus, capital=400000,
        context_fetcher=context,
    )
    pipeline._fetch_delivery_data = lambda trade_date: {}

    screener = MagicMock()

    def screen(*args, **kwargs):
        order.append("screen")
        return []
    screener.screen.side_effect = screen
    pipeline._intelligent_screener = screener

    if jev_regime is not None:
        jev = MagicMock()

        async def jev_analyze_regime(**kwargs):
            order.append("jev_regime")
            return jev_regime
        jev.analyze_regime = jev_analyze_regime
        jev.analyze_sectors = AsyncMock(return_value={"sectors": [], "reasoning": "x"})
        pipeline._jev_tier2 = jev
    else:
        pipeline._jev_tier2 = None
    return pipeline, screener, bus


async def run(pipeline):
    with pytest.raises(AnswersNeeded):
        await pipeline.run(TRADE_DATE)


async def test_tier1_uses_the_tier2_regime_and_its_confidence(tmp_path):
    pipeline, screener, _ = make(tmp_path, jev_regime=regime("trending_down", 0.29))

    await run(pipeline)

    kwargs = screener.screen.call_args.kwargs
    assert kwargs["regime"] == "trending_down"   # not the rule-based range_bound
    assert kwargs["regime_confidence"] == pytest.approx(0.29)  # not the old hardcoded 0.7


async def test_the_regime_is_decided_before_tier1_screens(tmp_path):
    order = []
    pipeline, _, _ = make(tmp_path, jev_regime=regime("trending_down"), order=order)

    await run(pipeline)

    assert order == ["jev_regime", "screen"]


async def test_the_llm_regime_is_used_when_jev_is_unavailable(tmp_path):
    pipeline, screener, _ = make(tmp_path, jev_regime=None, llm_regime=regime("volatile", 0.8))

    await run(pipeline)

    kwargs = screener.screen.call_args.kwargs
    assert kwargs["regime"] == "volatile"
    assert kwargs["regime_confidence"] == pytest.approx(0.8)


async def test_a_regime_without_a_confidence_defaults_to_half(tmp_path):
    pipeline, screener, _ = make(tmp_path, jev_regime=regime("range_bound", confidence=None))

    await run(pipeline)

    assert screener.screen.call_args.kwargs["regime_confidence"] == pytest.approx(0.5)


async def test_the_context_event_reports_the_unified_regime(tmp_path):
    pipeline, _, bus = make(tmp_path, jev_regime=regime("trending_down", 0.29))

    await run(pipeline)

    payloads = [call.args[1] for call in bus.emit_sync.call_args_list if call.args[0] == "scan.context"]
    assert payloads and all(p["regime"] == "trending_down" for p in payloads)


async def test_an_unanswered_regime_stops_before_any_screening(tmp_path):
    order = []
    pipeline, screener, _ = make(tmp_path, jev_regime=None, llm_regime=None, order=order)
    pipeline._tier2.analyze_regime.side_effect = AnswersNeeded([Path("regime.json")])

    await run(pipeline)

    screener.screen.assert_not_called()
