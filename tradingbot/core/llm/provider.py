"""Provider-agnostic LLM interface. Swapping vendors must not touch agent code."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


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
