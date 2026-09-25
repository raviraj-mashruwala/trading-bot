# OpenAI Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OpenAI/GPT as a second LLM provider so the user can choose between Claude and GPT via a config toggle.

**Architecture:** New `OpenAIProvider` class implementing the existing `LLMProvider` ABC. Uses OpenAI's function calling (the equivalent of Claude's `tool_use`) to get structured JSON output. Config-driven: `provider = "openai"` in `config.toml` selects it; `OPENAI_API_KEY` in `.env` authenticates it. The existing scanner and strategy modules call `provider.analyze()` unchanged.

**Tech Stack:** openai (async client), existing LLMProvider ABC, existing test patterns (stub client injection).

**Spec:** No separate spec — bounded change extending `docs/superpowers/specs/2026-09-23-intraday-trading-bot-design.md` § LLM Integration § Provider Interface.

## Global Constraints

- Python 3.12+
- No heavy frameworks
- LLM structured output via function calling — never regex or free-text parsing
- Secrets only in `.env`, never logged
- `OPENAI_API_KEY` is optional — only required when `provider = "openai"` in config
- `ANTHROPIC_API_KEY` remains required when `provider = "anthropic"` (the default)

## Review Focus

1. **OpenAI returns no function call** — model responds with plain text instead of calling the function. Must raise `LLMResponseError`, not crash or return `None`. Test in Task 1.
2. **OpenAI returns malformed JSON in function arguments** — the `arguments` field is a JSON string that might be truncated. Must raise `LLMResponseError`. Test in Task 1.
3. **Config says `provider = "openai"` but `OPENAI_API_KEY` is missing** — must raise `ConfigError` with the env var name, not a confusing auth error at call time. Test in Task 1.
4. **Config says `provider = "anthropic"` and `OPENAI_API_KEY` is absent** — must NOT fail. The key is only required for the active provider. Test in Task 1.

---

## Task 1: OpenAI Provider + Config Wiring

**Files:**
- Create: `tradingbot/core/llm/openai_provider.py`
- Modify: `tradingbot/core/llm/anthropic_provider.py` (move `build_provider` and update it)
- Modify: `tradingbot/core/config.py` (make `Secrets` accept optional `openai_api_key`)
- Modify: `pyproject.toml` (add `openai` dependency)
- Modify: `.env.example` (add `OPENAI_API_KEY=`)
- Modify: `config.toml` (add comment showing openai option)
- Test: `tests/core/llm/test_openai_provider.py`

**Interfaces:**
- Consumes: `LLMProvider` ABC from `tradingbot.core.llm.provider`; `LLMConfig`, `Secrets` from `tradingbot.core.config`; `LLMResponseError` from `tradingbot.core.llm.provider`.
- Produces: `OpenAIProvider(config: LLMConfig, api_key: str, client: Any | None = None, log_dir: Path | None = None)` implementing `LLMProvider`. Updated `build_provider()` handling `"openai"`. Updated `Secrets` with optional `openai_api_key`.

- [ ] **Step 1: Add the openai dependency**

In `pyproject.toml`, add to the `dependencies` list:

```
    "openai>=1.40.0",
```

Run: `pip install -e ".[dev]"`

- [ ] **Step 2: Update .env.example**

Append to `.env.example`:

```
OPENAI_API_KEY=sk-replace-me-or-leave-blank
```

- [ ] **Step 3: Update config.toml with a comment**

Change the `[llm]` section comment:

```toml
[llm]
provider = "anthropic"  # "anthropic" or "openai"
model = "claude-sonnet-5"  # or "gpt-4o", "gpt-4o-mini" for openai
timeout_sec = 60
max_retries = 1
```

- [ ] **Step 4: Make Secrets accept an optional OpenAI key**

In `tradingbot/core/config.py`, change the `Secrets` dataclass:

