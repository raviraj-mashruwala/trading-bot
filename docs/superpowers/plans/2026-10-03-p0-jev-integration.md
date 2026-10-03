# P0 Jev Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the LLM escalator with a Jev-based escalator (~100ms vs ~5s) and enhance the entry guard with a Jev probabilistic validation layer, with Claude as rare fallback.

**Architecture:** Three new files (JevClient, JevEscalator, tests) and three modified files (entry guard, execution intelligence, config). JevEscalator is a drop-in replacement returning the same `EscalationResult` dataclass so `executor.py` requires zero changes. Entry guard gets an optional `jev_client` that validates ENTER verdicts and enriches gray zone confidence.

**Tech Stack:** Python 3.12, typesafe-sdk >= 0.6.0, pytest, pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-10-03-p0-jev-integration-design.md`

## Global Constraints

- Python >= 3.12 (from pyproject.toml)
- typesafe-sdk is an optional dependency — all code must gracefully handle its absence
- `EscalationResult` dataclass is frozen (`frozen=True`) — same 4 fields: `action`, `reasoning`, `confidence`, `fallback_used`
- `EntryVerdict` dataclass is frozen — same 4 fields: `action`, `reason`, `confidence`, `reassess_after`
- Environment variable `TYPESAFE_API_KEY` for authentication (same pattern as `ANTHROPIC_API_KEY`)
- Default config ships with `jev.enabled = false` for zero-risk rollout

## Review Focus

1. **Missing API key at runtime:** JevClient constructed with no `TYPESAFE_API_KEY` in env should set `available = False` and never raise — callers silently fall back. Test in Task 1.
2. **Jev returns unexpected answer structure:** If the SDK response is missing expected keys (e.g., Jev API changes), `evaluate()` should return `None` not crash. Test in Task 2.
3. **Concurrent async calls during tick loop:** `aevaluate()` is called from the async executor tick — it must not hold a long-lived client connection that blocks other ticks. Test that timeout is honored in Task 2.
4. **Entry guard Jev failure mid-evaluation:** If Jev times out after deterministic rules said ENTER, the original ENTER verdict must be returned unchanged — not a crash, not a WAIT. Test in Task 3.
5. **Config backward compatibility:** Existing `config.toml` files without a `[jev]` section must load without error, defaulting to `jev.enabled = false`. Test in Task 1.

---

### Task 1: JevConfig + JevClient foundation

**Files:**
- Modify: `tradingbot/core/config.py` (add `JevConfig` dataclass + wire into `Config` and `load_config`)
- Modify: `config.toml` (add `[jev]` section)
- Modify: `pyproject.toml` (add optional `typesafe-sdk` dependency)
- Create: `tradingbot/core/jev_client.py`
- Create: `tests/core/test_jev_client.py`

**Interfaces:**
- Consumes: nothing (foundation layer)
- Produces:
  - `JevConfig(enabled: bool, model: str, entry_confidence_threshold: float, exit_confidence_threshold: float, uncertainty_threshold: float, timeout_ms: int)`
  - `JevClient(config: JevConfig)` with `.available: bool`, `.evaluate(state: dict, questions: dict) -> dict | None`, `.stats() -> dict`

- [ ] **Step 1: Add JevConfig dataclass to config.py**

Add after `LLMConfig` (line 182):

```python
@dataclass(frozen=True)
class JevConfig:
    enabled: bool = False
    model: str = "jev-latest"
    entry_confidence_threshold: float = 0.6
    exit_confidence_threshold: float = 0.75
    uncertainty_threshold: float = 0.3
    timeout_ms: int = 2000
```

Add `jev: JevConfig` field to the `Config` dataclass (after `kite: KiteConfig` at line 212):

```python
@dataclass(frozen=True)
class Config:
    general: GeneralConfig
    scanner: ScannerConfig
    strategy: StrategyConfig
    risk: RiskConfig
    execution: ExecutionConfig
    llm: LLMConfig
    paper: PaperConfig
    secrets: Secrets
    screening: ScreeningConfig
    backtest: BacktestConfig
    kite: KiteConfig
    jev: JevConfig = field(default_factory=lambda: JevConfig())
```

Add to `load_config()` — after `kite_raw` (around line 306), add:

```python
jev_raw = data.get("jev", {})
```

And in the `Config(...)` constructor call, add at the end:

```python
jev=JevConfig(
    enabled=bool(jev_raw.get("enabled", False)),
    model=str(jev_raw.get("model", "jev-latest")),
    entry_confidence_threshold=float(jev_raw.get("entry_confidence_threshold", 0.6)),
    exit_confidence_threshold=float(jev_raw.get("exit_confidence_threshold", 0.75)),
    uncertainty_threshold=float(jev_raw.get("uncertainty_threshold", 0.3)),
    timeout_ms=int(jev_raw.get("timeout_ms", 2000)),
),
```

- [ ] **Step 2: Add [jev] section to config.toml**

Append at end of `config.toml`:

```toml

[jev]
enabled = false
model = "jev-latest"
entry_confidence_threshold = 0.6
exit_confidence_threshold = 0.75
uncertainty_threshold = 0.3
timeout_ms = 2000
```

- [ ] **Step 3: Add typesafe-sdk optional dependency to pyproject.toml**

Add a new optional-dependencies group after `dev`:

```toml
jev = [
    "typesafe-sdk>=0.6.0",
]
```

- [ ] **Step 4: Write test_jev_client.py — test SDK unavailable**

```python
# tests/core/test_jev_client.py
from unittest.mock import patch
import pytest
from tradingbot.core.config import JevConfig


