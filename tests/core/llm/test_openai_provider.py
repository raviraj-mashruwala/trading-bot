import json
from types import SimpleNamespace

import pytest

from tradingbot.core.config import ConfigError, LLMConfig, Secrets
from tradingbot.core.llm.anthropic_provider import build_provider
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


# --- build_provider integration tests ---


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
