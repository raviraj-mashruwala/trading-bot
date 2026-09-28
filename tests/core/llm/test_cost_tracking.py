"""Tests for LLM cost tracking via LLMUsage dataclass."""

import pytest
from tradingbot.core.llm.provider import LLMUsage


def test_llm_usage_cost_calculation():
    usage = LLMUsage(input_tokens=1000, output_tokens=500, model="claude-sonnet-4-20250514")
    cost = usage.cost_usd()
    assert cost > 0
    # Sonnet: $3/M input, $15/M output
    expected = (1000 * 3 / 1_000_000) + (500 * 15 / 1_000_000)
    assert abs(cost - expected) < 0.0001


def test_llm_usage_zero_tokens():
    usage = LLMUsage(input_tokens=0, output_tokens=0, model="unknown-model")
    assert usage.cost_usd() == 0.0


def test_llm_usage_unknown_model_defaults():
    usage = LLMUsage(input_tokens=100, output_tokens=50, model="unknown")
    cost = usage.cost_usd()
    assert cost >= 0  # should not crash