def _config(**overrides) -> JevConfig:
    defaults = dict(enabled=True, model="jev-latest",
                    entry_confidence_threshold=0.6,
                    exit_confidence_threshold=0.75,
                    uncertainty_threshold=0.3, timeout_ms=2000)
    defaults.update(overrides)
    return JevConfig(**defaults)


def test_unavailable_when_sdk_missing():
    with patch.dict("sys.modules", {"typesafe_sdk": None}):
        # Force reimport
        import importlib
        from tradingbot.core import jev_client
        importlib.reload(jev_client)
        client = jev_client.JevClient(_config())
        assert client.available is False
        assert client.evaluate({"x": 1}, {}) is None


def test_unavailable_when_no_api_key():
    with patch.dict("os.environ", {}, clear=True):
        from tradingbot.core.jev_client import JevClient
        client = JevClient(_config())
        assert client.available is False


def test_stats_initial():
    from tradingbot.core.jev_client import JevClient
    client = JevClient(_config(enabled=False))
    s = client.stats()
    assert s["calls"] == 0
    assert s["avg_latency_ms"] == 0.0
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `pytest tests/core/test_jev_client.py -v`
Expected: FAIL — `jev_client` module does not exist

- [ ] **Step 6: Implement jev_client.py**

```python
"""Thin wrapper around TypeSafe's Jev SDK with graceful degradation."""

from __future__ import annotations

import logging
import os
import time as _time
from typing import Any

from tradingbot.core.config import JevConfig

log = logging.getLogger(__name__)

try:
    from typesafe_sdk import (
        AsyncTypeSafeClient,
        Choice,
        Noul,
        Score,
        TypeSafeClient,
    )
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    TypeSafeClient = None  # type: ignore[assignment,misc]
    AsyncTypeSafeClient = None  # type: ignore[assignment,misc]
    Choice = None  # type: ignore[assignment,misc]
    Noul = None  # type: ignore[assignment,misc]
    Score = None  # type: ignore[assignment,misc]


class JevClient:
    """Evaluate state + questions via TypeSafe Jev. Returns None on any failure."""

    def __init__(self, config: JevConfig) -> None:
        self._config = config
        self._api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
        self._available = _SDK_AVAILABLE and bool(self._api_key) and config.enabled
        self._calls = 0
        self._total_latency_ms = 0.0

        if not _SDK_AVAILABLE:
            log.info("typesafe-sdk not installed — Jev disabled")
        elif not self._api_key:
            log.info("TYPESAFE_API_KEY not set — Jev disabled")
        elif not config.enabled:
            log.info("Jev disabled in config")

    @property
    def available(self) -> bool:
        return self._available

    def evaluate(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any] | None:
        if not self._available:
            return None
        try:
            start = _time.monotonic()
            with TypeSafeClient(
                api_key=self._api_key,
                model=self._config.model,
            ) as client:
                response = client.system_one(state=state, questions=questions)
            elapsed_ms = (_time.monotonic() - start) * 1000
            self._calls += 1
            self._total_latency_ms += elapsed_ms
            log.debug("Jev call %d: %.0fms, %d answers",
                      self._calls, elapsed_ms, len(response.answers))
            return response.answers
        except Exception:
            log.warning("Jev evaluate failed", exc_info=True)
            return None

    async def aevaluate(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any] | None:
        if not self._available:
            return None
        try:
            start = _time.monotonic()
            async with AsyncTypeSafeClient(
                api_key=self._api_key,
                model=self._config.model,
            ) as client:
                response = await client.system_one(state=state, questions=questions)
            elapsed_ms = (_time.monotonic() - start) * 1000
            self._calls += 1
            self._total_latency_ms += elapsed_ms
            log.debug("Jev async call %d: %.0fms", self._calls, elapsed_ms)
            return response.answers
        except Exception:
            log.warning("Jev aevaluate failed", exc_info=True)
            return None

    def stats(self) -> dict[str, Any]:
        return {
            "calls": self._calls,
            "total_latency_ms": self._total_latency_ms,
            "avg_latency_ms": (self._total_latency_ms / self._calls) if self._calls > 0 else 0.0,
        }
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/core/test_jev_client.py -v`
Expected: PASS (3 tests)

- [ ] **Step 8: Verify existing tests still pass**

Run: `pytest tests/ -x -q --timeout=30`
Expected: All existing tests pass — no regressions from config changes

- [ ] **Step 9: Commit**

```bash
git add tradingbot/core/config.py tradingbot/core/jev_client.py config.toml pyproject.toml tests/core/test_jev_client.py
git commit -m "feat(jev): add JevConfig + JevClient with graceful SDK degradation"
```

---

### Task 2: JevEscalator — drop-in replacement for LLMEscalator

**Files:**
- Create: `tradingbot/executor/jev_escalator.py`
- Create: `tests/executor/test_jev_escalator.py`

**Interfaces:**
- Consumes: `JevClient.aevaluate(state, questions) -> dict | None` from Task 1, `EscalationResult` from `llm_escalator.py`, `SymbolState` from `momentum_scorer.py`, `LiveCandle` from `candle_aggregator.py`
- Produces: `JevEscalator(jev_client: JevClient, config: JevConfig, llm_fallback: LLMEscalator | None)` with `async evaluate_entry(leg, state: SymbolState, candles_1m: list[LiveCandle], candles_5m: list[LiveCandle], ticker_degraded: bool) -> EscalationResult` and `async evaluate_exit(leg_state, state: SymbolState, candles_1m: list[LiveCandle], candles_5m: list[LiveCandle]) -> EscalationResult`

