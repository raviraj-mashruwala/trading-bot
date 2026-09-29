# tests/executor/test_llm_escalator.py
from datetime import datetime, time
from unittest.mock import AsyncMock, patch, MagicMock
import json
import pytest
from tradingbot.executor.llm_escalator import LLMEscalator, EscalationResult
from tradingbot.executor.momentum_scorer import SymbolState
from tradingbot.executor.candle_aggregator import LiveCandle


def _state(**overrides) -> SymbolState:
    defaults = dict(
        symbol="RELIANCE", timestamp=datetime(2026, 9, 29, 10, 30),
        momentum_1m=10.0, momentum_5m=-15.0,
        volume_ratio=0.9, volume_trend="falling",
        vwap=2450.0, vwap_position=-0.3, price_vs_open=-0.2,
        last_pattern_1m="none", last_pattern_5m="none",
        body_dominance=0.4, trend_alignment=False, strength="weak",
    )
    defaults.update(overrides)
    return SymbolState(**defaults)


class FakeLeg:
    def __init__(self):
        self.symbol = "RELIANCE"
        self.direction = type("D", (), {"value": "LONG"})()
        self.entry_price = 2450.0
        self.stop_loss = 2430.0
        self.target_1 = 2470.0
        self.target_2 = 2490.0
        self.strategy = type("S", (), {"value": "BREAKOUT"})()
        self.confidence = 0.75
        self.reasoning = "Strong breakout above resistance"


def _candle(minute, o, c, vol=1000):
    return LiveCandle("RELIANCE", "1min", datetime(2026, 9, 29, 10, minute),
                      o, max(o, c) + 1, min(o, c) - 1, c, vol, True)


@pytest.fixture
def mock_anthropic():
    with patch("tradingbot.executor.llm_escalator.anthropic") as m:
        client = MagicMock()
        m.Anthropic.return_value = client
        response = MagicMock()
        response.content = [MagicMock(text=json.dumps({
            "action": "WAIT",
            "confidence": 0.6,
            "reasoning": "Volume declining suggests exhaustion but no reversal candle yet"
        }))]
        client.messages.create.return_value = response
        yield client


@pytest.mark.asyncio
async def test_evaluate_entry_returns_result(mock_anthropic):
    esc = LLMEscalator()
    result = await esc.evaluate_entry(
        FakeLeg(), _state(),
        [_candle(20, 2450, 2448), _candle(21, 2448, 2445)],
        [_candle(20, 2455, 2448)],
    )
    assert isinstance(result, EscalationResult)
    assert result.action == "WAIT"
    assert not result.fallback_used
    assert esc.escalation_count == 1


@pytest.mark.asyncio
async def test_max_escalations_enforced(mock_anthropic):
    esc = LLMEscalator(max_escalations=2)
    await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    assert result.fallback_used
    assert result.action == "WAIT"
    assert esc.escalation_count == 2


@pytest.mark.asyncio
async def test_malformed_response_triggers_fallback():
    with patch("tradingbot.executor.llm_escalator.anthropic") as m:
        client = MagicMock()
        m.Anthropic.return_value = client
        response = MagicMock()
        response.content = [MagicMock(text="not json at all")]
        client.messages.create.return_value = response
        esc = LLMEscalator()
        result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
        assert result.fallback_used
        assert result.action == "WAIT"


@pytest.mark.asyncio
async def test_api_exception_triggers_fallback():
    with patch("tradingbot.executor.llm_escalator.anthropic") as m:
        client = MagicMock()
        m.Anthropic.return_value = client
        client.messages.create.side_effect = Exception("API down")
        esc = LLMEscalator()
        result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
        assert result.fallback_used
        assert result.action == "WAIT"


@pytest.mark.asyncio
async def test_exit_escalation_defaults_to_hold(mock_anthropic):
    mock_anthropic.messages.create.side_effect = Exception("timeout")
    esc = LLMEscalator()
    result = await esc.evaluate_exit(
        MagicMock(), _state(), [], []
    )
    assert result.fallback_used
    assert result.action == "HOLD"


@pytest.mark.asyncio
async def test_entry_prompt_includes_degradation_warning(mock_anthropic):
    esc = LLMEscalator()
    await esc.evaluate_entry(
        FakeLeg(), _state(), [], [], ticker_degraded=True,
    )
    call_args = mock_anthropic.messages.create.call_args
    prompt_text = call_args.kwargs["messages"][0]["content"]
    assert "degraded" in prompt_text.lower()
    assert "REST LTP only" in prompt_text


def test_escalation_result_is_frozen():
    r = EscalationResult(action="WAIT", reasoning="test", confidence=0.5, fallback_used=False)
    with pytest.raises(AttributeError):
        r.action = "ENTER"
