"""OpenAI/GPT implementation of LLMProvider. Structured output via function calling."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from tradingbot.core.config import LLMConfig
from tradingbot.core.llm.provider import LLMProvider, LLMResponseError

logger = logging.getLogger(__name__)

MAX_TOKENS = 16000

HEALTH_CHECK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


class OpenAIProvider(LLMProvider):
    """Calls the OpenAI Chat Completions API with forced function calling."""

    def __init__(
        self,
        config: LLMConfig,
        api_key: str,
        base_url: str | None = None,
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
            from openai import AsyncOpenAI

            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=config.timeout_sec,
            )

    async def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
    ) -> dict[str, Any]:
        tool = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool_description,
                "parameters": input_schema,
                "strict": True,
            },
        }

        attempts = self.config.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await self.client.chat.completions.create(
                    model=self.config.model,
                    max_tokens=MAX_TOKENS,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    tools=[tool],
                    tool_choice={"type": "function", "function": {"name": tool_name}},
                )
            except Exception as exc:  # noqa: BLE001 - surfaced after retries
                last_error = exc
                logger.warning("LLM call failed on attempt %s/%s: %s", attempt, attempts, exc)
                continue

            payload = self._extract_function_args(response, tool_name)
            if payload is None:
                last_error = LLMResponseError(
                    f"model returned no function call for {tool_name!r}; "
                    f"finish_reason={getattr(response.choices[0], 'finish_reason', 'unknown')}"
                )
                logger.warning("LLM returned no function call on attempt %s/%s", attempt, attempts)
                continue

            self._log_call(system_prompt, user_prompt, tool_name, payload)
            return payload

        assert last_error is not None
        raise last_error

    async def health_check(self) -> bool:
        try:
            await self.analyze(
                system_prompt="You are a connectivity probe.",
                user_prompt="Call the function with ok set to true.",
                tool_name="report_health",
                tool_description="Report that the connection works.",
                input_schema=HEALTH_CHECK_SCHEMA,
            )
        except Exception:  # noqa: BLE001 - a health check never propagates
            return False
        return True

    @staticmethod
    def _extract_function_args(response: Any, tool_name: str) -> dict[str, Any] | None:
        choices = getattr(response, "choices", None) or []
        if not choices:
            return None

        message = choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            return None

        for call in tool_calls:
            if getattr(call, "type", None) == "function":
                func = getattr(call, "function", None)
                if func is not None and getattr(func, "name", None) == tool_name:
                    try:
                        return json.loads(func.arguments)
                    except (json.JSONDecodeError, TypeError) as exc:
                        raise LLMResponseError(
                            f"malformed function arguments for {tool_name!r}: {exc}"
                        ) from exc

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
            "provider": "openai",
            "model": self.config.model,
            "tool_name": tool_name,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "response": payload,
        }
        path = self.log_dir / f"{date.today().isoformat()}.jsonl"
        with path.open("a") as handle:
            handle.write(json.dumps(entry) + "\n")
