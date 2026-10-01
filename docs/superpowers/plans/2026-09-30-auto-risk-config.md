# Auto Risk Config from Capital — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically derive risk parameters (risk per trade, daily loss cap, capital deployment %, concurrent positions, shadow fraction) from the `capital` value so users only set one number.

**Architecture:** Add `auto_risk_config(capital)` function that maps capital to tier-based risk params. Make `[risk]` section in config.toml optional — when absent or partially specified, missing fields auto-derive from capital. Explicit TOML values always override auto-derived ones. API config endpoint surfaces whether each risk param is "auto" or "manual".

**Tech Stack:** Python dataclasses, TOML config, FastAPI

**Spec:** User request — "can these configs be auto done based on the capital?"

## Global Constraints

- Python 3.12+
- All dataclasses `frozen=True`
- Risk percentages as decimals (0.01 = 1%)
- Tests use `pytest`, existing `make_risk_config()` helper pattern
- Config file format: TOML

## Review Focus

1. Capital exactly at a tier boundary (e.g., 50000.0) — should deterministically pick one tier, not oscillate
2. `auto_risk_config(0)` or negative capital — should raise `ConfigError`, not produce nonsensical risk params
3. Partial override in TOML (e.g., only `max_concurrent_positions` specified, rest auto) — auto fields must still derive correctly
4. Paper mode `initial_capital` vs `general.capital` — auto risk should derive from `general.capital`, not paper capital
5. API PUT `/config` changing `capital` but not `[risk]` — risk params should re-derive on reload

---

### Task 1: `auto_risk_config()` Function

**Files:**
- Modify: `tradingbot/core/config.py` (add function after `RiskConfig` class, ~line 55)
- Test: `tests/core/test_auto_risk_config.py` (new)

**Interfaces:**
- Consumes: `RiskConfig` dataclass (existing)
- Produces: `auto_risk_config(capital: float) -> RiskConfig` — used by `load_config()` in Task 2

- [ ] **Step 1: Write failing tests for tier logic**

```python
"""Tests for capital-based automatic risk configuration."""

import pytest

from tradingbot.core.config import ConfigError, RiskConfig, auto_risk_config


class TestAutoRiskConfigTiers:
    """Each capital tier produces the documented risk parameters."""

    def test_micro_account_under_50k(self):
        rc = auto_risk_config(20_000.0)
        assert rc == RiskConfig(
            max_risk_per_trade_pct=0.015,
            max_daily_loss_pct=0.03,
            max_capital_deployed_pct=0.70,
            max_concurrent_positions=1,
        )

    def test_small_account_50k_to_200k(self):
        rc = auto_risk_config(100_000.0)
        assert rc == RiskConfig(
            max_risk_per_trade_pct=0.01,
            max_daily_loss_pct=0.025,
            max_capital_deployed_pct=0.60,
            max_concurrent_positions=2,
        )

    def test_medium_account_200k_to_1m(self):
        rc = auto_risk_config(500_000.0)
        assert rc == RiskConfig(
            max_risk_per_trade_pct=0.01,
            max_daily_loss_pct=0.02,
            max_capital_deployed_pct=0.50,
            max_concurrent_positions=2,
        )

    def test_large_account_above_1m(self):
        rc = auto_risk_config(2_000_000.0)
        assert rc == RiskConfig(
            max_risk_per_trade_pct=0.0075,
            max_daily_loss_pct=0.02,
            max_capital_deployed_pct=0.40,
            max_concurrent_positions=3,
        )


class TestAutoRiskConfigBoundaries:
    """Exact boundary values pick the higher tier (more conservative)."""

    def test_exactly_50k_is_small_tier(self):
        rc = auto_risk_config(50_000.0)
        assert rc.max_risk_per_trade_pct == 0.01
        assert rc.max_concurrent_positions == 2

    def test_exactly_200k_is_medium_tier(self):
        rc = auto_risk_config(200_000.0)
        assert rc.max_capital_deployed_pct == 0.50

    def test_exactly_1m_is_large_tier(self):
        rc = auto_risk_config(1_000_000.0)
        assert rc.max_risk_per_trade_pct == 0.0075


class TestAutoRiskConfigInvalid:
    """Zero and negative capital are rejected."""

    def test_zero_capital_raises(self):
        with pytest.raises(ConfigError, match="capital must be positive"):
            auto_risk_config(0)

    def test_negative_capital_raises(self):
        with pytest.raises(ConfigError, match="capital must be positive"):
            auto_risk_config(-10_000.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_auto_risk_config.py -v`
Expected: ImportError — `auto_risk_config` does not exist yet

