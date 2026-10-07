# Prompt Caching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Anthropic prompt caching to all Claude LLM calls so that repeated system prompts and tool schemas are cached at 10% of normal input cost.

**Architecture:** Convert `system` parameter from plain string to array-of-blocks format with `cache_control` markers. Add cache_control to tool definitions. Track cache hit/miss tokens in LLMUsage for cost visibility. Two files change: `provider.py` (LLMUsage dataclass) and `anthropic_provider.py` (API call format).

**Tech Stack:** Python, Anthropic SDK (`anthropic` package), pytest

**Spec:** Anthropic prompt caching docs — https://platform.claude.com/docs/en/build-with-claude/prompt-caching

## Global Constraints

- `anthropic` SDK version must support `cache_control` on system blocks and tools (available since SDK v0.25+, our version supports it).
- `system` must change from `str` to `list[dict]` format when `cache_control` is present — plain string format does not support cache markers.
- `analyze()` method signature in `LLMProvider` ABC stays unchanged — caching is an implementation detail of `AnthropicProvider`.
- Existing tests must pass — `FakeMessages` mock captures kwargs, so tests that assert `sent["system"] == "sys"` will break and need updating.
- Cache prefix order is: `tools` → `system` → `messages`. Put `cache_control` on the last tool and the system block.

## Review Focus

1. **Plain string system prompts** — `health_check()` passes a short system prompt ("You are a connectivity probe.") that's well below 1,024 tokens. Caching it wastes the write premium. The implementation should still work (cache_control is a hint, not a requirement), but verify it doesn't error.
2. **LLMUsage cost calculation with cache tokens** — cache_creation_input_tokens are billed at 1.25× input, cache_read_input_tokens at 0.1× input. The `cost_usd()` method must account for these separately, not double-count with `input_tokens`.
3. **Mock response objects in tests** — existing `SimpleNamespace` mocks don't include `usage.cache_read_input_tokens`. Tests must handle missing cache fields gracefully (default to 0).
4. **Tool cache_control placement** — `cache_control` goes on the tool dict, not inside `input_schema`. The Anthropic SDK expects it at the top level of each tool object.
5. **Backward compatibility with non-Anthropic providers** — `LLMUsage` gains new fields with defaults; other providers that don't set them get 0 cost for cache lines.

---

### Task 1: Add cache token fields to LLMUsage and update cost calculation

**Files:**
- Modify: `tradingbot/core/llm/provider.py:17-30` (LLMUsage dataclass + cost_usd)
- Modify: `tests/core/llm/test_cost_tracking.py` (add cache cost tests)

**Interfaces:**
- Consumes: nothing
- Produces: `LLMUsage(input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, model)` — Task 2 uses `cache_read_tokens` and `cache_creation_tokens` fields.

- [ ] **Step 1: Write failing tests for cache token cost tracking**

```python
# In tests/core/llm/test_cost_tracking.py — add these tests

def test_llm_usage_cache_read_tokens_cost():
    usage = LLMUsage(
        input_tokens=500, output_tokens=100,
        cache_read_tokens=1000, cache_creation_tokens=0,
        model="claude-sonnet-4-20250514",
    )
    cost = usage.cost_usd()
    # 500 fresh input @ $3/M + 1000 cache read @ $0.30/M + 100 output @ $15/M
    expected = (500 * 3 / 1_000_000) + (1000 * 0.30 / 1_000_000) + (100 * 15 / 1_000_000)
    assert abs(cost - expected) < 0.0001


def test_llm_usage_cache_creation_tokens_cost():
    usage = LLMUsage(
        input_tokens=200, output_tokens=100,
        cache_read_tokens=0, cache_creation_tokens=800,
        model="claude-sonnet-4-20250514",
    )
    cost = usage.cost_usd()
    # 200 fresh input @ $3/M + 800 cache write @ $3.75/M + 100 output @ $15/M
    expected = (200 * 3 / 1_000_000) + (800 * 3.75 / 1_000_000) + (100 * 15 / 1_000_000)
    assert abs(cost - expected) < 0.0001


def test_llm_usage_defaults_cache_to_zero():
    usage = LLMUsage(input_tokens=100, output_tokens=50, model="claude-sonnet-4-20250514")
    # Should work without passing cache fields
    assert usage.cache_read_tokens == 0
    assert usage.cache_creation_tokens == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/core/llm/test_cost_tracking.py -v --tb=short`
Expected: FAIL — `LLMUsage` doesn't accept `cache_read_tokens` or `cache_creation_tokens`.

- [ ] **Step 3: Update LLMUsage dataclass and cost calculation**