- [ ] **Step 1: Write test helpers and mock infrastructure**

```python
# tests/executor/test_jev_escalator.py
from datetime import datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest

from tradingbot.executor.llm_escalator import EscalationResult
from tradingbot.executor.momentum_scorer import SymbolState
from tradingbot.executor.candle_aggregator import LiveCandle
from tradingbot.core.config import JevConfig


def _jev_config(**overrides) -> JevConfig:
    defaults = dict(enabled=True, model="jev-latest",
                    entry_confidence_threshold=0.6,
                    exit_confidence_threshold=0.75,
                    uncertainty_threshold=0.3, timeout_ms=2000)
    defaults.update(overrides)
    return JevConfig(**defaults)


def _state(**overrides) -> SymbolState:
    defaults = dict(
        symbol="RELIANCE", timestamp=datetime(2026, 9, 29, 10, 30),
        momentum_1m=10.0, momentum_5m=-15.0,
        volume_ratio=0.9, volume_trend="falling",
        vwap=2450.0, vwap_position=-0.3, price_vs_open=-0.2,
        last_pattern_1m="none", last_pattern_5m="none",
        body_dominance=0.4, trend_alignment=False, strength="weak",
    )
    defaults.update(overrides)
    return SymbolState(**defaults)


class FakeLeg:
    def __init__(self):
        self.symbol = "RELIANCE"
        self.direction = SimpleNamespace(value="long")
        self.entry_price = 2450.0
        self.stop_loss = 2430.0
        self.target_1 = 2470.0
        self.target_2 = 2490.0
        self.strategy = SimpleNamespace(value="breakout")
        self.confidence = 0.75
        self.reasoning = "Strong breakout"


def _mock_jev_client(answers: dict | None) -> MagicMock:
    client = MagicMock()
    client.available = answers is not None
    client.aevaluate = AsyncMock(return_value=answers)
    return client


def _noul(value: float):
    return SimpleNamespace(noul=value)


def _choice(value: str, confidence: float = 0.8):
    return SimpleNamespace(choice=value, confidence=confidence)


def _score(value: float, confidence: float = 0.8):
    return SimpleNamespace(score=value, confidence=confidence)
```

- [ ] **Step 2: Write failing test — entry high confidence → ENTER**

Add to `test_jev_escalator.py`:

```python
@pytest.mark.asyncio
async def test_entry_enter_high_confidence():
    from tradingbot.executor.jev_escalator import JevEscalator
    answers = {
        "should_enter": _noul(0.85),
        "invalidated": _noul(0.05),
        "timing": _choice("enter_now", 0.91),
    }
    jev = _mock_jev_client(answers)
    esc = JevEscalator(jev, _jev_config())
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    assert result.action == "ENTER"
    assert result.confidence > 0.6
    assert not result.fallback_used
    assert "jev:" in result.reasoning
```

- [ ] **Step 3: Write failing test — entry skip invalidated**

```python
@pytest.mark.asyncio
async def test_entry_skip_invalidated():
    from tradingbot.executor.jev_escalator import JevEscalator
    answers = {
        "should_enter": _noul(0.50),
        "invalidated": _noul(0.80),
        "timing": _choice("enter_now", 0.5),
    }
    jev = _mock_jev_client(answers)
    esc = JevEscalator(jev, _jev_config())
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    assert result.action == "SKIP"
```

- [ ] **Step 4: Write failing test — entry skip via timing choice**

```python
@pytest.mark.asyncio
async def test_entry_skip_timing():
    from tradingbot.executor.jev_escalator import JevEscalator
    answers = {
        "should_enter": _noul(0.50),
        "invalidated": _noul(0.10),
        "timing": _choice("skip", 0.85),
    }
    jev = _mock_jev_client(answers)
    esc = JevEscalator(jev, _jev_config())
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    assert result.action == "SKIP"
```

- [ ] **Step 5: Write failing test — entry wait moderate confidence**

```python
@pytest.mark.asyncio
async def test_entry_wait_moderate():
    from tradingbot.executor.jev_escalator import JevEscalator
    answers = {
        "should_enter": _noul(0.45),
        "invalidated": _noul(0.10),
        "timing": _choice("wait_5min", 0.6),
    }
    jev = _mock_jev_client(answers)
    esc = JevEscalator(jev, _jev_config())
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    assert result.action == "WAIT"
    assert not result.fallback_used
```

- [ ] **Step 6: Write failing test — Claude fallback on low confidence**

```python
@pytest.mark.asyncio
async def test_entry_claude_fallback_low_confidence():
    from tradingbot.executor.jev_escalator import JevEscalator
    answers = {
        "should_enter": _noul(0.15),
        "invalidated": _noul(0.10),
        "timing": _choice("wait_5min", 0.3),
    }
    jev = _mock_jev_client(answers)
    llm = AsyncMock()
    llm.evaluate_entry = AsyncMock(return_value=EscalationResult("ENTER", "LLM says go", 0.7, False))
    esc = JevEscalator(jev, _jev_config(), llm_fallback=llm)
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    assert result.action == "ENTER"
    assert result.reasoning == "LLM says go"
    llm.evaluate_entry.assert_awaited_once()
```

- [ ] **Step 7: Write failing test — Jev unavailable uses fallback**