- [ ] **Step 3: Implement `auto_risk_config`**

Add to `tradingbot/core/config.py` after the `RiskConfig` dataclass (after line 54):

```python
_RISK_TIERS: list[tuple[float, RiskConfig]] = [
    (1_000_000.0, RiskConfig(
        max_risk_per_trade_pct=0.0075,
        max_daily_loss_pct=0.02,
        max_capital_deployed_pct=0.40,
        max_concurrent_positions=3,
    )),
    (200_000.0, RiskConfig(
        max_risk_per_trade_pct=0.01,
        max_daily_loss_pct=0.02,
        max_capital_deployed_pct=0.50,
        max_concurrent_positions=2,
    )),
    (50_000.0, RiskConfig(
        max_risk_per_trade_pct=0.01,
        max_daily_loss_pct=0.025,
        max_capital_deployed_pct=0.60,
        max_concurrent_positions=2,
    )),
    (0.0, RiskConfig(
        max_risk_per_trade_pct=0.015,
        max_daily_loss_pct=0.03,
        max_capital_deployed_pct=0.70,
        max_concurrent_positions=1,
    )),
]


def auto_risk_config(capital: float) -> RiskConfig:
    """Derive risk parameters from the account size."""
    if capital <= 0:
        raise ConfigError("capital must be positive")
    for threshold, config in _RISK_TIERS:
        if capital >= threshold:
            return config
    return _RISK_TIERS[-1][1]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_auto_risk_config.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tradingbot/core/config.py tests/core/test_auto_risk_config.py
git commit -m "feat(config): add auto_risk_config() to derive risk params from capital"
```

---

### Task 2: Make `[risk]` Section Optional in Config Loading

**Files:**
- Modify: `tradingbot/core/config.py:224-231` (`load_config` function, risk section handling)
- Test: `tests/core/test_config_auto_risk.py` (new)

**Interfaces:**
- Consumes: `auto_risk_config(capital)` from Task 1
- Produces: `load_config()` returns `Config` with auto-derived or merged `RiskConfig`. Downstream unchanged — `Config.risk` is still a `RiskConfig`.

- [ ] **Step 1: Write failing tests for optional `[risk]` loading**

```python
"""Tests for auto-risk integration in load_config."""

import textwrap
from pathlib import Path

import pytest

from tradingbot.core.config import ConfigError, load_config


MINIMAL_TOML = textwrap.dedent("""\
    [general]
    mode = "paper"
    capital = 20000
    log_level = "INFO"

    [strategy]
    backtest_days = 30
    candle_interval = "15minute"
    min_confidence = 0.5
    min_reward_risk = 1.5
    max_trades_per_day = 2

    [execution]
    entry_slippage_pct = 0.05
    square_off_time = "15:10"
    connection_timeout_sec = 30
    heartbeat_interval_sec = 60
    plan_max_age_hours = 14
    max_entry_price_drift_pct = 2.0

    [llm]
    provider = "anthropic"
    model = "claude-sonnet-4-20250514"
    timeout_sec = 60
    max_retries = 1

    [paper]
    slippage_pct = 0.05
    initial_capital = 20000
""")


@pytest.fixture()
def env_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("KITE_API_KEY", "test-key")
    monkeypatch.setenv("KITE_API_SECRET", "test-secret")


def test_missing_risk_section_auto_derives_from_capital(tmp_path, env_secrets):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(MINIMAL_TOML)

    config = load_config(cfg_path)

    assert config.risk.max_risk_per_trade_pct == 0.015
    assert config.risk.max_daily_loss_pct == 0.03
    assert config.risk.max_capital_deployed_pct == 0.70
    assert config.risk.max_concurrent_positions == 1


def test_partial_risk_section_merges_with_auto(tmp_path, env_secrets):
    toml_with_partial_risk = MINIMAL_TOML + textwrap.dedent("""\

        [risk]
        max_concurrent_positions = 3
    """)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(toml_with_partial_risk)

    config = load_config(cfg_path)

    assert config.risk.max_concurrent_positions == 3
    assert config.risk.max_risk_per_trade_pct == 0.015


def test_full_risk_section_overrides_all_auto(tmp_path, env_secrets):
    toml_with_full_risk = MINIMAL_TOML + textwrap.dedent("""\

        [risk]
        max_risk_per_trade_pct = 0.005
        max_daily_loss_pct = 0.01
        max_capital_deployed_pct = 0.30
        max_concurrent_positions = 4
    """)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(toml_with_full_risk)

    config = load_config(cfg_path)

    assert config.risk.max_risk_per_trade_pct == 0.005
    assert config.risk.max_daily_loss_pct == 0.01
    assert config.risk.max_capital_deployed_pct == 0.30
    assert config.risk.max_concurrent_positions == 4


def test_large_capital_auto_derives_conservative_params(tmp_path, env_secrets):
    large_toml = MINIMAL_TOML.replace("capital = 20000", "capital = 2000000")
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(large_toml)

    config = load_config(cfg_path)

    assert config.risk.max_risk_per_trade_pct == 0.0075
    assert config.risk.max_concurrent_positions == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_config_auto_risk.py -v`
