"""Provider-agnostic LLM interface. Swapping vendors must not touch agent code."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0, "cache_read": 1.50, "cache_write": 18.75},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cache_read": 1.50, "cache_write": 18.75},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0, "cache_read": 0.08, "cache_write": 1.0},
}
DEFAULT_PRICING: dict[str, float] = {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75}


@dataclass
class LLMUsage:
    """Token usage and cost for a single LLM call."""

    input_tokens: int
    output_tokens: int
    model: str
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    def cost_usd(self) -> float:
        pricing = MODEL_PRICING.get(self.model, DEFAULT_PRICING)
        return (
            self.input_tokens * pricing["input"] / 1_000_000
            + self.output_tokens * pricing["output"] / 1_000_000
            + self.cache_read_tokens * pricing.get("cache_read", 0.30) / 1_000_000
            + self.cache_creation_tokens * pricing.get("cache_write", 3.75) / 1_000_000
        )


class LLMError(Exception):
    """Base class for every LLM failure."""


class LLMTimeoutError(LLMError):
    """The model did not respond within the configured timeout."""


class LLMResponseError(LLMError):
    """The model responded, but not with the structured output we asked for."""


class LLMProvider(ABC):
    """Every provider returns structured output via a forced tool call."""

    @abstractmethod
    async def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Send the prompts and return the tool input the model produced."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True when the provider is reachable and credentials work."""