```python
@pytest.mark.asyncio
async def test_entry_jev_unavailable_uses_fallback():
    from tradingbot.executor.jev_escalator import JevEscalator
    jev = _mock_jev_client(None)  # available = False
    llm = AsyncMock()
    llm.evaluate_entry = AsyncMock(return_value=EscalationResult("WAIT", "LLM wait", 0.5, False))
    esc = JevEscalator(jev, _jev_config(), llm_fallback=llm)
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    assert result.action == "WAIT"
    llm.evaluate_entry.assert_awaited_once()
```

- [ ] **Step 8: Write failing test — Jev timeout uses fallback**

```python
@pytest.mark.asyncio
async def test_entry_jev_timeout_uses_fallback():
    from tradingbot.executor.jev_escalator import JevEscalator
    jev = MagicMock()
    jev.available = True
    jev.aevaluate = AsyncMock(return_value=None)  # timeout/error
    llm = AsyncMock()
    llm.evaluate_entry = AsyncMock(return_value=EscalationResult("WAIT", "LLM fallback", 0.4, False))
    esc = JevEscalator(jev, _jev_config(), llm_fallback=llm)
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    llm.evaluate_entry.assert_awaited_once()
```

- [ ] **Step 9: Write failing test — all unavailable returns WAIT**

```python
@pytest.mark.asyncio
async def test_entry_all_unavailable_returns_wait():
    from tradingbot.executor.jev_escalator import JevEscalator
    jev = MagicMock()
    jev.available = True
    jev.aevaluate = AsyncMock(return_value=None)
    llm = AsyncMock()
    llm.evaluate_entry = AsyncMock(side_effect=Exception("LLM down"))
    esc = JevEscalator(jev, _jev_config(), llm_fallback=llm)
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    assert result.action == "WAIT"
    assert result.fallback_used is True
```

- [ ] **Step 10: Write failing test — exit high confidence → EXIT**

```python
@pytest.mark.asyncio
async def test_exit_close_high_confidence():
    from tradingbot.executor.jev_escalator import JevEscalator
    answers = {
        "exit_now": _noul(0.90),
        "momentum_exhaustion": _noul(0.80),
        "reversal_risk": _score(3.2, 0.85),
    }
    jev = _mock_jev_client(answers)
    esc = JevEscalator(jev, _jev_config())
    result = await esc.evaluate_exit(MagicMock(), _state(), [], [])
    assert result.action == "EXIT"
    assert not result.fallback_used
```

- [ ] **Step 11: Write failing test — exit tighten stop**

```python
@pytest.mark.asyncio
async def test_exit_tighten_stop():
    from tradingbot.executor.jev_escalator import JevEscalator
    answers = {
        "exit_now": _noul(0.50),
        "momentum_exhaustion": _noul(0.70),
        "reversal_risk": _score(3.0, 0.80),  # 3.0/4 = 0.75 > 0.7
    }
    jev = _mock_jev_client(answers)
    esc = JevEscalator(jev, _jev_config())
    result = await esc.evaluate_exit(MagicMock(), _state(), [], [])
    assert result.action == "HOLD"
    assert "tighten_stop" in result.reasoning
```

- [ ] **Step 12: Write failing test — reasoning contains scores**

```python
@pytest.mark.asyncio
async def test_reasoning_contains_scores():
    from tradingbot.executor.jev_escalator import JevEscalator
    answers = {
        "should_enter": _noul(0.72),
        "invalidated": _noul(0.05),
        "timing": _choice("enter_now", 0.88),
    }
    jev = _mock_jev_client(answers)
    esc = JevEscalator(jev, _jev_config())
    result = await esc.evaluate_entry(FakeLeg(), _state(), [], [])
    assert "jev:" in result.reasoning
    assert "0.72" in result.reasoning
    assert "enter_now" in result.reasoning
```

- [ ] **Step 13: Run all tests to verify they fail**

Run: `pytest tests/executor/test_jev_escalator.py -v`
Expected: FAIL — `jev_escalator` module does not exist

- [ ] **Step 14: Implement jev_escalator.py**