```python
@dataclass(frozen=True)
class Secrets:
    anthropic_api_key: str = field(repr=False)
    kite_api_key: str = field(repr=False)
    kite_api_secret: str = field(repr=False)
    openai_api_key: str = field(default="", repr=False)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "Secrets(<redacted>)"
```

And in `load_config`, change the Secrets construction:

```python
        secrets=Secrets(
            anthropic_api_key=_require_env("ANTHROPIC_API_KEY"),
            kite_api_key=_require_env("KITE_API_KEY"),
            kite_api_secret=_require_env("KITE_API_SECRET"),
            openai_api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
        ),
```

Note: `openai_api_key` uses `os.environ.get` (optional), not `_require_env` (mandatory). It's only validated at provider-build time when `provider = "openai"`.

- [ ] **Step 5: Write the failing test for the OpenAI provider**

Create `tests/core/llm/test_openai_provider.py`:

```python
import json
from types import SimpleNamespace

import pytest

from tradingbot.core.config import LLMConfig
from tradingbot.core.llm.openai_provider import OpenAIProvider
from tradingbot.core.llm.provider import LLMResponseError

SCHEMA = {
    "type": "object",
    "properties": {"picks": {"type": "array", "items": {"type": "string"}}},
    "required": ["picks"],
    "additionalProperties": False,
}


def make_config() -> LLMConfig:
    return LLMConfig(provider="openai", model="gpt-4o", timeout_sec=60, max_retries=1)


class FakeCompletions:
    """Stands in for client.chat.completions, recording calls."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def make_client(responses):
    completions = FakeCompletions(responses)
    chat = SimpleNamespace(completions=completions)
    return SimpleNamespace(chat=chat)


def function_call_response(name, arguments):
    """Simulate an OpenAI response with a function call."""
    func = SimpleNamespace(name=name, arguments=json.dumps(arguments))
    tool_call = SimpleNamespace(id="call_abc123", type="function", function=func)
    choice = SimpleNamespace(
        message=SimpleNamespace(tool_calls=[tool_call], content=None),
        finish_reason="tool_calls",
    )
    return SimpleNamespace(choices=[choice])


def text_only_response(text="I cannot help with that."):
    """Simulate an OpenAI response with no function call."""
    choice = SimpleNamespace(
        message=SimpleNamespace(tool_calls=None, content=text),
        finish_reason="stop",
    )
    return SimpleNamespace(choices=[choice])


def empty_tool_calls_response():
    """Simulate an OpenAI response with an empty tool_calls list."""
    choice = SimpleNamespace(
        message=SimpleNamespace(tool_calls=[], content="Sure, here are the picks."),
        finish_reason="stop",
    )
    return SimpleNamespace(choices=[choice])


async def test_analyze_returns_the_function_arguments(tmp_path):
    client = make_client([function_call_response("emit_result", {"picks": ["RELIANCE", "TCS"]})])
    provider = OpenAIProvider(make_config(), api_key="sk-test", client=client, log_dir=tmp_path)

    result = await provider.analyze(
        system_prompt="You are an analyst.",
        user_prompt="Pick two stocks.",
        tool_name="emit_result",
        tool_description="Return the chosen stocks.",
        input_schema=SCHEMA,
    )

    assert result == {"picks": ["RELIANCE", "TCS"]}


async def test_analyze_sends_the_configured_model_and_function(tmp_path):
    client = make_client([function_call_response("emit_result", {"picks": []})])
    provider = OpenAIProvider(make_config(), api_key="sk-test", client=client, log_dir=tmp_path)

    await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)

    sent = client.chat.completions.calls[0]
    assert sent["model"] == "gpt-4o"
    assert sent["messages"][0] == {"role": "system", "content": "sys"}
    assert sent["messages"][1] == {"role": "user", "content": "user"}
    assert sent["tools"][0]["function"]["name"] == "emit_result"
    assert sent["tools"][0]["function"]["parameters"] == SCHEMA
    assert sent["tool_choice"] == {"type": "function", "function": {"name": "emit_result"}}


async def test_missing_function_call_raises_llm_response_error(tmp_path):
    client = make_client([text_only_response(), text_only_response()])
    provider = OpenAIProvider(make_config(), api_key="sk-test", client=client, log_dir=tmp_path)

    with pytest.raises(LLMResponseError, match="no function call"):
        await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)


async def test_empty_tool_calls_raises_llm_response_error(tmp_path):
    client = make_client([empty_tool_calls_response(), empty_tool_calls_response()])
    provider = OpenAIProvider(make_config(), api_key="sk-test", client=client, log_dir=tmp_path)

    with pytest.raises(LLMResponseError, match="no function call"):
        await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)


async def test_malformed_arguments_json_raises_llm_response_error(tmp_path):
    func = SimpleNamespace(name="emit_result", arguments="{truncated")
    tool_call = SimpleNamespace(id="call_bad", type="function", function=func)
    choice = SimpleNamespace(
        message=SimpleNamespace(tool_calls=[tool_call], content=None),
        finish_reason="tool_calls",
    )
    bad_response = SimpleNamespace(choices=[choice])

    client = make_client([bad_response, bad_response])
    provider = OpenAIProvider(make_config(), api_key="sk-test", client=client, log_dir=tmp_path)

    with pytest.raises(LLMResponseError, match="malformed"):
        await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)


async def test_a_transient_failure_is_retried_once(tmp_path):
    client = make_client([
        RuntimeError("connection reset"),
        function_call_response("emit_result", {"picks": ["INFY"]}),
    ])
    provider = OpenAIProvider(make_config(), api_key="sk-test", client=client, log_dir=tmp_path)

    result = await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)

    assert result == {"picks": ["INFY"]}
    assert len(client.chat.completions.calls) == 2


async def test_failures_beyond_max_retries_raise(tmp_path):
    client = make_client([RuntimeError("boom"), RuntimeError("boom again")])
    provider = OpenAIProvider(make_config(), api_key="sk-test", client=client, log_dir=tmp_path)

    with pytest.raises(RuntimeError, match="boom again"):
        await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)


async def test_every_call_is_logged_as_jsonl(tmp_path):
    client = make_client([function_call_response("emit_result", {"picks": ["SBIN"]})])
    provider = OpenAIProvider(make_config(), api_key="sk-test", client=client, log_dir=tmp_path)

    await provider.analyze("sys prompt", "user prompt", "emit_result", "desc", SCHEMA)

    log_files = list(tmp_path.glob("*.jsonl"))
    assert len(log_files) == 1
    entry = json.loads(log_files[0].read_text().strip())
    assert entry["tool_name"] == "emit_result"
    assert entry["system_prompt"] == "sys prompt"
    assert entry["response"] == {"picks": ["SBIN"]}
    assert entry["model"] == "gpt-4o"


async def test_the_api_key_never_appears_in_the_log(tmp_path):
    client = make_client([function_call_response("emit_result", {"picks": []})])
    provider = OpenAIProvider(
        make_config(), api_key="sk-openai-super-secret", client=client, log_dir=tmp_path
    )

    await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)

    written = "".join(path.read_text() for path in tmp_path.glob("*.jsonl"))
    assert "sk-openai-super-secret" not in written


async def test_health_check_is_true_when_the_call_succeeds(tmp_path):
    client = make_client([function_call_response("report_health", {"ok": True})])
    provider = OpenAIProvider(make_config(), api_key="sk-test", client=client, log_dir=tmp_path)

    assert await provider.health_check() is True


async def test_health_check_is_false_when_the_call_fails(tmp_path):
    client = make_client([RuntimeError("no network"), RuntimeError("still no")])
    provider = OpenAIProvider(make_config(), api_key="sk-test", client=client, log_dir=tmp_path)

    assert await provider.health_check() is False
```

