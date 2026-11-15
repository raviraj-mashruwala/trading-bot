"""A staged analysis is rerun several times; Jev's regime and sectors must not drift between runs."""

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tradingbot.analysis.pipeline import AnalysisPipeline
from tradingbot.core.llm.file_provider import AnswersNeeded

TRADE_DATE = date(2026, 9, 27)


def regime(name, confidence):
    return {
        "regime": name, "regime_confidence": confidence, "bias": "neutral",
        "sectors_in_play": [], "sectors_to_avoid": [], "risk_appetite": "moderate", "reasoning": name,
    }


def sectors(bias):
    return {"sectors": [{"name": "it", "intraday_bias": bias, "theme": "t", "catalyst": "c"}], "reasoning": bias}


def make(tmp_path, jev, cache_dir=None):
    from tradingbot.persistence.run_store import RunStore
    from tradingbot.persistence.setup_store import SetupStore

    db = tmp_path / "t.db"
    screener = MagicMock()
    screener.screen.return_value = []
    tier2 = AsyncMock()
    tier2.shortlist.side_effect = AnswersNeeded([Path("shortlist.json")])  # stop right after tier 2
    pipeline = AnalysisPipeline(
        data_sync=MagicMock(), candle_store=MagicMock(), screener=screener, tier2=tier2,
        tier3=AsyncMock(), backtest_engine=MagicMock(), monte_carlo=MagicMock(),
        run_store=RunStore(db), setup_store=SetupStore(db),
        event_bus=MagicMock(emit=AsyncMock()), capital=400000, cache_dir=cache_dir,
    )
    pipeline._fetch_delivery_data = lambda trade_date: {}
    pipeline._jev_tier2 = jev
    return pipeline, tier2


def drifting_jev():
    jev = MagicMock()
    jev.analyze_regime = AsyncMock(side_effect=[regime("trending_up", 0.22), regime("range_bound", 0.60)])
    jev.analyze_sectors = AsyncMock(side_effect=[sectors("bullish"), sectors("bearish")])
    return jev


async def run_twice(pipeline):
    for _ in range(2):
        with pytest.raises(AnswersNeeded):
            await pipeline.run(TRADE_DATE)


async def test_reruns_reuse_the_first_regime_and_sectors(tmp_path):
    jev = drifting_jev()
    pipeline, tier2 = make(tmp_path, jev, cache_dir=tmp_path / "queue")

    await run_twice(pipeline)

    assert jev.analyze_regime.await_count == 1
    assert jev.analyze_sectors.await_count == 1
    first, second = (call.args for call in tier2.shortlist.await_args_list)
    assert first[0]["regime"] == second[0]["regime"] == "trending_up"
    assert first[1]["reasoning"] == second[1]["reasoning"] == "bullish"


async def test_the_cache_file_lives_in_the_queue_dir_and_is_plain_json(tmp_path):
    queue = tmp_path / "queue"
    pipeline, _ = make(tmp_path, drifting_jev(), cache_dir=queue)

    with pytest.raises(AnswersNeeded):
        await pipeline.run(TRADE_DATE)

    cached = json.loads((queue / "jev_tier2.json").read_text())
    assert cached["regime"]["regime"] == "trending_up"
    assert cached["sectors"]["reasoning"] == "bullish"


async def test_without_a_cache_dir_jev_is_asked_every_run(tmp_path):
    # The web API path keeps its historical behaviour.
    jev = drifting_jev()
    pipeline, tier2 = make(tmp_path, jev, cache_dir=None)

    await run_twice(pipeline)

    assert jev.analyze_regime.await_count == 2
    first, second = (call.args for call in tier2.shortlist.await_args_list)
    assert first[0]["regime"] == "trending_up" and second[0]["regime"] == "range_bound"


async def test_a_failed_jev_call_is_not_cached_so_the_next_run_retries(tmp_path):
    jev = MagicMock()
    jev.analyze_regime = AsyncMock(side_effect=[None, regime("range_bound", 0.6)])
    jev.analyze_sectors = AsyncMock(return_value=sectors("neutral"))
    pipeline, tier2 = make(tmp_path, jev, cache_dir=tmp_path / "queue")
    tier2.analyze_regime.return_value = regime("trending_down", 0.5)  # the LLM fallback on run 1
    tier2.analyze_sectors.return_value = sectors("neutral")

    await run_twice(pipeline)

    assert jev.analyze_regime.await_count == 2  # None was not remembered


async def test_a_corrupt_cache_file_is_ignored_not_fatal(tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    (queue / "jev_tier2.json").write_text("{not json")
    jev = drifting_jev()
    pipeline, tier2 = make(tmp_path, jev, cache_dir=queue)

    with pytest.raises(AnswersNeeded):
        await pipeline.run(TRADE_DATE)

    assert jev.analyze_regime.await_count == 1
    assert tier2.shortlist.await_args.args[0]["regime"] == "trending_up"


def test_staged_runs_get_a_cache_dir_and_the_web_path_does_not():
    from tradingbot.api.analysis_routes import _pipeline_cache_dir

    staged = SimpleNamespace(require_prefetched=True, config=SimpleNamespace(llm=SimpleNamespace(queue_dir="/q/2026-11-02")))
    web = SimpleNamespace(require_prefetched=False, config=SimpleNamespace(llm=SimpleNamespace(queue_dir="/q")))

    assert _pipeline_cache_dir(staged) == Path("/q/2026-11-02")
    assert _pipeline_cache_dir(web) is None
