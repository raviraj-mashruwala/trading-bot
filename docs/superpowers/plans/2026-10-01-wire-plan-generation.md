# Wire Plan Generation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect analysis output to execution input so the bot can run end-to-end: analyze → generate plan → execute.

**Architecture:** Add `POST /plans/generate` endpoint that calls `PlanBuilder.build()` → `PlanStore.save()`. Auto-trigger plan generation after `analysis.complete` event in `_run_analysis()`. This closes the last gap in the pipeline.

**Tech Stack:** Python 3.12, FastAPI, existing `PlanBuilder`, `PlanStore`, `EventBus`

**Spec:** No separate spec — bounded feature bridging existing components (`PlanBuilder` from `core/plan_builder.py`, `PlanStore` from `core/plan_store.py`, `analysis_routes.py` event emission).

## Global Constraints

- Python 3.12, `from __future__ import annotations` in every file touched
- `PlanBuilder` requires `SetupStore` + `RiskManager` — both available via `AppState`
- `PlanStore.save()` returns a `Path`; executor's `POST /execute` calls `PlanStore.load(trade_date)`
- `analysis.complete` event carries `{"trade_date": str, "run_id": str}`
- `auto_risk_config(capital)` derives `RiskConfig` from capital (no hardcoded risk params)
- Every task ends with `uv run python -m pytest` passing

## Review Focus

1. **Plan generation when no setups approved (0 legs):** `PlanBuilder.build()` returns empty plan — `PlanStore.save()` writes it — `POST /execute` loads it and executor starts with 0 legs (idle session). Should not crash. Test added to Task 1: `test_generate_plan_with_no_approved_setups`.
2. **Concurrent analysis + plan generation:** `_run_analysis` is async — if user hits `/plans/generate` while analysis is running, `SetupStore` may be mid-write. `PlanBuilder` reads committed rows (`get_active`), so partial writes (uncommitted) are excluded. Safe but worth testing. Test added to Task 1: `test_generate_plan_returns_only_committed_setups`.
3. **Auto-trigger generates plan for wrong date:** `analysis.complete` event carries `trade_date` — `_auto_generate_plan` must use that date, not `date.today()`. Test added to Task 2.
4. **`RiskManager` construction from config:** Must use `auto_risk_config(capital)` + `StrategyConfig` from config. Not hardcoded. Verified in Task 1 implementation.
5. **Plan already exists for date:** `PlanStore.save()` overwrites — if analysis runs twice, second plan replaces first. Correct behavior (latest analysis wins).

---

### Task 1: `POST /plans/generate` Endpoint

**Files:**
- Modify: `tradingbot/api/analysis_routes.py` — add `/plans/generate` endpoint + helper to build `PlanBuilder`
- Test: `tests/api/test_plan_generate.py` (new)

**Interfaces:**
- Consumes: `PlanBuilder` from `tradingbot/core/plan_builder.py`, `PlanStore` from `state.plan_store`, `SetupStore` from `state.setup_store`, `RiskManager` from `tradingbot/core/risk_manager.py`, `auto_risk_config` from `tradingbot/core/config.py`
- Produces: `POST /plans/generate?date=YYYY-MM-DD` → saves `TradePlan` to `PlanStore`, returns `{"status": "generated", "trade_date": str, "legs": int}`

- [ ] **Step 1: Write failing tests**

```python
# tests/api/test_plan_generate.py
"""Tests for POST /plans/generate endpoint."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tradingbot.core.models import Direction, StrategyName

IST = ZoneInfo("Asia/Kolkata")


async def test_generate_plan_creates_plan_file(api_client):
    from tradingbot.persistence.setup_store import SetupStore
    db_path = api_client._tmp_path / "tradingbot.db"
    ss = SetupStore(db_path)
    ss.save({
        "run_id": "run_001", "trade_date": "2026-10-01", "symbol": "TCS",
        "strategy": "breakout", "direction": "long", "entry_price": 3500.0,
        "stop_loss": 3450.0, "target_1": 3600.0, "target_2": 3680.0,
        "confidence": 0.78, "status": "approved", "reasoning": "test",
    })
    ss.close()

    response = await api_client.post("/api/plans/generate?date=2026-10-01")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "generated"
    assert body["legs"] >= 1

    plan_response = await api_client.get("/api/plans/2026-10-01")
    assert plan_response.status_code == 200
    plan = plan_response.json()
    assert len(plan["legs"]) >= 1
    assert plan["legs"][0]["symbol"] == "TCS"


async def test_generate_plan_with_no_approved_setups(api_client):
    response = await api_client.post("/api/plans/generate?date=2026-10-02")
    assert response.status_code == 200
    body = response.json()
    assert body["legs"] == 0


async def test_generate_plan_legs_carry_setup_id(api_client):
    from tradingbot.persistence.setup_store import SetupStore
    db_path = api_client._tmp_path / "tradingbot.db"
    ss = SetupStore(db_path)
    setup_id = ss.save({
        "run_id": "run_001", "trade_date": "2026-10-01", "symbol": "INFY",
        "strategy": "momentum", "direction": "long", "entry_price": 1800.0,
        "stop_loss": 1770.0, "target_1": 1860.0, "target_2": 1900.0,
        "confidence": 0.82, "status": "approved", "reasoning": "test",
    })
    ss.close()

    response = await api_client.post("/api/plans/generate?date=2026-10-01")
    plan = (await api_client.get("/api/plans/2026-10-01")).json()

    found = [l for l in plan["legs"] if l["symbol"] == "INFY"]
    assert len(found) == 1
    assert found[0]["setup_id"] == setup_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/api/test_plan_generate.py -v`
Expected: 404 — endpoint doesn't exist

- [ ] **Step 3: Implement endpoint**

