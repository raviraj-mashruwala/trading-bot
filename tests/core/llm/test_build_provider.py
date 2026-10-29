from pathlib import Path

import pytest

from tradingbot.core.config import LLMConfig, Secrets
from tradingbot.core.llm.anthropic_provider import build_provider
from tradingbot.core.llm.file_provider import FileAnswerProvider

SECRETS = Secrets(anthropic_api_key="", kite_api_key="k", kite_api_secret="s")


def llm_config(provider, **overrides):
    return LLMConfig(provider=provider, model="m", timeout_sec=60, max_retries=1, **overrides)


def test_build_provider_returns_file_provider_for_file(tmp_path):
    provider = build_provider(llm_config("file", queue_dir=str(tmp_path / "q")), SECRETS)

    assert isinstance(provider, FileAnswerProvider)
    assert provider.queue_dir == Path(tmp_path / "q")


def test_build_provider_unknown_provider_message_lists_anthropic_and_file():
    with pytest.raises(ValueError, match="anthropic.*file"):
        build_provider(llm_config("openai"), SECRETS)