- [ ] **Step 6: Run the tests to verify they fail**

Run: `pytest tests/core/llm/test_openai_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.core.llm.openai_provider'`

- [ ] **Step 7: Implement the OpenAI provider**

Create `tradingbot/core/llm/openai_provider.py`:

```python
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

            self.client = AsyncOpenAI(api_key=api_key, timeout=config.timeout_sec)

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
```

- [ ] **Step 8: Update build_provider to handle "openai"**

In `tradingbot/core/llm/anthropic_provider.py`, change `build_provider`:

```python
def build_provider(
    config: LLMConfig,
    secrets: Secrets,
    log_dir: Path | None = None,
) -> LLMProvider:
    """Return the provider named in config."""
    if config.provider == "anthropic":
        return AnthropicProvider(config, api_key=secrets.anthropic_api_key, log_dir=log_dir)
    if config.provider == "openai":
        from tradingbot.core.llm.openai_provider import OpenAIProvider

        if not secrets.openai_api_key:
            from tradingbot.core.config import ConfigError

            raise ConfigError("OPENAI_API_KEY is not set but llm.provider is 'openai'.")
        return OpenAIProvider(config, api_key=secrets.openai_api_key, log_dir=log_dir)
    raise ValueError(f"unknown llm.provider {config.provider!r}; expected 'anthropic' or 'openai'")
```

