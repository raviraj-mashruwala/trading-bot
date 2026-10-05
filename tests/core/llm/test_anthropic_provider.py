import json
from types import SimpleNamespace

import pytest

from tradingbot.core.config import LLMConfig
from tradingbot.core.llm.anthropic_provider import AnthropicProvider
from tradingbot.core.llm.provider import LLMResponseError

SCHEMA = {
    "type": "object",
    "properties": {"picks": {"type": "array", "items": {"type": "string"}}},
    "required": ["picks"],
    "additionalProperties": False,
}


def make_config() -> LLMConfig:
    return LLMConfig(provider="anthropic", model="claude-sonnet-5", timeout_sec=60, max_retries=1)


class FakeMessages:
    """Stands in for client.messages, recording the kwargs it was called with."""

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
    return SimpleNamespace(messages=FakeMessages(responses))


def tool_use_response(payload, tool_name="emit_result"):
    block = SimpleNamespace(type="tool_use", name=tool_name, input=payload)
    usage = SimpleNamespace(input_tokens=0, output_tokens=0,
                            cache_read_input_tokens=0, cache_creation_input_tokens=0)
    return SimpleNamespace(content=[block], stop_reason="tool_use", usage=usage)


def text_only_response(text="I cannot help with that."):
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block], stop_reason="end_turn")


async def test_analyze_returns_the_tool_input(tmp_path):
    client = make_client([tool_use_response({"picks": ["RELIANCE", "TCS"]})])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    result = await provider.analyze(
        system_prompt="You are an analyst.",
        user_prompt="Pick two stocks.",
        tool_name="emit_result",
        tool_description="Return the chosen stocks.",
        input_schema=SCHEMA,
    )

    assert result["picks"] == ["RELIANCE", "TCS"]


async def test_analyze_sends_the_configured_model_and_tool(tmp_path):
    client = make_client([tool_use_response({"picks": []})])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)

    sent = client.messages.calls[0]
    assert sent["model"] == "claude-sonnet-5"
    assert sent["system"][0]["text"] == "sys"
    assert sent["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert sent["tools"][0]["name"] == "emit_result"
    assert sent["tools"][0]["input_schema"] == SCHEMA
    assert sent["tools"][0]["cache_control"] == {"type": "ephemeral"}
    assert sent["messages"] == [{"role": "user", "content": "user"}]


async def test_missing_tool_use_block_raises_llm_response_error(tmp_path):
    client = make_client([text_only_response(), text_only_response()])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    with pytest.raises(LLMResponseError, match="no tool_use block"):
        await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)


async def test_a_transient_failure_is_retried_once(tmp_path):
    client = make_client([RuntimeError("connection reset"), tool_use_response({"picks": ["INFY"]})])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    result = await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)

    assert result["picks"] == ["INFY"]
    assert len(client.messages.calls) == 2


async def test_failures_beyond_max_retries_raise(tmp_path):
    client = make_client([RuntimeError("boom"), RuntimeError("boom again")])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    with pytest.raises(Exception, match="boom again"):
        await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)


async def test_every_call_is_logged_as_jsonl(tmp_path):
    client = make_client([tool_use_response({"picks": ["SBIN"]})])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    await provider.analyze("sys prompt", "user prompt", "emit_result", "desc", SCHEMA)

    log_files = list(tmp_path.glob("*.jsonl"))
    assert len(log_files) == 1
    entry = json.loads(log_files[0].read_text().strip())
    assert entry["tool_name"] == "emit_result"
    assert entry["system_prompt"] == "sys prompt"
    assert entry["response"] == {"picks": ["SBIN"]}


async def test_the_api_key_never_appears_in_the_log(tmp_path):
    client = make_client([tool_use_response({"picks": []})])
    provider = AnthropicProvider(
        make_config(), api_key="sk-ant-super-secret", client=client, log_dir=tmp_path
    )

    await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)

    written = "".join(path.read_text() for path in tmp_path.glob("*.jsonl"))
    assert "sk-ant-super-secret" not in written


async def test_health_check_is_true_when_the_call_succeeds(tmp_path):
    client = make_client([tool_use_response({"ok": True}, "report_health")])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    assert await provider.health_check() is True


async def test_health_check_is_false_when_the_call_fails(tmp_path):
    client = make_client([RuntimeError("no network"), RuntimeError("still no network")])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    assert await provider.health_check() is False


async def test_analyze_tracks_cache_tokens_in_usage(tmp_path):
    resp = tool_use_response({"picks": ["A"]})
    resp.usage = SimpleNamespace(input_tokens=200, output_tokens=50,
                                 cache_read_input_tokens=500, cache_creation_input_tokens=0)
    client = make_client([resp])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    result = await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)

    usage = result["_usage"]
    assert usage.cache_read_tokens == 500
    assert usage.cache_creation_tokens == 0