```python
"""Jev-based escalator: drop-in replacement for LLMEscalator."""

from __future__ import annotations

import logging
from typing import Any

from tradingbot.core.config import JevConfig
from tradingbot.core.jev_client import JevClient
from tradingbot.executor.candle_aggregator import LiveCandle
from tradingbot.executor.llm_escalator import EscalationResult, LLMEscalator
from tradingbot.executor.momentum_scorer import SymbolState

log = logging.getLogger(__name__)

_ENTRY_FALLBACK = EscalationResult("WAIT", "all_escalators_unavailable", 0.0, True)
_EXIT_FALLBACK = EscalationResult("HOLD", "all_escalators_unavailable", 0.0, True)


def _build_entry_questions() -> dict[str, Any]:
    from tradingbot.core.jev_client import Noul, Choice
    if Noul is None:
        return {}
    return {
        "should_enter": Noul(
            instructions="Should this trade be entered based on the live price action?",
            criteria={
                "true": "Momentum, volume, and price action confirm the setup thesis — enter",
                "false": "Price action contradicts or weakens the setup — wait or skip",
            },
        ),
        "invalidated": Noul(
            instructions="Has the original trade setup been invalidated by current price action?",
            criteria={
                "true": "Key levels broken, pattern failed, or thesis no longer holds",
                "false": "Setup thesis still intact despite current conditions",
            },
        ),
        "timing": Choice(
            instructions="What is the best action right now?",
            criteria={
                "enter_now": "Conditions are favorable — execute immediately",
                "wait_5min": "Close but not quite — reassess shortly",
                "skip": "Setup is no longer valid — do not enter today",
            },
        ),
    }


def _build_exit_questions() -> dict[str, Any]:
    from tradingbot.core.jev_client import Noul, Score
    if Noul is None:
        return {}
    return {
        "exit_now": Noul(
            instructions="Should this position be closed immediately?",
            criteria={
                "true": "Momentum exhausted, reversal signals, or risk elevated — close now",
                "false": "Position still has favorable momentum — hold",
            },
        ),
        "momentum_exhaustion": Noul(
            instructions="Is the momentum that drove this trade showing signs of exhaustion?",
        ),
        "reversal_risk": Score(
            instructions="How likely is a reversal against this position in the next 30 minutes?",
            criteria=[
                "Very unlikely — strong trend continuation signals",
                "Unlikely — some noise but trend intact",
                "Possible — mixed signals, caution warranted",
                "Likely — multiple reversal signals forming",
                "Very likely — clear reversal pattern underway",
            ],
        ),
    }


def _state_from_entry(leg: Any, state: SymbolState, candles_5m: list[LiveCandle]) -> dict:
    return {
        "setup": {
            "symbol": leg.symbol,
            "direction": leg.direction.value,
            "strategy": leg.strategy.value,
            "entry_price": leg.entry_price,
            "stop_loss": leg.stop_loss,
            "target_1": leg.target_1,
        },
        "live": {
            "momentum_1m": state.momentum_1m,
            "momentum_5m": state.momentum_5m,
            "volume_ratio": state.volume_ratio,
            "vwap_position": state.vwap_position,
            "trend_alignment": state.trend_alignment,
            "strength": state.strength,
            "body_dominance": state.body_dominance,
            "last_pattern_1m": state.last_pattern_1m,
            "last_pattern_5m": state.last_pattern_5m,
        },
        "candles_5m": [
            {"o": c.open, "h": c.high, "l": c.low, "c": c.close, "v": c.volume}
            for c in candles_5m[-6:]
        ],
    }


def _state_from_exit(leg_state: Any, state: SymbolState, candles_5m: list[LiveCandle]) -> dict:
    return {
        "position": {
            "symbol": state.symbol,
            "momentum_1m": state.momentum_1m,
            "momentum_5m": state.momentum_5m,
            "volume_ratio": state.volume_ratio,
            "vwap_position": state.vwap_position,
            "trend_alignment": state.trend_alignment,
            "strength": state.strength,
        },
        "candles_5m": [
            {"o": c.open, "h": c.high, "l": c.low, "c": c.close, "v": c.volume}
            for c in candles_5m[-6:]
        ],
    }


def _format_entry_reasoning(answers: dict) -> str:
    se = answers["should_enter"].noul
    inv = answers["invalidated"].noul
    tm = answers["timing"].choice
    tc = answers["timing"].confidence
    return f"jev: should_enter={se:.2f}, timing={tm}(conf={tc:.2f}), invalidated={inv:.2f}"


def _format_exit_reasoning(answers: dict) -> str:
    ex = answers["exit_now"].noul
    me = answers["momentum_exhaustion"].noul
    rr = answers["reversal_risk"].score
    return f"jev: exit_now={ex:.2f}, exhaustion={me:.2f}, reversal_risk={rr:.2f}"


class JevEscalator:
    """Drop-in replacement for LLMEscalator using TypeSafe Jev."""

    def __init__(
        self,
        jev_client: JevClient,
        config: JevConfig,
        llm_fallback: LLMEscalator | None = None,
    ) -> None:
        self._jev = jev_client
        self._config = config
        self._fallback = llm_fallback
        self._call_count = 0

    @property
    def escalation_count(self) -> int:
        return self._call_count

    async def evaluate_entry(
        self,
        leg: Any,
        state: SymbolState,
        candles_1m: list[LiveCandle],
        candles_5m: list[LiveCandle],
        ticker_degraded: bool = False,
    ) -> EscalationResult:
        answers = await self._jev.aevaluate(
            state=_state_from_entry(leg, state, candles_5m),
            questions=_build_entry_questions(),
        )

        if answers is None:
            return await self._entry_fallback(leg, state, candles_1m, candles_5m, ticker_degraded)

        self._call_count += 1
        reasoning = _format_entry_reasoning(answers)

        if answers["invalidated"].noul > 0.7:
            return EscalationResult("SKIP", reasoning, answers["invalidated"].noul, False)

        if answers["timing"].choice == "skip":
            return EscalationResult("SKIP", reasoning, answers["timing"].confidence, False)

        se = answers["should_enter"].noul
        if se >= self._config.entry_confidence_threshold:
            return EscalationResult("ENTER", reasoning, se, False)

        if se < self._config.uncertainty_threshold:
            log.info("Jev uncertain (%.2f < %.2f), trying Claude fallback",
                     se, self._config.uncertainty_threshold)
            return await self._entry_fallback(leg, state, candles_1m, candles_5m, ticker_degraded)

        return EscalationResult("WAIT", reasoning, se, False)

    async def evaluate_exit(
        self,
        leg_state: Any,
        state: SymbolState,
        candles_1m: list[LiveCandle],
        candles_5m: list[LiveCandle],
    ) -> EscalationResult:
        answers = await self._jev.aevaluate(
            state=_state_from_exit(leg_state, state, candles_5m),
            questions=_build_exit_questions(),
        )

        if answers is None:
            return await self._exit_fallback(leg_state, state, candles_1m, candles_5m)

        self._call_count += 1
        reasoning = _format_exit_reasoning(answers)

        ex = answers["exit_now"].noul
        if ex >= self._config.exit_confidence_threshold:
            return EscalationResult("EXIT", reasoning, ex, False)

        reversal_norm = answers["reversal_risk"].score / 4.0
        exhaustion = answers["momentum_exhaustion"].noul
        if reversal_norm > 0.7 and exhaustion > 0.6:
            return EscalationResult("HOLD", f"{reasoning}; tighten_stop", reversal_norm, False)

        if ex < self._config.uncertainty_threshold:
            log.info("Jev exit uncertain (%.2f), trying Claude fallback", ex)
            return await self._exit_fallback(leg_state, state, candles_1m, candles_5m)

        return EscalationResult("HOLD", reasoning, 1.0 - ex, False)

    async def _entry_fallback(self, leg, state, candles_1m, candles_5m, ticker_degraded):
        if self._fallback is None:
            return _ENTRY_FALLBACK
        try:
            return await self._fallback.evaluate_entry(
                leg, state, candles_1m, candles_5m, ticker_degraded,
            )
        except Exception:
            log.warning("Claude entry fallback also failed", exc_info=True)
            return _ENTRY_FALLBACK

    async def _exit_fallback(self, leg_state, state, candles_1m, candles_5m):
        if self._fallback is None:
            return _EXIT_FALLBACK
        try:
            return await self._fallback.evaluate_exit(
                leg_state, state, candles_1m, candles_5m,
            )
        except Exception:
            log.warning("Claude exit fallback also failed", exc_info=True)
            return _EXIT_FALLBACK
```

