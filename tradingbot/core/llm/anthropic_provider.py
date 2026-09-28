"""Claude implementation of LLMProvider. Structured output comes from tool_use."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from tradingbot.core.config import LLMConfig, Secrets
from tradingbot.core.llm.provider import LLMProvider, LLMResponseError, LLMUsage

logger = logging.getLogger(__name__)

MAX_TOKENS = 16000

HEALTH_CHECK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


class AnthropicProvider(LLMProvider):
    """Calls the Anthropic Messages API and returns the forced tool input."""

    def __init__(
        self,
        config: LLMConfig,
        api_key: str,
        client: Any | None = None,
        log_dir: Path | None = None,
    ) -> None:
        self.config = config
        self.log_dir = Path(log_dir) if log_dir is not None else None
        if self.log_dir is not None:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        if client is not None:
            self.client = client
        else:
            from anthropic import AsyncAnthropic

            self.client = AsyncAnthropic(api_key=api_key, timeout=config.timeout_sec)

    async def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
    ) -> dict[str, Any]:
        tool = {
            "name": tool_name,
            "description": tool_description,
            "input_schema": input_schema,
            "strict": True,
        }

        attempts = self.config.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await self.client.messages.create(
                    model=self.config.model,
                    max_tokens=MAX_TOKENS,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                    tools=[tool],
                )
            except Exception as exc:  # noqa: BLE001 - surfaced after retries
                last_error = exc
                logger.warning("LLM call failed on attempt %s/%s: %s", attempt, attempts, exc)
                continue

            payload = self._extract_tool_input(response, tool_name)
            if payload is None:
                last_error = LLMResponseError(
                    f"model returned no tool_use block for {tool_name!r}; "
                    f"stop_reason={getattr(response, 'stop_reason', 'unknown')}"
                )
                logger.warning("LLM returned no tool_use on attempt %s/%s", attempt, attempts)
                continue

            self._log_call(system_prompt, user_prompt, tool_name, payload)

            # Attach token usage for cost tracking (after logging to avoid serialization issues)
            usage = getattr(response, "usage", None)
            payload["_usage"] = LLMUsage(
                input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
                output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
                model=self.config.model,
            )

            return payload

        assert last_error is not None
        raise last_error

    async def health_check(self) -> bool:
        try:
            await self.analyze(
                system_prompt="You are a connectivity probe.",
                user_prompt="Call the tool with ok set to true.",
                tool_name="report_health",
                tool_description="Report that the connection works.",
                input_schema=HEALTH_CHECK_SCHEMA,
            )
        except Exception:  # noqa: BLE001 - a health check never propagates
            return False
        return True

    @staticmethod
    def _extract_tool_input(response: Any, tool_name: str) -> dict[str, Any] | None:
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
                return dict(block.input)
        return None

    def _log_call(
        self,
        system_prompt: str,
        user_prompt: str,
        tool_name: str,
        payload: dict[str, Any],
    ) -> None:
        if self.log_dir is None:
            return
        entry = {
            "model": self.config.model,
            "tool_name": tool_name,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "response": payload,
        }
        path = self.log_dir / f"{date.today().isoformat()}.jsonl"
        with path.open("a") as handle:
            handle.write(json.dumps(entry) + "\n")


def build_provider(
    config: LLMConfig,
    secrets: Secrets,
    log_dir: Path | None = None,
) -> LLMProvider:
    """Return the provider named in config."""
    if config.provider == "anthropic":
        return AnthropicProvider(config, api_key=secrets.anthropic_api_key, log_dir=log_dir)
    raise ValueError(f"unknown llm.provider {config.provider!r}; expected 'anthropic'")
