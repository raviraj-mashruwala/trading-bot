import inspect

import pytest

from tradingbot.core.llm.provider import LLMError, LLMProvider, LLMResponseError, LLMTimeoutError


def test_provider_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        LLMProvider()


def test_provider_declares_the_expected_async_methods():
    assert inspect.iscoroutinefunction(LLMProvider.analyze)
    assert inspect.iscoroutinefunction(LLMProvider.health_check)


def test_analyze_signature_is_stable():
    params = list(inspect.signature(LLMProvider.analyze).parameters)
    assert params == [
        "self",
        "system_prompt",
        "user_prompt",
        "tool_name",
        "tool_description",
        "input_schema",
    ]


def test_specific_errors_subclass_llm_error():
    assert issubclass(LLMTimeoutError, LLMError)
    assert issubclass(LLMResponseError, LLMError)


def test_a_concrete_subclass_can_be_instantiated():
    class StubProvider(LLMProvider):
        async def analyze(self, system_prompt, user_prompt, tool_name, tool_description, input_schema):
            return {"ok": True}

        async def health_check(self):
            return True

    assert isinstance(StubProvider(), LLMProvider)