Expected: FAIL — `load_config` raises `ConfigError` for missing `[risk]` section

- [ ] **Step 3: Modify `load_config` to make `[risk]` optional**

In `tradingbot/core/config.py`, change the `load_config` function. Replace lines 193-194 and 226-231:

Before (line ~193):
```python
    risk_raw = _section(data, "risk")
```

After:
```python
    risk_raw = data.get("risk", {})
```

Before (line ~226):
```python
        risk=RiskConfig(
            max_risk_per_trade_pct=float(risk_raw["max_risk_per_trade_pct"]),
            max_daily_loss_pct=float(risk_raw["max_daily_loss_pct"]),
            max_capital_deployed_pct=float(risk_raw["max_capital_deployed_pct"]),
            max_concurrent_positions=int(risk_raw["max_concurrent_positions"]),
        ),
```

After:
```python
        risk=_build_risk_config(risk_raw, capital=float(general_raw["capital"])),
```

Add this helper function before `load_config`:

```python
def _build_risk_config(risk_raw: dict, capital: float) -> RiskConfig:
    """Merge explicit TOML overrides onto auto-derived defaults."""
    auto = auto_risk_config(capital)
    if not risk_raw:
        return auto
    from dataclasses import asdict
    auto_dict = asdict(auto)
    type_map = {"max_risk_per_trade_pct": float, "max_daily_loss_pct": float,
                "max_capital_deployed_pct": float, "max_concurrent_positions": int}
    for key in auto_dict:
        if key in risk_raw:
            auto_dict[key] = type_map[key](risk_raw[key])
    return RiskConfig(**auto_dict)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_config_auto_risk.py tests/core/test_auto_risk_config.py -v`
Expected: All PASS

- [ ] **Step 5: Run existing config and risk manager tests to check for regressions**

Run: `pytest tests/core/test_risk_manager.py tests/ -k "config" -v`
Expected: All existing tests still PASS (they provide explicit `RiskConfig` — not affected)

- [ ] **Step 6: Commit**

```bash
git add tradingbot/core/config.py tests/core/test_config_auto_risk.py
git commit -m "feat(config): make [risk] section optional, auto-derive from capital"
```

---

### Task 3: Remove Hardcoded `[risk]` from `config.toml` Default

**Files:**
- Modify: `config.toml:13-17` (remove or comment the `[risk]` section)
- Modify: `tradingbot/api/config_routes.py:61-66` (add `auto_derived` flag to API response)
- Test: `tests/api/test_config_routes.py` (add test for auto-derived flag — if this file exists; otherwise add to existing API test file)

**Interfaces:**
- Consumes: `auto_risk_config(capital)` from Task 1, `_build_risk_config()` from Task 2
- Produces: API response includes `risk.auto_derived: true/false` per field. Frontend can show which params are auto vs manual.

- [ ] **Step 1: Check for existing API config tests**

Run: `find tests/ -name "*.py" | xargs grep -l "config_routes\|/api/config" 2>/dev/null`

Look at existing API test patterns to follow.

- [ ] **Step 2: Write test for auto_derived flag in API response**

Add to the appropriate API test file (or create `tests/api/test_config_auto_risk.py`):

```python
"""Test that the config API surfaces auto-derived risk info."""

import pytest
from unittest.mock import MagicMock

from tradingbot.core.config import (
    Config, GeneralConfig, RiskConfig, StrategyConfig, ExecutionConfig,
    LLMConfig, PaperConfig, Secrets, ScannerConfig, ScreeningConfig,
    BacktestConfig, KiteConfig, auto_risk_config,
)
from tradingbot.core.models import Mode


def test_config_response_includes_auto_derived_flag():
    capital = 20_000.0
    auto = auto_risk_config(capital)
    risk = RiskConfig(
        max_risk_per_trade_pct=auto.max_risk_per_trade_pct,
        max_daily_loss_pct=auto.max_daily_loss_pct,
        max_capital_deployed_pct=auto.max_capital_deployed_pct,
        max_concurrent_positions=5,
    )
    from tradingbot.api.config_routes import _risk_response
    result = _risk_response(risk, capital)

    assert result["max_risk_per_trade_pct"] == 0.015
    assert result["auto_derived"]["max_risk_per_trade_pct"] is True
    assert result["auto_derived"]["max_concurrent_positions"] is False
```