```python
# In tradingbot/core/llm/provider.py — replace LLMUsage and pricing

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/core/llm/test_cost_tracking.py -v --tb=short`
Expected: All PASS (including existing tests — they don't pass cache fields, defaults to 0).

- [ ] **Step 5: Run full LLM test suite for regressions**

Run: `.venv/bin/python3 -m pytest tests/core/llm/ -v --tb=short`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add tradingbot/core/llm/provider.py tests/core/llm/test_cost_tracking.py
git commit -m "feat(llm): add cache token tracking to LLMUsage with per-model pricing"
```

---

### Task 2: Enable prompt caching in AnthropicProvider

**Files:**
- Modify: `tradingbot/core/llm/anthropic_provider.py:56-96` (analyze method)
- Modify: `tests/core/llm/test_anthropic_provider.py` (update system format assertions, add cache tests)

**Interfaces:**
- Consumes: `LLMUsage(cache_read_tokens=..., cache_creation_tokens=...)` from Task 1
- Produces: Anthropic API calls with `cache_control` on system and tool blocks. Response `usage` includes `cache_read_input_tokens` and `cache_creation_input_tokens`.

- [ ] **Step 1: Write failing tests for cached API call format**

```python
# In tests/core/llm/test_anthropic_provider.py — add these tests

async def test_analyze_sends_system_as_cached_block(tmp_path):
    resp = tool_use_response({"picks": []})
    resp.usage = SimpleNamespace(input_tokens=100, output_tokens=50,
                                 cache_read_input_tokens=0, cache_creation_input_tokens=80)
    client = make_client([resp])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)

    sent = client.messages.calls[0]
    # system must be array format with cache_control
    assert isinstance(sent["system"], list)
    assert sent["system"][0]["type"] == "text"
    assert sent["system"][0]["text"] == "sys"
    assert sent["system"][0]["cache_control"] == {"type": "ephemeral"}


async def test_analyze_sends_tool_with_cache_control(tmp_path):
    resp = tool_use_response({"picks": []})
    resp.usage = SimpleNamespace(input_tokens=100, output_tokens=50,
                                 cache_read_input_tokens=0, cache_creation_input_tokens=0)
    client = make_client([resp])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)

    sent = client.messages.calls[0]
    assert sent["tools"][0]["cache_control"] == {"type": "ephemeral"}


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/core/llm/test_anthropic_provider.py -v -k "cache" --tb=short`
Expected: FAIL — system is still a plain string, no cache_control on tools.

- [ ] **Step 3: Update analyze() to use cached system and tool format**

Replace lines 56-96 in `anthropic_provider.py`:

```python
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
            "cache_control": {"type": "ephemeral"},
        }

        system_blocks = [{
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }]

        attempts = self.config.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await self.client.messages.create(
                    model=self.config.model,
                    max_tokens=MAX_TOKENS,
                    system=system_blocks,
                    messages=[{"role": "user", "content": user_prompt}],
                    tools=[tool],
                )
            except Exception as exc:
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

            usage = getattr(response, "usage", None)
            payload["_usage"] = LLMUsage(
                input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
                output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) if usage else 0,
                cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) if usage else 0,
                model=self.config.model,
            )

            return payload

        assert last_error is not None
        raise last_error
```

- [ ] **Step 4: Update existing test that asserts system format**

The test `test_analyze_sends_the_configured_model_and_tool` at line 66 asserts `sent["system"] == "sys"`. Update it:

```python
async def test_analyze_sends_the_configured_model_and_tool(tmp_path):
    resp = tool_use_response({"picks": []})
    resp.usage = SimpleNamespace(input_tokens=0, output_tokens=0,
                                 cache_read_input_tokens=0, cache_creation_input_tokens=0)
    client = make_client([resp])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)

    sent = client.messages.calls[0]
    assert sent["model"] == "claude-sonnet-5"
    assert sent["system"][0]["text"] == "sys"
    assert sent["tools"][0]["name"] == "emit_result"
    assert sent["tools"][0]["input_schema"] == SCHEMA
    assert sent["messages"] == [{"role": "user", "content": "user"}]
```

Also add `usage` to `tool_use_response` helper so other tests don't break:

```python
def tool_use_response(payload, tool_name="emit_result"):
    block = SimpleNamespace(type="tool_use", name=tool_name, input=payload)
    usage = SimpleNamespace(input_tokens=0, output_tokens=0,
                            cache_read_input_tokens=0, cache_creation_input_tokens=0)
    return SimpleNamespace(content=[block], stop_reason="tool_use", usage=usage)
```

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python3 -m pytest tests/core/llm/ -v --tb=short`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add tradingbot/core/llm/anthropic_provider.py tests/core/llm/test_anthropic_provider.py
git commit -m "feat(llm): enable prompt caching on system prompts and tool schemas"
```