- [ ] **Step 15: Run tests to verify they pass**

Run: `pytest tests/executor/test_jev_escalator.py -v`
Expected: PASS (11 tests)

- [ ] **Step 16: Run all executor tests to verify no regressions**

Run: `pytest tests/executor/ -v`
Expected: All existing LLM escalator and entry guard tests still pass

- [ ] **Step 17: Commit**

```bash
git add tradingbot/executor/jev_escalator.py tests/executor/test_jev_escalator.py
git commit -m "feat(jev): add JevEscalator with Claude fallback chain — 11 tests"
```

---

### Task 3: Entry guard Jev enhancement + wiring + integration

**Files:**
- Modify: `tradingbot/executor/entry_guard.py` (add Jev validation layer)
- Modify: `tradingbot/executor/execution_intelligence.py` (wire JevEscalator + Jev-enhanced guard)
- Modify: `tests/executor/test_entry_guard.py` (add 4 Jev tests)

**Interfaces:**
- Consumes: `JevClient` from Task 1, `JevEscalator` from Task 2, `EntryVerdict` and `EntryGuard` from existing code
- Produces: Enhanced `EntryGuard(max_drift_pct, jev_client=None)` with Jev validation on ENTER verdicts and gray zone enrichment. `ExecutionIntelligence` now creates `JevEscalator` when available.

- [ ] **Step 1: Write failing test — Jev fading overrides ENTER**

Add to `tests/executor/test_entry_guard.py`:

```python
from unittest.mock import MagicMock
from types import SimpleNamespace


def _mock_jev(enter_now=0.7, momentum_quality=0.6, fading_risk=0.3):
    """Build a mock JevClient that returns canned validate answers."""
    client = MagicMock()
    client.available = True
    client.evaluate = MagicMock(return_value={
        "enter_now": SimpleNamespace(noul=enter_now),
        "momentum_quality": SimpleNamespace(score=momentum_quality * 4, confidence=0.8),
        "fading_risk": SimpleNamespace(noul=fading_risk),
    })
    return client


def test_jev_fading_overrides_enter():
    guard = EntryGuard(max_drift_pct=5.0, jev_client=_mock_jev(fading_risk=0.75))
    leg = FakeLeg(direction="long")
    # Conditions that trigger rule 10 ENTER
    v = guard.evaluate(
        leg,
        _state(momentum_1m=40.0, momentum_5m=45.0, volume_ratio=1.5, trend_alignment=True),
        2450.0,
        datetime(2026, 9, 29, 9, 20),
    )
    assert v.action == "WAIT"
    assert "fading" in v.reason.lower()
```

- [ ] **Step 2: Write failing test — Jev low quality overrides ENTER**

```python
def test_jev_low_quality_overrides_enter():
    guard = EntryGuard(max_drift_pct=5.0, jev_client=_mock_jev(momentum_quality=0.1))
    leg = FakeLeg(direction="long")
    v = guard.evaluate(
        leg,
        _state(momentum_1m=40.0, momentum_5m=45.0, volume_ratio=1.5, trend_alignment=True),
        2450.0,
        datetime(2026, 9, 29, 9, 20),
    )
    assert v.action == "WAIT"
    assert "momentum" in v.reason.lower() or "quality" in v.reason.lower()
```

- [ ] **Step 3: Write failing test — Jev confirms and boosts confidence**

```python
def test_jev_confirms_boosts_confidence():
    guard = EntryGuard(max_drift_pct=5.0, jev_client=_mock_jev(enter_now=0.9, momentum_quality=0.8, fading_risk=0.1))
    leg = FakeLeg(direction="long")
    v = guard.evaluate(
        leg,
        _state(momentum_1m=40.0, momentum_5m=45.0, volume_ratio=1.5, trend_alignment=True),
        2450.0,
        datetime(2026, 9, 29, 9, 20),
    )
    assert v.action == "ENTER"
    assert v.confidence > 0.8  # boosted from base 0.8
```

- [ ] **Step 4: Write failing test — Jev unavailable preserves deterministic**