- [ ] **Step 9: Write the build_provider integration tests**

Add to `tests/core/llm/test_openai_provider.py`:

```python
from tradingbot.core.config import ConfigError, Secrets, LLMConfig
from tradingbot.core.llm.anthropic_provider import build_provider


def test_build_provider_returns_openai_when_configured():
    config = LLMConfig(provider="openai", model="gpt-4o", timeout_sec=60, max_retries=1)
    secrets = Secrets(
        anthropic_api_key="sk-ant-test",
        kite_api_key="k",
        kite_api_secret="s",
        openai_api_key="sk-openai-test",
    )

    provider = build_provider(config, secrets)

    assert type(provider).__name__ == "OpenAIProvider"


def test_build_provider_raises_when_openai_key_missing():
    config = LLMConfig(provider="openai", model="gpt-4o", timeout_sec=60, max_retries=1)
    secrets = Secrets(
        anthropic_api_key="sk-ant-test",
        kite_api_key="k",
        kite_api_secret="s",
        openai_api_key="",
    )

    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        build_provider(config, secrets)


def test_build_provider_still_works_for_anthropic_without_openai_key():
    config = LLMConfig(provider="anthropic", model="claude-sonnet-5", timeout_sec=60, max_retries=1)
    secrets = Secrets(
        anthropic_api_key="sk-ant-test",
        kite_api_key="k",
        kite_api_secret="s",
        openai_api_key="",
    )

    provider = build_provider(config, secrets)

    assert type(provider).__name__ == "AnthropicProvider"


def test_build_provider_raises_for_unknown_provider():
    config = LLMConfig(provider="gemini", model="x", timeout_sec=60, max_retries=1)
    secrets = Secrets(
        anthropic_api_key="a",
        kite_api_key="k",
        kite_api_secret="s",
        openai_api_key="",
    )

    with pytest.raises(ValueError, match="gemini"):
        build_provider(config, secrets)
```

- [ ] **Step 10: Run the full test suite**

Run: `pytest tests/ -v`
Expected: all existing 254 tests + 15 new OpenAI tests = 269 passing.

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml .env.example config.toml tradingbot/core/config.py tradingbot/core/llm/anthropic_provider.py tradingbot/core/llm/openai_provider.py tests/core/llm/test_openai_provider.py
git commit -m "feat: add OpenAI/GPT as a second LLM provider with function calling"
```

---

## Done

To use OpenAI instead of Claude:

1. Set `OPENAI_API_KEY=sk-...` in `.env`
2. In `config.toml`:
   ```toml
   [llm]
   provider = "openai"
   model = "gpt-4o"       # or "gpt-4o-mini" for cheaper
   ```
3. Run `tradingbot analyze` as normal — the scanner and strategy engine use the same interface.