- [ ] **Step 3: Add `_risk_response` helper to config_routes.py**

In `tradingbot/api/config_routes.py`, add a helper and update `_config_to_dict`:

```python
from tradingbot.core.config import auto_risk_config

def _risk_response(risk: RiskConfig, capital: float) -> dict:
    """Risk config dict with auto_derived flags per field."""
    from dataclasses import asdict
    auto = auto_risk_config(capital)
    auto_dict = asdict(auto)
    risk_dict = asdict(risk)
    auto_flags = {k: risk_dict[k] == auto_dict[k] for k in risk_dict}
    return {**risk_dict, "auto_derived": auto_flags}
```

Update the `_config_to_dict` function to replace the hardcoded `risk` section:

```python
        "risk": _risk_response(config.risk, config.general.capital),
```

- [ ] **Step 4: Update `config.toml` — remove `[risk]` section**

Remove lines 13-17 from `config.toml`:

```toml
[risk]
max_risk_per_trade_pct = 0.01
max_daily_loss_pct = 0.02
max_capital_deployed_pct = 0.50
max_concurrent_positions = 2
```

The bot now auto-derives these from `capital = 400000` (medium tier: 1%/2%/50%/2 — same values as before, so behavior unchanged).

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All tests PASS. Existing tests that construct `RiskConfig` directly are unaffected. Config loading tests work because `[risk]` is now optional.

- [ ] **Step 6: Commit**

```bash
git add config.toml tradingbot/api/config_routes.py tests/api/test_config_auto_risk.py
git commit -m "feat(config): remove hardcoded [risk] section, auto-derive from capital

Users now only need to set capital in config.toml. Risk parameters
auto-scale based on account size tiers. Explicit [risk] overrides
still respected. API response includes auto_derived flags."
```

---

### Task 4: Auto-Derive `shadow_fraction` from Capital

**Files:**
- Modify: `tradingbot/core/config.py` (extend `auto_risk_config` or add parallel function)
- Modify: `tradingbot/core/config.py:240-242` (`load_config` — default `shadow_fraction` from capital)
- Test: `tests/core/test_auto_risk_config.py` (add shadow_fraction tests)

**Interfaces:**
- Consumes: `auto_risk_config(capital)` from Task 1
- Produces: `auto_shadow_fraction(capital) -> float` — used by `load_config()` when `shadow_fraction` not in TOML

- [ ] **Step 1: Write failing tests**

Add to `tests/core/test_auto_risk_config.py`:

```python
from tradingbot.core.config import auto_shadow_fraction


class TestAutoShadowFraction:
    """Small accounts use full quantity; large accounts use shadow mode."""

    def test_under_50k_no_shadow(self):
        assert auto_shadow_fraction(20_000.0) == 1.0

    def test_50k_to_200k_no_shadow(self):
        assert auto_shadow_fraction(100_000.0) == 1.0

    def test_200k_to_1m_uses_shadow(self):
        assert auto_shadow_fraction(500_000.0) == 0.1

    def test_above_1m_uses_shadow(self):
        assert auto_shadow_fraction(2_000_000.0) == 0.1

    def test_zero_capital_raises(self):
        with pytest.raises(ConfigError, match="capital must be positive"):
            auto_shadow_fraction(0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_auto_risk_config.py::TestAutoShadowFraction -v`
Expected: ImportError — `auto_shadow_fraction` does not exist

- [ ] **Step 3: Implement `auto_shadow_fraction`**

Add to `tradingbot/core/config.py` after `auto_risk_config`:

```python
def auto_shadow_fraction(capital: float) -> float:
    """Shadow fraction: small accounts trade full size, large accounts shadow."""
    if capital <= 0:
        raise ConfigError("capital must be positive")
    if capital < 200_000.0:
        return 1.0
    return 0.1
```

- [ ] **Step 4: Wire into `load_config`**

In `load_config`, change the `shadow_fraction` default in `ExecutionConfig` construction:

Before:
```python
            shadow_fraction=float(execution_raw.get("shadow_fraction", 0.1)),
```

After:
```python
            shadow_fraction=float(execution_raw.get(
                "shadow_fraction",
                auto_shadow_fraction(float(general_raw["capital"])),
            )),
```

- [ ] **Step 5: Run all tests**

Run: `pytest tests/ -v --tb=short`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add tradingbot/core/config.py tests/core/test_auto_risk_config.py
git commit -m "feat(config): auto-derive shadow_fraction from capital size"
```
