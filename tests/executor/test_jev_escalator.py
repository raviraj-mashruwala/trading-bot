"""Tests for JevEscalator — drop-in replacement for LLMEscalator."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tradingbot.core.config import JevConfig
from tradingbot.executor.llm_escalator import EscalationResult
from tradingbot.executor.momentum_scorer import SymbolState


def _jev_config(**overrides) -> JevConfig:
    defaults = dict(
        enabled=True, model="jev-latest",
        entry_confidence_threshold=0.6,
        exit_confidence_threshold=0.75,
        uncertainty_threshold=0.3, timeout_ms=2000,
    )
    defaults.update(overrides)
    return JevConfig(**defaults)


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
        self.direction = SimpleNamespace(value="long")
        self.entry_price = 2450.0
        self.stop_loss = 2430.0
        self.target_1 = 2470.0
        self.target_2 = 2490.0
        self.strategy = SimpleNamespace(value="breakout")
        self.confidence = 0.75
        self.reasoning = "Strong breakout"


def _noul(value: float):
    return SimpleNamespace(noul=value)


def _choice(value: str, confidence: float = 0.8):
    return SimpleNamespace(choice=value, confidence=confidence)


def _score(value: float, confidence: float = 0.8):
    return SimpleNamespace(score=value, confidence=confidence)


def _mock_jev_client(answers: dict | None) -> MagicMock:
    client = MagicMock()
    client.available = answers is not None
    client.aevaluate = AsyncMock(return_value=answers)
    return client


# --- Entry tests ---

@pytest.mark.asyncio
async def test_entry_enter_high_confidence():
    from tradingbot.executor.jev_escalator import JevEscalator
    answers = {
        "should_enter": _noul(0.85),
        "invalidated": _noul(0.05),
        "timing": _choice("enter_now", 0.91),
    }
    jev = _mock_jev_client(answers)
    esc = JevEscalator(jev, _jev_config())
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    assert result.action == "ENTER"
    assert result.confidence > 0.6
    assert not result.fallback_used
    assert "jev:" in result.reasoning


@pytest.mark.asyncio
async def test_entry_skip_invalidated():
    from tradingbot.executor.jev_escalator import JevEscalator
    answers = {
        "should_enter": _noul(0.50),
        "invalidated": _noul(0.80),
        "timing": _choice("enter_now", 0.5),
    }
    jev = _mock_jev_client(answers)
    esc = JevEscalator(jev, _jev_config())
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    assert result.action == "SKIP"


@pytest.mark.asyncio
async def test_entry_skip_timing():
    from tradingbot.executor.jev_escalator import JevEscalator
    answers = {
        "should_enter": _noul(0.50),
        "invalidated": _noul(0.10),
        "timing": _choice("skip", 0.85),
    }
    jev = _mock_jev_client(answers)
    esc = JevEscalator(jev, _jev_config())
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    assert result.action == "SKIP"


@pytest.mark.asyncio
async def test_entry_wait_moderate():
    from tradingbot.executor.jev_escalator import JevEscalator
    answers = {
        "should_enter": _noul(0.45),
        "invalidated": _noul(0.10),
        "timing": _choice("wait_5min", 0.6),
    }
    jev = _mock_jev_client(answers)
    esc = JevEscalator(jev, _jev_config())
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    assert result.action == "WAIT"
    assert not result.fallback_used


@pytest.mark.asyncio
async def test_entry_claude_fallback_low_confidence():
    from tradingbot.executor.jev_escalator import JevEscalator
    answers = {
        "should_enter": _noul(0.15),
        "invalidated": _noul(0.10),
        "timing": _choice("wait_5min", 0.3),
    }
    jev = _mock_jev_client(answers)
    llm = AsyncMock()
    llm.evaluate_entry = AsyncMock(
        return_value=EscalationResult("ENTER", "LLM says go", 0.7, False),
    )
    esc = JevEscalator(jev, _jev_config(), llm_fallback=llm)
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    assert result.action == "ENTER"
    assert result.reasoning == "LLM says go"
    llm.evaluate_entry.assert_awaited_once()


@pytest.mark.asyncio
async def test_entry_jev_unavailable_uses_fallback():
    from tradingbot.executor.jev_escalator import JevEscalator
    jev = _mock_jev_client(None)  # available = False
    llm = AsyncMock()
    llm.evaluate_entry = AsyncMock(
        return_value=EscalationResult("WAIT", "LLM wait", 0.5, False),
    )
    esc = JevEscalator(jev, _jev_config(), llm_fallback=llm)
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    assert result.action == "WAIT"
    llm.evaluate_entry.assert_awaited_once()


@pytest.mark.asyncio
async def test_entry_jev_timeout_uses_fallback():
    from tradingbot.executor.jev_escalator import JevEscalator
    jev = MagicMock()
    jev.available = True
    jev.aevaluate = AsyncMock(return_value=None)
    llm = AsyncMock()
    llm.evaluate_entry = AsyncMock(
        return_value=EscalationResult("WAIT", "LLM fallback", 0.4, False),
    )
    esc = JevEscalator(jev, _jev_config(), llm_fallback=llm)
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    llm.evaluate_entry.assert_awaited_once()


@pytest.mark.asyncio
async def test_entry_all_unavailable_returns_wait():
    from tradingbot.executor.jev_escalator import JevEscalator
    jev = MagicMock()
    jev.available = True
    jev.aevaluate = AsyncMock(return_value=None)
    llm = AsyncMock()
    llm.evaluate_entry = AsyncMock(side_effect=Exception("LLM down"))
    esc = JevEscalator(jev, _jev_config(), llm_fallback=llm)
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    assert result.action == "WAIT"
    assert result.fallback_used is True


# --- Exit tests ---

@pytest.mark.asyncio
async def test_exit_close_high_confidence():
    from tradingbot.executor.jev_escalator import JevEscalator
    answers = {
        "exit_now": _noul(0.90),
        "momentum_exhaustion": _noul(0.80),
        "reversal_risk": _score(3.2, 0.85),
    }
    jev = _mock_jev_client(answers)
    esc = JevEscalator(jev, _jev_config())
    result = await esc.evaluate_exit(MagicMock(), _state(), [], [])
    assert result.action == "EXIT"
    assert not result.fallback_used


@pytest.mark.asyncio
async def test_exit_tighten_stop():
    from tradingbot.executor.jev_escalator import JevEscalator
    answers = {
        "exit_now": _noul(0.50),
        "momentum_exhaustion": _noul(0.70),
        "reversal_risk": _score(3.0, 0.80),
    }
    jev = _mock_jev_client(answers)
    esc = JevEscalator(jev, _jev_config())
    result = await esc.evaluate_exit(MagicMock(), _state(), [], [])
    assert result.action == "HOLD"
    assert "tighten_stop" in result.reasoning


@pytest.mark.asyncio
async def test_entry_malformed_answers_uses_fallback():
    from tradingbot.executor.jev_escalator import JevEscalator
    answers = {"should_enter": _noul(0.85)}  # missing invalidated, timing
    jev = _mock_jev_client(answers)
    llm = AsyncMock()
    llm.evaluate_entry = AsyncMock(
        return_value=EscalationResult("WAIT", "LLM fallback", 0.4, False),
    )
    esc = JevEscalator(jev, _jev_config(), llm_fallback=llm)
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    llm.evaluate_entry.assert_awaited_once()


@pytest.mark.asyncio
async def test_exit_malformed_answers_uses_fallback():
    from tradingbot.executor.jev_escalator import JevEscalator
    answers = {"exit_now": _noul(0.9)}  # missing momentum_exhaustion, reversal_risk
    jev = _mock_jev_client(answers)
    llm = AsyncMock()
    llm.evaluate_exit = AsyncMock(
        return_value=EscalationResult("HOLD", "LLM fallback", 0.5, False),
    )
    esc = JevEscalator(jev, _jev_config(), llm_fallback=llm)
    result = await esc.evaluate_exit(MagicMock(), _state(), [], [])
    llm.evaluate_exit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reasoning_contains_scores():
    from tradingbot.executor.jev_escalator import JevEscalator
    answers = {
        "should_enter": _noul(0.72),
        "invalidated": _noul(0.05),
        "timing": _choice("enter_now", 0.88),
    }
    jev = _mock_jev_client(answers)
    esc = JevEscalator(jev, _jev_config())
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    assert "jev:" in result.reasoning
    assert "0.72" in result.reasoning
    assert "enter_now" in result.reasoning
