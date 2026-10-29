"""AnalysisPipeline can stop at missing LLM answers or shortlist data and be rerun."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tradingbot.analysis.pipeline import AnalysisPipeline, DataNeeded
from tradingbot.analysis.tier2_analyzer import Tier2Analyzer
from tradingbot.analysis.tier3_analyzer import Tier3Analyzer
from tradingbot.core.llm.file_provider import AnswersNeeded, FileAnswerProvider

TRADE_DATE = date(2026, 9, 27)

REGIME = {
    "regime": "trending_up", "regime_confidence": 0.8, "bias": "bullish",
    "sectors_in_play": ["IT"], "sectors_to_avoid": [], "risk_appetite": "moderate",
    "reasoning": "test",
}
SECTORS = {"sectors": [], "reasoning": "test"}


def shortlist_of(*symbols):
    return {
        "shortlist": [{"symbol": s, "direction": "long", "reasoning": "r"} for s in symbols],
        "max_positions_today": 3,
        "reasoning": "test",
    }


@pytest.fixture
def deps(tmp_path):
    from tradingbot.persistence.run_store import RunStore
    from tradingbot.persistence.setup_store import SetupStore

    db = tmp_path / "test.db"
    screener = MagicMock()
    screener.screen.return_value = []
    return {
        "data_sync": MagicMock(),
        "candle_store": MagicMock(),
        "screener": screener,
        "tier2": AsyncMock(),
        "tier3": AsyncMock(),
        "backtest_engine": MagicMock(),
        "monte_carlo": MagicMock(),
        "run_store": RunStore(db),
        "setup_store": SetupStore(db),
        "event_bus": MagicMock(emit=AsyncMock()),
        "capital": 400000,
    }


def make_pipeline(deps, **extra):
    pipeline = AnalysisPipeline(**deps, **extra)
    pipeline._fetch_indicators_for_symbol = lambda sym: ({"rsi_14": 55}, f"{sym} summary")
    pipeline._fetch_delivery_data = lambda trade_date: {}  # no network in tests
    return pipeline


def assert_nothing_persisted(deps):
    assert deps["run_store"].list_for_date(TRADE_DATE) == []
    assert deps["setup_store"].get_for_symbol("INFY", TRADE_DATE) == []


async def test_missing_regime_answer_exits_before_any_persistence(deps):
    deps["tier2"].analyze_regime.side_effect = AnswersNeeded([Path("regime.json")])

    with pytest.raises(AnswersNeeded):
        await make_pipeline(deps).run(TRADE_DATE)

    assert_nothing_persisted(deps)


async def test_all_deep_analysis_requests_written_in_one_run(deps):
    deps["tier2"].analyze_regime.return_value = dict(REGIME)
    deps["tier2"].analyze_sectors.return_value = dict(SECTORS)
    deps["tier2"].shortlist.return_value = shortlist_of("INFY", "TCS", "RELIANCE")

    async def deep_analyze(symbol, **kwargs):
        raise AnswersNeeded([Path(f"{symbol}.json")])

    deps["tier3"].deep_analyze.side_effect = deep_analyze

    with pytest.raises(AnswersNeeded) as raised:
        await make_pipeline(deps).run(TRADE_DATE)

    assert deps["tier3"].deep_analyze.call_count == 3
    assert raised.value.requests == [Path("INFY.json"), Path("TCS.json"), Path("RELIANCE.json")]
    deps["tier3"].validate_portfolio.assert_not_called()
    assert_nothing_persisted(deps)


async def test_answered_symbols_do_not_hide_pending_ones(deps):
    deps["tier2"].analyze_regime.return_value = dict(REGIME)
    deps["tier2"].analyze_sectors.return_value = dict(SECTORS)
    deps["tier2"].shortlist.return_value = shortlist_of("INFY", "TCS")

    async def deep_analyze(symbol, **kwargs):
        if symbol == "TCS":
            raise AnswersNeeded([Path("TCS.json")])
        return {"symbol": symbol, "setups": [], "no_trade_reason": "flat"}

    deps["tier3"].deep_analyze.side_effect = deep_analyze

    with pytest.raises(AnswersNeeded) as raised:
        await make_pipeline(deps).run(TRADE_DATE)

    assert raised.value.requests == [Path("TCS.json")]


def duckdb_with(last_dates):
    store = MagicMock()
    store.last_date.side_effect = lambda symbol, interval: last_dates.get(symbol)
    return store


async def test_require_prefetched_raises_data_needed_for_new_symbol(deps):
    deps["tier2"].analyze_regime.return_value = dict(REGIME)
    deps["tier2"].analyze_sectors.return_value = dict(SECTORS)
    deps["tier2"].shortlist.return_value = shortlist_of("INFY", "TCS")
    pipeline = make_pipeline(
        deps, duckdb_store=duckdb_with({"TCS": date(2026, 9, 26)}), require_prefetched=True,
    )
    pipeline.fetch_shortlist = AsyncMock()

    with pytest.raises(DataNeeded) as raised:
        await pipeline.run(TRADE_DATE)

    assert raised.value.symbols == ["INFY"]
    pipeline.fetch_shortlist.assert_not_awaited()
    deps["tier3"].deep_analyze.assert_not_called()


async def test_require_prefetched_continues_when_data_is_present(deps):
    deps["tier2"].analyze_regime.return_value = dict(REGIME)
    deps["tier2"].analyze_sectors.return_value = dict(SECTORS)
    deps["tier2"].shortlist.return_value = shortlist_of("INFY")
    deps["tier3"].deep_analyze.return_value = {"symbol": "INFY", "setups": [], "no_trade_reason": "x"}
    pipeline = make_pipeline(
        deps, duckdb_store=duckdb_with({"INFY": date(2026, 9, 26)}), require_prefetched=True,
    )

    run = await pipeline.run(TRADE_DATE)

    assert run.tier2_shortlisted == 1
    deps["tier3"].deep_analyze.assert_awaited_once()


async def test_require_prefetched_false_still_fetches_inline(deps):
    deps["tier2"].analyze_regime.return_value = dict(REGIME)
    deps["tier2"].analyze_sectors.return_value = dict(SECTORS)
    deps["tier2"].shortlist.return_value = shortlist_of("INFY")
    deps["tier3"].deep_analyze.return_value = {"symbol": "INFY", "setups": [], "no_trade_reason": "x"}
    pipeline = make_pipeline(deps, duckdb_store=duckdb_with({}))
    pipeline.fetch_shortlist = AsyncMock()

    await pipeline.run(TRADE_DATE)

    pipeline.fetch_shortlist.assert_awaited_once()
    assert pipeline.fetch_shortlist.await_args.args[0] == ["INFY"]


# ---------------------------------------------------------------------------
# End to end: real tier analyzers, file provider, answers written between runs.
# ---------------------------------------------------------------------------

DEEP = {
    "symbol": "INFY",
    "setups": [{
        "strategy": "breakout", "direction": "long", "entry_trigger": "t",
        "entry_price": 1500.0, "stop_loss": 1480.0, "target_1": 1540.0, "target_2": 1560.0,
        "position_size_hint": "1x", "entry_window": "09:30-10:30", "exit_deadline": "15:10",
        "confidence": 0.75, "edge_description": "e", "invalidation": "i", "bear_case": "b",
        "confluence_count": 3, "timeframe_alignment": ["5m"],
    }],
    "no_trade_reason": None,
}


def answer_for(request: dict) -> dict:
    tool = request["tool_name"]
    if tool == "submit_regime_analysis":
        return {
            **REGIME,
            "key_levels": {
                "nifty_support": 1.0, "nifty_resistance": 2.0,
                "banknifty_support": 1.0, "banknifty_resistance": 2.0,
            },
        }
    if tool == "submit_sector_analysis":
        return SECTORS
    if tool == "submit_shortlist":
        return {
            "shortlist": [{
                "symbol": "INFY", "direction": "long", "conviction": "high", "reasoning": "r",
                "primary_strategy": "breakout",
                "key_levels": {"support": 1.0, "resistance": 2.0, "vwap": 1.5},
                "risk_flag": "none", "counter_argument": "c",
            }],
            "max_positions_today": 3,
            "reasoning": "test",
        }
    if tool == "submit_deep_analysis":
        assert request["step"] == "deep:INFY"
        return DEEP
    if tool == "submit_validation":
        return {
            "approved": [{"symbol": "INFY", "setup_index": 0, "approval": "strong", "adjustment": None}],
            "rejected": [],
            "portfolio_risk_assessment": {
                "total_setups": 1, "approved_count": 1, "max_correlated_exposure": "low",
                "regime_alignment": "ok", "worst_case_loss": "1%", "recommendation": "go",
            },
        }
    raise AssertionError(f"unexpected tool {tool}")


def answer_pending(queue_dir: Path) -> int:
    answers = queue_dir / "answers"
    answers.mkdir(exist_ok=True)
    written = 0
    for request_path in sorted((queue_dir / "requests").glob("*.json")):
        if (answers / request_path.name).exists():
            continue
        request = json.loads(request_path.read_text())
        (answers / request_path.name).write_text(json.dumps(answer_for(request)))
        written += 1
    return written


async def test_reruns_converge_to_one_run_even_when_live_inputs_drift(deps, tmp_path):
    queue_dir = tmp_path / "queue"
    provider = FileAnswerProvider(queue_dir)
    deps["tier2"] = Tier2Analyzer(provider)
    deps["tier3"] = Tier3Analyzer(provider)

    drift = iter(range(1000))
    context = MagicMock()
    context.fetch.side_effect = lambda: MagicMock(
        nifty_level=24000 + next(drift), india_vix=15.0 + next(drift) / 100,
        fii_net_cr=100.0, dii_net_cr=100.0, sector_leaders=[], sector_laggards=[],
        regime=MagicMock(value="range_bound"),
    )
    deps["context_fetcher"] = context

    pipeline = make_pipeline(deps)
    pipeline._fetch_indicators_for_symbol = lambda sym: ({"rsi_14": 50 + next(drift)}, f"{sym} {next(drift)}")

    rounds = 0
    while True:
        try:
            run = await pipeline.run(TRADE_DATE)
            break
        except AnswersNeeded:
            rounds += 1
            assert rounds <= 5, "reruns are not converging"
            assert answer_pending(queue_dir) >= 1

    assert rounds == 5  # regime, sectors, shortlist, deep analysis, adversarial
    assert run.setups_approved == 1
    assert len(deps["run_store"].list_for_date(TRADE_DATE)) == 1
    assert len(deps["setup_store"].get_for_symbol("INFY", TRADE_DATE)) == 1
