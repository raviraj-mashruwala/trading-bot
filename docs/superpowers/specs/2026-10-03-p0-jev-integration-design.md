# P0 Jev Integration: Design Spec

**Date:** 2026-10-03
**Scope:** Replace LLM escalator with Jev + enhance entry guard with Jev probabilistic layer
**Priority:** P0 — execution-critical path, highest impact integration

---

## 1. Problem Statement

The trading bot's execution layer has two AI-related bottlenecks:

1. **LLM Escalator** (`executor/llm_escalator.py`): When the entry guard is uncertain (confidence < 0.4), it escalates to Claude Sonnet with a 10s timeout. In a 5-second tick loop, this blocks the entire execution cycle. Max 5 escalations/day. Costs ~$0.02/call.

2. **Entry Guard Rigidity** (`executor/entry_guard.py`): 10 hard-coded rules with binary thresholds (e.g., momentum < -60 → VETO). Gray zone cases get a flat 0.39 confidence with no nuance. ENTER decisions at confidence 0.8 have no validation against fading moves.

TypeSafe's Jev model (System One) returns typed decisions with calibrated probabilities in ~100ms at $0.00004/call — making it viable to run inside every tick for every position.

## 2. Goals

- Entry/exit escalation decisions in <200ms (was 3-10s)
- Continuous position assessment every tick (was occasional escalation only)
- Calibrated confidence scores replacing binary thresholds
- Zero breaking changes — existing behavior preserved when Jev disabled
- Claude retained as rare fallback for low-confidence Jev results

## 3. Non-Goals

- Tier 2/3 Jev integration (separate work items)
- Intelligent Tier 1 screening (already implemented in `intelligent_screener.py`)
- News screening, live regime monitoring (P1/P2)
- Replacing Claude for Tier 3 deep analysis (stays on Claude permanently)

---

## 4. Architecture

### 4.1 Component Map

```
NEW FILES:
  core/jev_client.py                  — Thin wrapper around TypeSafeClient
  executor/jev_escalator.py           — Drop-in replacement for LLMEscalator
  tests/executor/test_jev_escalator.py — 11 tests

MODIFIED FILES:
  executor/entry_guard.py             — Add optional Jev validation layer
  executor/execution_intelligence.py  — Wire JevEscalator + Jev-enhanced guard
  core/config.py                      — Add JevConfig dataclass
  config.toml                         — Add [jev] section
  pyproject.toml                      — Add typesafe-sdk dependency
  tests/executor/test_entry_guard.py  — Add 4 Jev-related tests
```

### 4.2 Decision Chain

```
Entry Guard (deterministic, 10 rules)
  ├─ VETO (conf > 0.9): done, skip — Jev never overrides
  ├─ ENTER (conf 0.8): Jev validates
  │    ├─ fading_risk > 0.65 → downgrade to WAIT
  │    ├─ momentum_quality < 0.25 → downgrade to WAIT
  │    └─ confirmed → ENTER (confidence boosted)
  └─ WAIT / GRAY ZONE (conf < 0.4): JevEscalator
       ├─ Jev confident (> 0.6) → act on Jev result
       ├─ Jev uncertain (< 0.3) → Claude fallback
       └─ Jev unavailable → Claude fallback → deterministic fallback
```

### 4.3 Hierarchy of Control

```
1. DETERMINISTIC SAFETY  — kill switch, stops, time cutoff (never overridden)
2. DETERMINISTIC RULES   — entry guard hard vetoes (never overridden by AI)
3. JEV (System One)      — fast probabilistic layer, enriches/validates
4. CLAUDE (System Two)   — slow reasoning, rare fallback when Jev uncertain
5. DETERMINISTIC DEFAULT — WAIT/HOLD when all AI unavailable
```

---

## 5. Component Specifications

### 5.1 JevClient (`core/jev_client.py`)

**Responsibility:** Thin wrapper around `typesafe_sdk.TypeSafeClient`. Handles SDK import failure gracefully.

**Interface:**
```python
class JevClient:
    def __init__(self, config: JevConfig):
        # Reads TYPESAFE_API_KEY from env
        # Catches ImportError if typesafe-sdk not installed
        # Sets self.available = False on failure

    @property
    def available(self) -> bool:
        """Whether Jev is usable (SDK installed + API key present)."""

    def evaluate(self, state: dict, questions: dict) -> dict | None:
        """Sync evaluation. Returns response.answers dict or None on failure."""
        # Wraps client.system_one()
        # Logs questions + answers at DEBUG level
        # Catches TypeSafeAPIError, logs warning, returns None
        # Tracks call count and cumulative latency

    async def aevaluate(self, state: dict, questions: dict) -> dict | None:
        """Async evaluation. Same contract as evaluate()."""
        # Uses AsyncTypeSafeClient

    def stats(self) -> dict:
        """Returns {calls: int, total_latency_ms: float, avg_latency_ms: float}."""
```

**Design choices:**
- Returns `None` on any failure (timeout, API error, import error) — callers check for None
- No retry logic — Jev is fast enough that retries aren't worth the latency
- Logging at DEBUG to avoid noise; WARNING on failures
- Stats for observability dashboard

