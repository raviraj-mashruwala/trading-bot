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


def test_llm_usage_cache_read_tokens_cost():
    usage = LLMUsage(
        input_tokens=500, output_tokens=100,
        cache_read_tokens=1000, cache_creation_tokens=0,
        model="claude-sonnet-4-20250514",
    )
    cost = usage.cost_usd()
    expected = (500 * 3 / 1_000_000) + (1000 * 0.30 / 1_000_000) + (100 * 15 / 1_000_000)
    assert abs(cost - expected) < 0.0001


def test_llm_usage_cache_creation_tokens_cost():
    usage = LLMUsage(
        input_tokens=200, output_tokens=100,
        cache_read_tokens=0, cache_creation_tokens=800,
        model="claude-sonnet-4-20250514",
    )
    cost = usage.cost_usd()
    expected = (200 * 3 / 1_000_000) + (800 * 3.75 / 1_000_000) + (100 * 15 / 1_000_000)
    assert abs(cost - expected) < 0.0001


def test_llm_usage_defaults_cache_to_zero():
    usage = LLMUsage(input_tokens=100, output_tokens=50, model="claude-sonnet-4-20250514")
    assert usage.cache_read_tokens == 0
    assert usage.cache_creation_tokens == 0