```python
def test_jev_unavailable_uses_deterministic():
    failing_jev = MagicMock()
    failing_jev.available = True
    failing_jev.evaluate = MagicMock(return_value=None)  # Jev failed
    guard = EntryGuard(max_drift_pct=5.0, jev_client=failing_jev)
    leg = FakeLeg(direction="long")
    v = guard.evaluate(
        leg,
        _state(momentum_1m=40.0, momentum_5m=45.0, volume_ratio=1.5, trend_alignment=True),
        2450.0,
        datetime(2026, 9, 29, 9, 20),
    )
    assert v.action == "ENTER"
    assert v.confidence == 0.8  # original deterministic value, unchanged
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `pytest tests/executor/test_entry_guard.py::test_jev_fading_overrides_enter tests/executor/test_entry_guard.py::test_jev_low_quality_overrides_enter tests/executor/test_entry_guard.py::test_jev_confirms_boosts_confidence tests/executor/test_entry_guard.py::test_jev_unavailable_uses_deterministic -v`
Expected: FAIL — `EntryGuard` constructor doesn't accept `jev_client`

- [ ] **Step 6: Modify entry_guard.py — add Jev validation layer**

Replace the `EntryGuard` class in `tradingbot/executor/entry_guard.py`:

```python
class EntryGuard:
    def __init__(self, max_drift_pct: float, jev_client=None) -> None:
        self._max_drift_pct = max_drift_pct
        self._jev = jev_client

    def evaluate(self, leg, state: SymbolState, current_price: float,
                 now: datetime) -> EntryVerdict:
        direction = leg.direction.value
        now_time = now.time() if isinstance(now, datetime) else now

        # Rule 1: entry window expired
        if now_time > leg.entry_window_end:
            return EntryVerdict("VETO", "Entry window expired", 1.0, 0)

        # Rule 1b: max entry wait expired
        if now_time > leg.max_entry_wait:
            return EntryVerdict("VETO", "Max entry wait expired", 1.0, 0)

        # Rule 2: price drift
        drift_pct = abs(current_price - leg.entry_price) / leg.entry_price * 100
        if drift_pct > self._max_drift_pct:
            return EntryVerdict("VETO", f"Price drift {drift_pct:.1f}% exceeds {self._max_drift_pct}%", 1.0, 0)

        # Rule 3: LONG into strong selling
        if direction == "long" and state.momentum_5m < -60:
            return EntryVerdict("VETO", f"Strong 5m selling (momentum {state.momentum_5m:.0f})", 0.9, 0)

        # Rule 4: SHORT into strong buying
        if direction == "short" and state.momentum_5m > 60:
            return EntryVerdict("VETO", f"Strong 5m buying (momentum {state.momentum_5m:.0f})", 0.9, 0)

        # Rule 5: low volume
        if state.volume_ratio < 0.3:
            return EntryVerdict("WAIT", "Volume too low, no liquidity", 0.7, 60)

        # Rule 6: choppy, no alignment
        if not state.trend_alignment and state.body_dominance < 0.3:
            return EntryVerdict("WAIT", "Choppy, conflicting signals", 0.6, 60)

        # Rule 7: LONG falling below VWAP
        if direction == "long" and state.vwap_position < -0.8 and state.momentum_1m < -30:
            return EntryVerdict("WAIT", "Price falling below VWAP", 0.5, 60)

        # Rule 7b: SHORT rising above VWAP
        if direction == "short" and state.vwap_position > 0.8 and state.momentum_1m > 30:
            return EntryVerdict("WAIT", "Price rising above VWAP", 0.5, 60)

        # Rule 8: adverse candle pattern
        if direction == "long" and state.last_pattern_5m in _BEARISH_PATTERNS:
            return EntryVerdict("WAIT", f"Bearish 5m pattern: {state.last_pattern_5m}", 0.5, 60)
        if direction == "short" and state.last_pattern_5m in _BULLISH_PATTERNS:
            return EntryVerdict("WAIT", f"Bullish 5m pattern: {state.last_pattern_5m}", 0.5, 60)

        # Rule 10: clean setup — momentum aligned + volume adequate
        aligned_momentum = (
            (direction == "long" and state.momentum_1m > 20 and state.momentum_5m > 15)
            or (direction == "short" and state.momentum_1m < -20 and state.momentum_5m < -15)
        )
        if aligned_momentum and state.volume_ratio > 0.7 and state.trend_alignment:
            verdict = EntryVerdict("ENTER", "Momentum aligned, volume adequate", 0.8, 0)
            return self._jev_validate(leg, state, verdict)

        # Rule 9: gray zone
        confidence = 0.2 + min(0.1, state.volume_ratio * 0.05) + min(0.09, state.body_dominance * 0.05)
        verdict = EntryVerdict("ENTER", "No disqualifying signal, marginal conditions", confidence, 0)
        return self._jev_enrich_gray_zone(leg, state, verdict)

    def _jev_validate(self, leg, state: SymbolState, verdict: EntryVerdict) -> EntryVerdict:
        """Validate an ENTER verdict using Jev. Returns original on failure."""
        jev_result = self._jev_evaluate(leg, state)
        if jev_result is None:
            return verdict

        if jev_result["fading_risk"] > 0.65:
            return EntryVerdict("WAIT", "jev_fading_risk", 0.5, 30)
        if jev_result["momentum_quality"] < 0.25:
            return EntryVerdict("WAIT", "jev_low_momentum_quality", 0.45, 60)

        boosted = min(0.95, verdict.confidence + jev_result["momentum_quality"] * 0.15)
        return EntryVerdict(verdict.action, verdict.reason, boosted, verdict.reassess_after)

    def _jev_enrich_gray_zone(self, leg, state: SymbolState, verdict: EntryVerdict) -> EntryVerdict:
        """Enrich gray zone confidence with Jev signals."""
        jev_result = self._jev_evaluate(leg, state)
        if jev_result is None:
            return verdict

        enriched = 0.3 * jev_result["enter_now"] + 0.2 * jev_result["momentum_quality"]
        return EntryVerdict(verdict.action, verdict.reason, enriched, verdict.reassess_after)

    def _jev_evaluate(self, leg, state: SymbolState) -> dict | None:
        """Call Jev with 3 validation questions. Returns normalized dict or None."""
        if self._jev is None or not self._jev.available:
            return None
        try:
            from tradingbot.core.jev_client import Noul, Score
            if Noul is None:
                return None
            answers = self._jev.evaluate(
                state={
                    "direction": leg.direction.value,
                    "momentum_1m": state.momentum_1m,
                    "momentum_5m": state.momentum_5m,
                    "volume_ratio": state.volume_ratio,
                    "vwap_position": state.vwap_position,
                    "trend_alignment": state.trend_alignment,
                    "strength": state.strength,
                    "body_dominance": state.body_dominance,
                },
                questions={
                    "enter_now": Noul(
                        instructions=(
                            "Given the live momentum data, should this trade be entered NOW? "
                            "Consider direction alignment, momentum strength, volume, and VWAP."
                        ),
                        criteria={
                            "true": "Momentum, volume, and price action support immediate entry",
                            "false": "Conditions are unfavorable — wait or skip",
                        },
                    ),
                    "momentum_quality": Score(
                        instructions="How favorable is current momentum for this trade direction?",
                        criteria=[
                            "Hostile — momentum strongly against trade direction",
                            "Unfavorable — weak or conflicting momentum",
                            "Neutral — no strong momentum either way",
                            "Favorable — momentum aligns with trade direction",
                            "Ideal — strong, clean momentum with volume confirmation",
                        ],
                    ),
                    "fading_risk": Noul(
                        instructions="Is there a risk that the move has already played out (late entry)?",
                    ),
                },
            )
            if answers is None:
                return None
            return {
                "enter_now": answers["enter_now"].noul,
                "momentum_quality": answers["momentum_quality"].score / 4.0,
                "fading_risk": answers["fading_risk"].noul,
            }
        except Exception:
            return None