### 5.2 JevEscalator (`executor/jev_escalator.py`)

**Responsibility:** Drop-in replacement for `LLMEscalator`. Same async interface, same return type (`EscalationResult`).

**Interface:**
```python
class JevEscalator:
    def __init__(self, jev_client: JevClient, config: JevConfig,
                 llm_fallback: LLMEscalator | None = None):
        self._jev = jev_client
        self._config = config
        self._fallback = llm_fallback
        self._call_count = 0

    async def evaluate_entry(self, leg, symbol_state, candles) -> EscalationResult:
        """Entry decision via Jev, with Claude fallback."""

    async def evaluate_exit(self, position, symbol_state, candles) -> EscalationResult:
        """Exit decision via Jev, with Claude fallback."""
```

**Entry evaluation — 3 questions, 1 Jev call:**

| ID | Type | Instructions |
|----|------|-------------|
| `should_enter` | Noul | "Should this trade be entered based on live price action?" with criteria for true/false |
| `invalidated` | Noul | "Has the original trade setup been invalidated by current price action?" |
| `timing` | Choice | "What is the best action right now?" with options: enter_now, wait_5min, skip |

State payload:
```python
{
    "setup": {symbol, direction, strategy, entry_price, stop_loss, target_1},
    "live": {momentum_1m, momentum_5m, volume_ratio, vwap_position,
             trend_alignment, strength, body_dominance,
             last_pattern_1m, last_pattern_5m},
    "candles_5m": candles[-6:]  # last 30 min
}
```

Decision mapping:
```
invalidated.noul > 0.7                           → EscalationResult("SKIP", ...)
timing.choice == "skip"                           → EscalationResult("SKIP", ...)
should_enter.noul > config.entry_confidence       → EscalationResult("ENTER", ...)
should_enter.noul < config.uncertainty_threshold   → delegate to llm_fallback
otherwise                                          → EscalationResult("WAIT", ...)
```

**Exit evaluation — 3 questions, 1 Jev call:**

| ID | Type | Instructions |
|----|------|-------------|
| `exit_now` | Noul | "Should this position be closed immediately?" with criteria |
| `momentum_exhaustion` | Noul | "Is the momentum that drove this trade showing signs of exhaustion?" |
| `reversal_risk` | Score (5 levels) | "How likely is a reversal against this position in the next 30 minutes?" |

Decision mapping:
```
exit_now.noul > config.exit_confidence             → EscalationResult("EXIT", ...)
reversal_risk.score/4 > 0.7 AND exhaustion > 0.6  → EscalationResult("HOLD", reasoning="tighten_stop")
exit_now.noul < config.uncertainty_threshold        → delegate to llm_fallback
otherwise                                           → EscalationResult("HOLD", ...)
```

**Fallback chain (both methods):**
```
1. Try Jev → if result is confident, return it
2. If Jev uncertain OR failed → try llm_fallback.evaluate_*()
3. If llm_fallback is None OR fails → return deterministic default
   Entry default: EscalationResult("WAIT", "all_escalators_unavailable", 0.0, True)
   Exit default: EscalationResult("HOLD", "all_escalators_unavailable", 0.0, True)
```

**Reasoning string:** Since Jev doesn't generate text, `EscalationResult.reasoning` is assembled from scores:
```
"jev: should_enter=0.82, timing=enter_now(conf=0.91), invalidated=0.05"
```
This preserves existing logging/UI that displays reasoning.

### 5.3 Entry Guard Enhancement (`executor/entry_guard.py`)

**Changes:** Constructor accepts optional `jev_client`. Two new behaviors:

**A) Validate ENTER verdicts (after rule 10):**
```
If jev_client available AND verdict is ENTER:
  Call _jev_validate_entry(leg, state) → {enter_now, momentum_quality, fading_risk}
  If fading_risk > 0.65 → downgrade to WAIT("jev_fading_risk", 0.5, reassess=30)
  If momentum_quality < 0.25 → downgrade to WAIT("jev_low_momentum_quality", 0.45, reassess=60)
  Else → boost confidence by momentum_quality * 0.15 (capped at 0.95)
```

**B) Enrich gray zone confidence (after all rules, no match):**
```
If jev_client available:
  Call _jev_validate_entry(leg, state)
  gray_confidence = 0.3 * enter_now + 0.2 * momentum_quality
  verdict.confidence = gray_confidence
  # May now be above 0.4 → skipping escalation entirely
  # Or still below → escalation proceeds (to JevEscalator now, not Claude)
```

**Private method `_jev_validate_entry(leg, state)` — 3 questions:**

| ID | Type | Purpose |
|----|------|---------|
| `enter_now` | Noul | Overall entry signal |
| `momentum_quality` | Score (0-4) | Momentum favorability, normalized to 0-1 |
| `fading_risk` | Noul | Has the move already played out? |

**Failure mode:** If Jev call returns None (timeout/error), return original deterministic verdict unchanged. Jev is enhancement, never a gate.