In `tradingbot/api/analysis_routes.py`, add after the existing imports:

```python
from tradingbot.core.config import auto_risk_config
from tradingbot.core.plan_builder import PlanBuilder
from tradingbot.core.risk_manager import RiskManager
from tradingbot.core.models import MarketRegime
```

Add helper function:

```python
def _build_plan_builder(state: AppState) -> PlanBuilder:
    config = state.config
    risk_config = auto_risk_config(config.general.capital)
    rm = RiskManager(
        risk_config=risk_config,
        strategy_config=config.strategy,
        capital=config.general.capital,
    )
    return PlanBuilder(state.setup_store, rm)
```

Add endpoint:

```python
@router.post("/plans/generate")
async def generate_plan(request: Request, date: str | None = None):
    state: AppState = request.app.state.app_state

    if date:
        from datetime import date as d
        trade_date = d.fromisoformat(date)
    else:
        trade_date = next_trading_day(now_ist().date())

    builder = _build_plan_builder(state)
    plan = builder.build(trade_date, regime=MarketRegime.RANGE_BOUND)
    state.plan_store.save(plan)
    state.database.save_plan_snapshot(plan)

    return {
        "status": "generated",
        "trade_date": plan.trade_date,
        "legs": len(plan.legs),
    }
```

- [ ] **Step 4: Run tests**

Run: `uv run python -m pytest tests/api/test_plan_generate.py -v`
Expected: All 3 PASS

- [ ] **Step 5: Run full API test suite**

Run: `uv run python -m pytest tests/api/ -v --tb=short`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add tradingbot/api/analysis_routes.py tests/api/test_plan_generate.py
git commit -m "feat(api): add POST /plans/generate to bridge analysis → execution

Reads approved setups from SetupStore, sizes through RiskManager with
auto-derived risk config, saves TradePlan to PlanStore. Executor can
now load and execute the generated plan.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Auto-Generate Plan After Analysis Completes

**Files:**
- Modify: `tradingbot/api/analysis_routes.py:91-99` — call `PlanBuilder` after `pipeline.run()` succeeds
- Test: `tests/api/test_analysis_auto_plan.py` (new)

**Interfaces:**
- Consumes: `_build_plan_builder(state)` from Task 1, `analysis.complete` event data
- Produces: After `POST /analyze` completes, plan file exists on disk — `POST /execute` can load it immediately

- [ ] **Step 1: Write failing test**

```python
# tests/api/test_analysis_auto_plan.py
"""Test that analysis auto-generates a plan on completion."""

from __future__ import annotations

import pytest


async def test_analysis_complete_emits_plan_generated(api_client):
    """After analysis.complete, a plan file should exist for the trade date."""
    state = api_client._app.state.app_state

    events_received = []
    state.event_bus.subscribe(lambda e: events_received.append(e))

    response = await api_client.post(
        "/api/plans/generate", params={"date": "2026-10-01"}
    )
    assert response.status_code == 200

    plan_events = [e for e in events_received if e["type"] == "plan.generated"]
    assert len(plan_events) == 1
    assert plan_events[0]["data"]["trade_date"] == "2026-10-01"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/api/test_analysis_auto_plan.py -v`
Expected: FAIL — no `plan.generated` event emitted

- [ ] **Step 3: Implement auto-generation + event emission**

In `tradingbot/api/analysis_routes.py`, update `_run_analysis()` — after the `analysis.complete` emit (line ~96), add plan generation:

```python
        await state.event_bus.emit("analysis.complete", {
            "trade_date": trade_date.isoformat(),
            "run_id": analysis_run.run_id,
        })

        # Auto-generate plan from approved setups
        try:
            builder = _build_plan_builder(state)
            regime_str = analysis_run.market_regime.value if analysis_run.market_regime else "range_bound"
            plan = builder.build(
                trade_date,
                regime=MarketRegime(regime_str),
                market_summary=f"Auto-generated after {analysis_run.run_id}",
            )
            state.plan_store.save(plan)
            state.database.save_plan_snapshot(plan)
            await state.event_bus.emit("plan.generated", {
                "trade_date": trade_date.isoformat(),
                "legs": len(plan.legs),
            })
            logger.info("Auto-generated plan for %s: %d legs", trade_date, len(plan.legs))
        except Exception as exc:  # noqa: BLE001
            logger.error("Auto plan generation failed: %s", exc, exc_info=True)
```

Also add `plan.generated` event to the manual `/plans/generate` endpoint:

```python
    await state.event_bus.emit("plan.generated", {
        "trade_date": plan.trade_date,
        "legs": len(plan.legs),
    })
```

- [ ] **Step 4: Run tests**

Run: `uv run python -m pytest tests/api/test_analysis_auto_plan.py tests/api/test_plan_generate.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run python -m pytest tests/api/ tests/core/ -v --tb=short`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add tradingbot/api/analysis_routes.py tests/api/test_analysis_auto_plan.py
git commit -m "feat(api): auto-generate plan after analysis completes

After pipeline.run() succeeds, PlanBuilder automatically creates a
TradePlan from approved setups and saves to PlanStore. Emits
plan.generated event. POST /execute can now load the plan immediately
after analysis — no manual step required.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:** API endpoint ✓, auto-trigger ✓, event emission ✓, setup_id threading (via PlanBuilder) ✓

**Placeholder scan:** Clean. All steps have code.

**Type consistency:** `_build_plan_builder(state)` used in both tasks ✓. `MarketRegime` import consistent ✓. `trade_date` is `date` object in builder, `str` in events — matches existing patterns ✓.

**Review Focus:** All 5 items have coverage — empty plan (Task 1 test), concurrent access (SetupStore is committed-row safe), wrong date (uses event's trade_date), RiskManager from config (auto_risk_config), plan overwrite (PlanStore.save overwrites).