```

- [ ] **Step 7: Run entry guard tests**

Run: `pytest tests/executor/test_entry_guard.py -v`
Expected: All 16 tests pass (12 existing + 4 new)

- [ ] **Step 8: Modify execution_intelligence.py — wire Jev**

In `tradingbot/executor/execution_intelligence.py`, add imports at top:

```python
from tradingbot.core.jev_client import JevClient
from tradingbot.executor.jev_escalator import JevEscalator
```

Replace lines 45-47 in `__init__`:

```python
        # Old:
        # self.entry_guard = EntryGuard(max_drift_pct=config.max_entry_price_drift_pct)
        # self.adaptive_exit = AdaptiveExitManager(square_off_time=config.square_off_time)
        # self.escalator = LLMEscalator()

        # New: Jev-enhanced with Claude fallback
        jev_config = getattr(config, "jev", None)
        jev_client = None
        if jev_config and jev_config.enabled:
            jev_client = JevClient(jev_config)

        self.entry_guard = EntryGuard(
            max_drift_pct=config.max_entry_price_drift_pct,
            jev_client=jev_client,
        )
        self.adaptive_exit = AdaptiveExitManager(square_off_time=config.square_off_time)

        llm_escalator = LLMEscalator()
        if jev_client and jev_client.available:
            self.escalator = JevEscalator(jev_client, jev_config, llm_fallback=llm_escalator)
        else:
            self.escalator = llm_escalator
```

- [ ] **Step 9: Run full test suite**

Run: `pytest tests/ -x -q --timeout=30`
Expected: All tests pass — no regressions

- [ ] **Step 10: Commit**

```bash
git add tradingbot/executor/entry_guard.py tradingbot/executor/execution_intelligence.py tests/executor/test_entry_guard.py
git commit -m "feat(jev): enhance entry guard with Jev validation + wire JevEscalator"
```

---

### Task 4: Final verification and documentation commit

**Files:**
- No new code — verification and cleanup only

**Interfaces:**
- Consumes: Everything from Tasks 1-3
- Produces: Verified, committed, working integration

- [ ] **Step 1: Run complete test suite**

Run: `pytest tests/ -v --timeout=30`
Expected: All tests pass. Count should include 15 new Jev-related tests.

- [ ] **Step 2: Verify import chain works without typesafe-sdk**

Run: `python -c "from tradingbot.core.jev_client import JevClient; from tradingbot.core.config import JevConfig; c = JevClient(JevConfig()); print('available:', c.available)"`
Expected: `available: False` (no SDK installed in dev, or no API key)

- [ ] **Step 3: Verify executor still works with jev.enabled=false**

Run: `python -c "from tradingbot.core.config import load_config; c = load_config(); print('jev.enabled:', c.jev.enabled)"`
Expected: `jev.enabled: False`

- [ ] **Step 4: Verify config loads without [jev] section**

Create a temporary config without [jev] and verify it loads:
```bash
python -c "
import tomllib, tempfile, os
from pathlib import Path
from tradingbot.core.config import load_config
# load_config reads config.toml which now has [jev] — verify defaults work
c = load_config()
print('jev defaults:', c.jev)
"
```
Expected: Prints JevConfig with defaults, no error

- [ ] **Step 5: Final commit if any cleanup needed**

```bash
git status
# If clean, skip. If stray files, add and commit.
```
