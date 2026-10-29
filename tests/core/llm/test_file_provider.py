import json
import os
import time

import pytest

from tradingbot.analysis.prompts import (
    ADVERSARIAL_TOOL,
    DEEP_ANALYSIS_TOOL,
    REGIME_TOOL,
    SECTOR_TOOL,
    SHORTLIST_TOOL,
)
from tradingbot.core.llm.file_provider import AnswersNeeded, FileAnswerProvider, request_id

SCHEMA = {
    "type": "object",
    "properties": {"picks": {"type": "array", "items": {"type": "string"}}},
    "required": ["picks"],
    "additionalProperties": False,
}
TOOL = ("submit_picks", "Submit picks", SCHEMA)


def call(provider, user_prompt="user", tool=TOOL):
    name, description, schema = tool
    return provider.analyze(
        system_prompt="system",
        user_prompt=user_prompt,
        tool_name=name,
        tool_description=description,
        input_schema=schema,
    )


def rid(user_prompt="user", tool_name="submit_picks"):
    return request_id(tool_name, "system", user_prompt)


def write_answer(tmp_path, answer, user_prompt="user", tool_name="submit_picks"):
    answers = tmp_path / "answers"
    answers.mkdir(exist_ok=True)
    path = answers / f"{rid(user_prompt, tool_name)}.json"
    path.write_text(answer if isinstance(answer, str) else json.dumps(answer))
    return path


def test_request_id_is_stable_and_changes_with_user_prompt():
    assert rid("a") == rid("a")
    assert rid("a") != rid("b")
    assert len(rid("a")) == 16


async def test_missing_answer_writes_request_and_raises_answers_needed_without_waiting(tmp_path):
    provider = FileAnswerProvider(tmp_path)

    started = time.monotonic()
    with pytest.raises(AnswersNeeded) as raised:
        await call(provider)
    assert time.monotonic() - started < 0.5

    request_path = tmp_path / "requests" / f"{rid()}.json"
    assert raised.value.requests == [request_path]
    request = json.loads(request_path.read_text())
    assert set(request) == {
        "id", "tool_name", "tool_description", "system_prompt",
        "user_prompt", "input_schema", "created_at",
    }
    assert request["id"] == rid()
    assert request["input_schema"] == SCHEMA


async def test_existing_valid_answer_is_returned_and_no_request_written(tmp_path):
    write_answer(tmp_path, {"picks": ["RELIANCE"]})

    result = await call(FileAnswerProvider(tmp_path))

    assert result == {"picks": ["RELIANCE"]}
    assert not (tmp_path / "requests").exists()


async def test_request_file_is_written_once(tmp_path):
    provider = FileAnswerProvider(tmp_path)
    with pytest.raises(AnswersNeeded):
        await call(provider)
    path = tmp_path / "requests" / f"{rid()}.json"
    first = path.read_text()

    time.sleep(0.01)
    with pytest.raises(AnswersNeeded):
        await call(provider)

    assert path.read_text() == first
    assert len(list((tmp_path / "requests").iterdir())) == 1


async def test_schema_violation_is_rejected_with_reason_and_request_stays_pending(tmp_path):
    answer_path = write_answer(tmp_path, {"wrong": 1})

    with pytest.raises(AnswersNeeded):
        await call(FileAnswerProvider(tmp_path))

    assert not answer_path.exists()
    assert (tmp_path / "rejected" / f"{rid()}.json").exists()
    reason = (tmp_path / "rejected" / f"{rid()}.reason.txt").read_text()
    assert "picks" in reason
    assert (tmp_path / "requests" / f"{rid()}.json").exists()


async def test_corrected_answer_after_rejection_is_accepted(tmp_path):
    provider = FileAnswerProvider(tmp_path)
    write_answer(tmp_path, {"wrong": 1})
    with pytest.raises(AnswersNeeded):
        await call(provider)

    write_answer(tmp_path, {"picks": ["INFY"]})

    assert await call(provider) == {"picks": ["INFY"]}


async def test_unparseable_fresh_file_is_pending_not_rejected(tmp_path):
    path = write_answer(tmp_path, '{"picks": ["REL')

    with pytest.raises(AnswersNeeded):
        await call(FileAnswerProvider(tmp_path))

    assert path.exists()
    assert not (tmp_path / "rejected").exists()


async def test_unparseable_old_file_is_rejected(tmp_path):
    path = write_answer(tmp_path, '{"picks": ["REL')
    ten_seconds_ago = time.time() - 10
    os.utime(path, (ten_seconds_ago, ten_seconds_ago))

    with pytest.raises(AnswersNeeded):
        await call(FileAnswerProvider(tmp_path))

    assert not path.exists()
    assert (tmp_path / "rejected" / f"{rid()}.reason.txt").exists()


async def test_health_check_true_for_writable_dir_and_does_not_wait(tmp_path):
    started = time.monotonic()

    assert await FileAnswerProvider(tmp_path).health_check() is True
    assert time.monotonic() - started < 0.5


MINIMAL_ANSWERS = {
    "submit_regime_analysis": {
        "regime": "range_bound",
        "regime_confidence": 0.7,
        "bias": "neutral",
        "key_levels": {
            "nifty_support": 24000.0, "nifty_resistance": 24500.0,
            "banknifty_support": 52000.0, "banknifty_resistance": 53000.0,
        },
        "sectors_in_play": ["IT"],
        "risk_appetite": "moderate",
        "reasoning": "test",
    },
    "submit_sector_analysis": {
        "sectors": [
            {"name": "IT", "theme": "t", "intraday_bias": "bullish", "catalyst": "c"},
        ],
        "reasoning": "test",
    },
    "submit_shortlist": {
        "shortlist": [{
            "symbol": "INFY", "direction": "long", "conviction": "high",
            "reasoning": "r", "primary_strategy": "breakout",
            "key_levels": {"support": 1.0, "resistance": 2.0, "vwap": 1.5},
            "risk_flag": "none", "counter_argument": "c",
        }],
        "max_positions_today": 3,
        "reasoning": "test",
    },
    "submit_deep_analysis": {
        "symbol": "INFY",
        "setups": [{
            "strategy": "breakout", "direction": "long", "entry_trigger": "t",
            "entry_price": 100.0, "stop_loss": 95.0, "target_1": 110.0,
            "target_2": 115.0, "position_size_hint": "1x", "entry_window": "09:30-10:30",
            "exit_deadline": "15:10", "confidence": 0.7, "edge_description": "e",
            "invalidation": "i", "bear_case": "b", "confluence_count": 3,
            "timeframe_alignment": ["5m"],
        }],
        "no_trade_reason": None,
    },
    "submit_validation": {
        "approved": [{"symbol": "INFY", "setup_index": 0, "approval": "strong", "adjustment": None}],
        "rejected": [],
        "portfolio_risk_assessment": {
            "total_setups": 1, "approved_count": 1, "max_correlated_exposure": "low",
            "regime_alignment": "ok", "worst_case_loss": "1%", "recommendation": "go",
        },
    },
}


@pytest.mark.parametrize(
    "tool", [REGIME_TOOL, SECTOR_TOOL, SHORTLIST_TOOL, DEEP_ANALYSIS_TOOL, ADVERSARIAL_TOOL],
    ids=lambda tool: tool[0],
)
async def test_production_tool_schemas_accept_minimal_valid_answers(tmp_path, tool):
    name = tool[0]
    write_answer(tmp_path, MINIMAL_ANSWERS[name], tool_name=name)

    result = await call(FileAnswerProvider(tmp_path), tool=tool)

    assert result == MINIMAL_ANSWERS[name]