### 5.4 Wiring (`executor/execution_intelligence.py`)

```python
# In __init__ or setup method:

# 1. Create Jev client (optional)
jev_client = JevClient(config.jev) if config.jev.enabled else None

# 2. Create LLM escalator as before (now serves as fallback)
llm_escalator = LLMEscalator()

# 3. Jev escalator wraps both, or fall back to pure LLM
if jev_client and jev_client.available:
    escalator = JevEscalator(jev_client, config.jev, llm_fallback=llm_escalator)
else:
    escalator = llm_escalator

# 4. Entry guard gets optional Jev
entry_guard = EntryGuard(config.execution, jev_client=jev_client)
```

**Executor code (`executor.py`) requires zero changes.** It calls `escalator.evaluate_entry()` and `entry_guard.evaluate()` with the same interfaces.

### 5.5 Configuration

**`core/config.py` — new dataclass:**
```python
@dataclass
class JevConfig:
    enabled: bool = True
    model: str = "jev-latest"
    entry_confidence_threshold: float = 0.6
    exit_confidence_threshold: float = 0.75
    uncertainty_threshold: float = 0.3
    timeout_ms: int = 2000
```

**`config.toml` — new section:**
```toml
[jev]
enabled = true
model = "jev-latest"
entry_confidence_threshold = 0.6
exit_confidence_threshold = 0.75
uncertainty_threshold = 0.3
timeout_ms = 2000
```

**Environment:** `TYPESAFE_API_KEY` in `.env` (same pattern as existing `ANTHROPIC_API_KEY`).

---

## 6. Test Plan

### 6.1 New Tests: `test_jev_escalator.py` (11 tests)

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_entry_enter_high_confidence` | should_enter=0.85 + timing=enter_now → ENTER |
| 2 | `test_entry_skip_invalidated` | invalidated=0.8 → SKIP |
| 3 | `test_entry_skip_timing` | timing=skip → SKIP |
| 4 | `test_entry_wait_moderate` | should_enter=0.45 → WAIT |
| 5 | `test_entry_claude_fallback_low_confidence` | should_enter=0.15 → calls LLMEscalator |
| 6 | `test_entry_jev_unavailable_uses_fallback` | jev_client=None → calls LLMEscalator |
| 7 | `test_entry_jev_timeout_uses_fallback` | evaluate returns None → calls LLMEscalator |
| 8 | `test_entry_all_unavailable_returns_wait` | Jev + Claude both fail → WAIT with fallback_used |
| 9 | `test_exit_close_high_confidence` | exit_now=0.9 → EXIT |
| 10 | `test_exit_tighten_stop` | reversal=0.8 + exhaustion=0.7 → HOLD(tighten_stop) |
| 11 | `test_reasoning_contains_scores` | EscalationResult.reasoning includes "jev:" prefix + noul values |

**Mock strategy:** Mock `typesafe_sdk` at module level. Build `MockResponse` with `.answers` dict returning typed objects with `.noul`, `.score`, `.choice`, `.confidence` attributes.

### 6.2 New Tests: `test_entry_guard.py` additions (4 tests)

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_jev_fading_overrides_enter` | Good momentum (rule 10 ENTER) + fading=0.75 → WAIT |
| 2 | `test_jev_low_quality_overrides_enter` | Good momentum (rule 10 ENTER) + quality=0.1 → WAIT |
| 3 | `test_jev_confirms_boosts_confidence` | Rule 10 ENTER + quality=0.8 → confidence > 0.8 |
| 4 | `test_jev_unavailable_uses_deterministic` | Jev returns None → original ENTER(0.8) unchanged |

### 6.3 Existing Tests: No Modifications

- 12 existing entry guard tests pass (jev_client defaults to None)
- 7 existing LLM escalator tests pass (LLMEscalator class unchanged)

---

## 7. Rollout Plan

| Phase | Config | Behavior | Duration |
|-------|--------|----------|----------|
| **Ship** | `jev.enabled = false` | Existing behavior. Zero risk. | Immediate |
| **Shadow** | `jev.enabled = true` | Both run; Jev logged, Claude decides | 1-2 days paper trading |
| **Primary** | `jev.enabled = true` | Jev decides; Claude fallback only | After shadow validation |

**Observability:** JevClient logs call count, avg latency, fallback rate. Existing `execution_decisions` DB table captures all verdicts with source (jev/claude/deterministic).

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Jev API down during market hours | Claude fallback → deterministic fallback. Three-layer chain. |
| Jev miscalibrated for Indian equities | Shadow mode compares Jev vs Claude decisions before switching |
| typesafe-sdk not installed | `JevClient.available` returns False, all code skips Jev |
| Jev latency spike > 2s | Timeout at 2s, fallback chain activates |
| Question design suboptimal | Questions are data in config-like structure, easy to tune without code changes |

---

## 9. Estimated Effort

~510 lines new/changed code. 15 new tests. 3 new files, 6 modified files.
Estimated: 1-2 focused implementation sessions.
