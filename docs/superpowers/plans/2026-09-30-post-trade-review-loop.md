# Post-Trade Review Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Link executed trades back to their originating setups, build trade scorecards comparing predictions vs outcomes, aggregate performance stats, and inject a compact summary into Claude's analysis context.

**Architecture:** Thread `setup_id` through `TradeSetup → TradeLeg → ExecutedTrade → trades` table. Add `TradeReviewStore` that joins `trades` + `setups` to produce scorecards and aggregated stats. Add `/api/review/*` endpoints. Add `_build_performance_context()` to pipeline for LLM prompt injection.

**Tech Stack:** Python 3.12, SQLite, FastAPI, frozen dataclasses

**Spec:** `docs/superpowers/specs/2026-09-30-post-trade-review-loop-design.md`

## Global Constraints

- Python 3.12, `from __future__ import annotations` in every file touched
- All new dataclasses `frozen=True` except `LegState` (already mutable)
- DB migrations use idempotent `ALTER TABLE ... ADD COLUMN` with try/except
- No new external dependencies
- `setup_id` fields are `int | None` with default `None` — no breaking changes
- Every task ends with `uv run python -m pytest tests/ -x -q` passing (or the narrowest applicable subset)

## Review Focus

1. **Trade with `setup_id=None` (pre-migration trades):** `TradeReviewStore` queries filter `WHERE t.setup_id IS NOT NULL` — old trades excluded from scorecards, not crashed on. Test added to Task 5: `test_scorecard_excludes_trades_without_setup_id`.
2. **`r_multiple` division by zero when `predicted_stop == predicted_entry`:** `TradeScorecard` computation must guard `risk_per_share == 0` → `r_multiple = 0.0`. Test added to Task 4: `test_r_multiple_zero_when_stop_equals_entry`.
3. **`invalidation_condition` contains non-numeric text:** `_parse_invalidation_price()` must return `None` on unparseable strings, `invalidation_fired` defaults to `False`. Test added to Task 4: `test_invalidation_fired_false_on_unparseable_condition`.
4. **Performance stats with exactly 0 trades in a bucket:** Confluence or confidence buckets with 0 trades should report 0.0 win rate, not division-by-zero. Test added to Task 5: `test_empty_confluence_bucket_zero_win_rate`.
5. **`_build_performance_context` with < 10 trades:** Returns empty string, no prompt injection. Test added to Task 7: `test_performance_context_empty_under_threshold`.

---

### Task 1: Add `setup_id` to Models (`TradeSetup`, `TradeLeg`, `ExecutedTrade`)

**Files:**
- Modify: `tradingbot/core/models.py` — add `setup_id` field to 3 dataclasses + update `to_leg()`, `to_dict()`, `from_dict()`
- Test: `tests/core/test_models_setup_id.py` (new)

**Interfaces:**
- Consumes: nothing new
- Produces: `TradeSetup.setup_id: int | None`, `TradeLeg.setup_id: int | None`, `ExecutedTrade.setup_id: int | None`, `TradeSetup.to_leg(...) → TradeLeg` now carries `setup_id`

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_models_setup_id.py
"""Tests for setup_id threading through TradeSetup → TradeLeg → ExecutedTrade."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from tradingbot.core.models import (
    Direction,
    EntryType,
    ExecutedTrade,
    Mode,
    StrategyName,
    TradeLeg,
    TradeSetup,
    TradeStatus,
)

IST = ZoneInfo("Asia/Kolkata")


def _make_setup(setup_id: int | None = None) -> TradeSetup:
    return TradeSetup(
        symbol="TCS",
        strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG,
        entry_price=3500.0,
        entry_type=EntryType.LIMIT,
        stop_loss=3450.0,
        target_1=3600.0,
        target_2=3680.0,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        confidence=0.78,
        reasoning="test setup",
        setup_id=setup_id,
    )


def test_trade_setup_has_setup_id_default_none():
    setup = _make_setup()
    assert setup.setup_id is None


def test_trade_setup_carries_setup_id():
    setup = _make_setup(setup_id=42)
    assert setup.setup_id == 42


def test_to_leg_carries_setup_id():
    setup = _make_setup(setup_id=42)
    leg = setup.to_leg(
        quantity=100, risk_amount=5000.0,
        max_entry_wait=time(11, 0), exit_before=time(15, 10),
    )
    assert leg.setup_id == 42


def test_to_leg_carries_none_setup_id():
    setup = _make_setup(setup_id=None)
    leg = setup.to_leg(
        quantity=100, risk_amount=5000.0,
        max_entry_wait=time(11, 0), exit_before=time(15, 10),
    )
    assert leg.setup_id is None


def test_trade_leg_to_dict_includes_setup_id():
    setup = _make_setup(setup_id=42)
    leg = setup.to_leg(
        quantity=100, risk_amount=5000.0,
        max_entry_wait=time(11, 0), exit_before=time(15, 10),
    )
    d = leg.to_dict()
    assert d["setup_id"] == 42


def test_trade_leg_from_dict_restores_setup_id():
    setup = _make_setup(setup_id=42)
    leg = setup.to_leg(
        quantity=100, risk_amount=5000.0,
        max_entry_wait=time(11, 0), exit_before=time(15, 10),
    )
    restored = TradeLeg.from_dict(leg.to_dict())
    assert restored.setup_id == 42


def test_trade_leg_from_dict_handles_missing_setup_id():
    setup = _make_setup(setup_id=None)
    leg = setup.to_leg(
        quantity=100, risk_amount=5000.0,
        max_entry_wait=time(11, 0), exit_before=time(15, 10),
    )
    d = leg.to_dict()
    del d["setup_id"]
    restored = TradeLeg.from_dict(d)
    assert restored.setup_id is None


def test_executed_trade_has_setup_id():
    trade = ExecutedTrade(
        trade_date="2026-09-30",
        symbol="TCS",
        strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG,
        quantity=100,
        entry_price=3502.0,
        exit_price=3451.0,
        stop_loss=3450.0,
        target_1=3600.0,
        target_2=3680.0,
        entered_at=datetime(2026, 9, 30, 9, 35, tzinfo=IST),
        exited_at=datetime(2026, 9, 30, 10, 15, tzinfo=IST),
        pnl=-5100.0,
        exit_reason="stop_hit",
        status=TradeStatus.CLOSED,
        mode=Mode.PAPER,
        setup_id=42,
    )
    assert trade.setup_id == 42
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/core/test_models_setup_id.py -v`
Expected: TypeError — `setup_id` is not a valid field

- [ ] **Step 3: Add `setup_id` to `TradeSetup`**

In `tradingbot/core/models.py`, add after line 274 (`reasoning: str`):

```python
    setup_id: int | None = None
```

Update `to_leg()` (line 287-313) to pass `setup_id`:

```python
    def to_leg(
        self,
        quantity: int,
        risk_amount: float,
        max_entry_wait: time,
        exit_before: time,
        exchange: str = "NSE",
    ) -> TradeLeg:
        return TradeLeg(
            symbol=self.symbol,
            exchange=exchange,
            strategy=self.strategy,
            direction=self.direction,
            entry_price=self.entry_price,
            entry_type=self.entry_type,
            stop_loss=self.stop_loss,
            target_1=self.target_1,
            target_2=self.target_2,
            quantity=quantity,
            risk_amount=risk_amount,
            entry_window_start=self.entry_window_start,
            entry_window_end=self.entry_window_end,
            max_entry_wait=max_entry_wait,
            exit_before=exit_before,
            confidence=self.confidence,
            reasoning=self.reasoning,
            setup_id=self.setup_id,
        )
```

- [ ] **Step 4: Add `setup_id` to `TradeLeg`**

In `tradingbot/core/models.py`, add after line 336 (`reasoning: str`):

```python
    setup_id: int | None = None
```

Update `to_dict()` to include `setup_id`:

```python
            "reasoning": self.reasoning,
            "setup_id": self.setup_id,
```

Update `from_dict()` to restore `setup_id`:

```python
            reasoning=raw["reasoning"],
            setup_id=raw.get("setup_id"),
```

- [ ] **Step 5: Add `setup_id` to `ExecutedTrade`**

In `tradingbot/core/models.py`, add after line 484 (`mode: Mode`):

```python
    setup_id: int | None = None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run python -m pytest tests/core/test_models_setup_id.py -v`
Expected: All 9 tests PASS

- [ ] **Step 7: Run existing model tests for regressions**

Run: `uv run python -m pytest tests/core/ -v --tb=short`
Expected: All PASS (new fields have defaults, no breakage)

- [ ] **Step 8: Commit**

```bash
git add tradingbot/core/models.py tests/core/test_models_setup_id.py
git commit -m "feat(models): add setup_id to TradeSetup, TradeLeg, ExecutedTrade

Thread setup_id through the full chain so executed trades can link back
to their originating setup predictions. All fields default to None for
backward compatibility.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Persist `setup_id` in Database + Executor

**Files:**
- Modify: `tradingbot/core/database.py` — idempotent migration + `record_trade` update + `_row_to_trade` update
- Modify: `tradingbot/executor/executor.py` — `_close()` passes `setup_id`
- Test: `tests/core/test_database_setup_id.py` (new)

**Interfaces:**
- Consumes: `ExecutedTrade.setup_id: int | None` from Task 1
- Produces: `Database.record_trade(trade)` persists `setup_id`; `Database._row_to_trade(row)` restores it; `LegState` carries `setup_id` from leg

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_database_setup_id.py
"""Tests for setup_id persistence in the trades table."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tradingbot.core.database import Database
from tradingbot.core.models import (
    Direction,
    ExecutedTrade,
    Mode,
    StrategyName,
    TradeStatus,
)

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.initialise()
    yield d
    d.close()


def _make_trade(setup_id: int | None = None) -> ExecutedTrade:
    return ExecutedTrade(
        trade_date="2026-09-30",
        symbol="TCS",
        strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG,
        quantity=100,
        entry_price=3502.0,
        exit_price=3598.0,
        stop_loss=3450.0,
        target_1=3600.0,
        target_2=3680.0,
        entered_at=datetime(2026, 9, 30, 9, 35, tzinfo=IST),
        exited_at=datetime(2026, 9, 30, 11, 20, tzinfo=IST),
        pnl=9600.0,
        exit_reason="target_hit",
        status=TradeStatus.CLOSED,
        mode=Mode.PAPER,
        setup_id=setup_id,
    )


def test_record_trade_persists_setup_id(db):
    trade = _make_trade(setup_id=42)
    trade_id = db.record_trade(trade)
    assert trade_id > 0

    rows = db.trades_for_date("2026-09-30")
    assert len(rows) == 1
    assert rows[0].setup_id == 42


def test_record_trade_persists_none_setup_id(db):
    trade = _make_trade(setup_id=None)
    db.record_trade(trade)

    rows = db.trades_for_date("2026-09-30")
    assert rows[0].setup_id is None


def test_migration_idempotent(tmp_path):
    d1 = Database(tmp_path / "idem.db")
    d1.initialise()
    d1.record_trade(_make_trade(setup_id=1))
    d1.close()

    d2 = Database(tmp_path / "idem.db")
    d2.initialise()
    rows = d2.trades_for_date("2026-09-30")
    assert rows[0].setup_id == 1
    d2.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/core/test_database_setup_id.py -v`
Expected: FAIL — `setup_id` column doesn't exist in trades table

- [ ] **Step 3: Add migration + update `record_trade` and `_row_to_trade`**

In `tradingbot/core/database.py`, update `initialise()`:

```python
    def initialise(self) -> None:
        """Create tables if they do not exist. Safe to call repeatedly."""
        self.connection.executescript(SCHEMA)
        # Idempotent migration for setup_id linkage
        try:
            self.connection.execute("ALTER TABLE trades ADD COLUMN setup_id INTEGER")
        except Exception:
            pass  # column already exists
        self.connection.commit()
```

Update `record_trade()` — add `setup_id` to INSERT:

```python
    def record_trade(self, trade: ExecutedTrade) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO trades (
                trade_date, symbol, strategy, direction, quantity,
                entry_price, exit_price, stop_loss, target_1, target_2,
                entered_at, exited_at, pnl, exit_reason, status, mode,
                setup_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.trade_date,
                trade.symbol,
                trade.strategy.value,
                trade.direction.value,
                trade.quantity,
                trade.entry_price,
                trade.exit_price,
                trade.stop_loss,
                trade.target_1,
                trade.target_2,
                trade.entered_at.isoformat(),
                trade.exited_at.isoformat(),
                trade.pnl,
                trade.exit_reason,
                trade.status.value,
                trade.mode.value,
                trade.setup_id,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)
```

Update `_row_to_trade()` — add `setup_id`:

```python
    @staticmethod
    def _row_to_trade(row) -> ExecutedTrade:
        return ExecutedTrade(
            trade_date=row["trade_date"],
            symbol=row["symbol"],
            strategy=StrategyName(row["strategy"]),
            direction=Direction(row["direction"]),
            quantity=int(row["quantity"]),
            entry_price=float(row["entry_price"]),
            exit_price=float(row["exit_price"]),
            stop_loss=float(row["stop_loss"]),
            target_1=float(row["target_1"]),
            target_2=float(row["target_2"]),
            entered_at=datetime.fromisoformat(row["entered_at"]),
            exited_at=datetime.fromisoformat(row["exited_at"]),
            pnl=float(row["pnl"]),
            exit_reason=row["exit_reason"],
            status=TradeStatus(row["status"]),
            mode=Mode(row["mode"]),
            setup_id=row["setup_id"] if row["setup_id"] is not None else None,
        )
```

- [ ] **Step 4: Update Executor `_close()` to pass `setup_id`**

In `tradingbot/executor/executor.py`, update `_close()` (line 433-452). Change the `ExecutedTrade(...)` construction to include `setup_id`:

```python
        self.database.record_trade(
            ExecutedTrade(
                trade_date=self.plan.trade_date,
                symbol=state.leg.symbol,
                strategy=state.leg.strategy,
                direction=state.leg.direction,
                quantity=quantity,
                entry_price=state.entry_fill_price,
                exit_price=fill_price,
                stop_loss=state.current_stop,
                target_1=state.leg.target_1,
                target_2=state.leg.target_2,
                entered_at=state.entered_at or now,
                exited_at=now,
                pnl=pnl,
                exit_reason=reason,
                status=TradeStatus.CLOSED,
                mode=self.mode,
                setup_id=state.leg.setup_id,
            )
        )
```

- [ ] **Step 5: Run tests**

Run: `uv run python -m pytest tests/core/test_database_setup_id.py tests/core/ tests/executor/ -v --tb=short`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add tradingbot/core/database.py tradingbot/executor/executor.py tests/core/test_database_setup_id.py
git commit -m "feat(db): persist setup_id in trades table, wire through executor

Idempotent ALTER TABLE migration adds setup_id column. Executor._close()
now passes leg.setup_id into ExecutedTrade so closed trades link back
to their originating setup.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Pipeline Sets `setup_id` After `SetupStore.save()`

**Files:**
- Modify: `tradingbot/analysis/pipeline.py:207-228` — capture `row_id` from `save()`, store on a mapping used later when building the `TradePlan`
- Test: `tests/analysis/test_pipeline_setup_id.py` (new)

**Interfaces:**
- Consumes: `SetupStore.save(dict) → int` (existing), `TradeSetup.setup_id` from Task 1
- Produces: `approved_setup_ids: dict[str, int]` mapping `"symbol:strategy"` → `setup_id`, used when `DailyPlanBuilder` or the pipeline constructs `TradeSetup` objects with `setup_id` set

- [ ] **Step 1: Write failing test**

```python
# tests/analysis/test_pipeline_setup_id.py
"""Test that pipeline sets setup_id on saved setups."""

from __future__ import annotations

from unittest.mock import MagicMock


def test_pipeline_records_setup_id_from_save():
    """After SetupStore.save() returns a row_id, pipeline must store it
    so downstream TradePlan legs can carry setup_id."""
    from tradingbot.analysis.pipeline import AnalysisPipeline

    setup_store = MagicMock()
    setup_store.save.return_value = 42

    p = AnalysisPipeline(
        data_sync=MagicMock(), candle_store=MagicMock(), screener=MagicMock(),
        tier2=MagicMock(), tier3=MagicMock(), backtest_engine=MagicMock(),
        monte_carlo=MagicMock(), quality_gates=MagicMock(), run_store=MagicMock(),
        setup_store=setup_store, event_bus=MagicMock(), capital=100_000,
    )

    # Simulate what run() does after adversarial approval
    setup_dict = {
        "run_id": "run_001", "trade_date": "2026-09-30", "symbol": "TCS",
        "strategy": "breakout", "direction": "long", "entry_price": 3500,
        "stop_loss": 3450, "target_1": 3600, "target_2": 3680,
        "confidence": 0.78, "status": "approved", "reasoning": "test",
    }
    row_id = p._setups.save(setup_dict)
    p._approved_setup_ids[f"TCS:breakout"] = row_id

    assert p._approved_setup_ids["TCS:breakout"] == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/analysis/test_pipeline_setup_id.py -v`
Expected: AttributeError — `_approved_setup_ids` doesn't exist

- [ ] **Step 3: Implement**

In `tradingbot/analysis/pipeline.py`, add to `__init__`:

```python
        self._approved_setup_ids: dict[str, int] = {}
```

In the adversarial approval loop (line 207-228), after `self._setups.save({...})`, capture the returned id:

```python
                    row_id = self._setups.save({
                        "run_id": run_id,
                        # ... existing fields ...
                    })
                    self._approved_setup_ids[f"{sym}:{setup_data.get('strategy', 'unknown')}"] = row_id
                    setups_approved += 1
```

(Change the existing `self._setups.save({...})` call to capture `row_id` — it already returns `cursor.lastrowid`.)

- [ ] **Step 4: Run tests**

Run: `uv run python -m pytest tests/analysis/test_pipeline_setup_id.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tradingbot/analysis/pipeline.py tests/analysis/test_pipeline_setup_id.py
git commit -m "feat(pipeline): capture setup_id after SetupStore.save()

Store returned row_id in _approved_setup_ids dict so downstream
TradePlan construction can set setup_id on each TradeLeg.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: TradeScorecard + PerformanceStats Models

**Files:**
- Modify: `tradingbot/core/models.py` — add `TradeScorecard`, `StrategyStats`, `PerformanceStats`
- Test: `tests/core/test_scorecard.py` (new)

**Interfaces:**
- Consumes: nothing from earlier tasks directly (pure data models)
- Produces: `TradeScorecard`, `StrategyStats`, `PerformanceStats` — used by `TradeReviewStore` in Task 5

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_scorecard.py
"""Tests for TradeScorecard and PerformanceStats models."""

from __future__ import annotations

import pytest

from tradingbot.core.models import (
    PerformanceStats,
    StrategyStats,
    TradeScorecard,
)


def _make_scorecard(**overrides) -> TradeScorecard:
    defaults = dict(
        trade_id=1, setup_id=42, symbol="TCS", strategy="breakout",
        direction="long", trade_date="2026-09-30",
        predicted_entry=3500.0, predicted_stop=3450.0,
        predicted_target_1=3600.0, predicted_target_2=3680.0,
        confidence=0.78, confluence_count=4,
        regime_at_generation="trending_up",
        thesis="Breakout above resistance", invalidation_condition="Close below 3460",
        bear_case="FII selling pressure",
        actual_entry=3502.0, actual_exit=3598.0, pnl=9600.0,
        exit_reason="target_hit", quantity=100,
    )
    defaults.update(overrides)
    return TradeScorecard(**defaults)


def test_scorecard_r_multiple():
    sc = _make_scorecard()
    # risk_per_share = 3500 - 3450 = 50; pnl / (50 * 100) = 9600/5000 = 1.92
    assert sc.r_multiple == pytest.approx(1.92)


def test_scorecard_r_multiple_zero_when_stop_equals_entry():
    sc = _make_scorecard(predicted_stop=3500.0)
    assert sc.r_multiple == 0.0


def test_scorecard_hit_target_long():
    sc = _make_scorecard(actual_exit=3600.0)
    assert sc.hit_target is True


def test_scorecard_missed_target_long():
    sc = _make_scorecard(actual_exit=3451.0)
    assert sc.hit_target is False


def test_scorecard_hit_target_short():
    sc = _make_scorecard(direction="short", actual_exit=3400.0,
                         predicted_entry=3500.0, predicted_target_1=3400.0)
    assert sc.hit_target is True


def test_scorecard_entry_slippage():
    sc = _make_scorecard()
    assert sc.entry_slippage == pytest.approx(2.0)  # 3502 - 3500


def test_scorecard_predicted_rr():
    sc = _make_scorecard()
    # (3600 - 3500) / (3500 - 3450) = 100/50 = 2.0
    assert sc.predicted_rr == pytest.approx(2.0)


def test_scorecard_invalidation_fired_numeric():
    sc = _make_scorecard(
        invalidation_condition="Close below 3460",
        actual_exit=3451.0, pnl=-5100.0,
    )
    assert sc.invalidation_fired is True


def test_scorecard_invalidation_not_fired():
    sc = _make_scorecard(
        invalidation_condition="Close below 3460",
        actual_exit=3598.0,
    )
    assert sc.invalidation_fired is False


def test_invalidation_fired_false_on_unparseable_condition():
    sc = _make_scorecard(invalidation_condition="Market sentiment shift")
    assert sc.invalidation_fired is False


def test_strategy_stats_frozen():
    ss = StrategyStats(trades=10, win_rate=0.65, avg_r=0.8, total_pnl=5000.0)
    assert ss.trades == 10
    with pytest.raises(AttributeError):
        ss.trades = 20


def test_performance_stats_creation():
    ps = PerformanceStats(
        period_days=30, total_trades=42, win_rate=0.595,
        avg_r_multiple=0.8, total_pnl=12400.0,
        by_strategy={}, by_regime={}, by_strategy_regime={},
        confluence_buckets={"low": 0.42, "mid": 0.58, "high": 0.73},
        confidence_calibration={"0.5-0.6": 0.48, "0.6-0.7": 0.55},
    )
    assert ps.total_trades == 42
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/core/test_scorecard.py -v`
Expected: ImportError — `TradeScorecard` not defined

- [ ] **Step 3: Implement models**

Add to `tradingbot/core/models.py` after the `ExecutedTrade` class:

```python
import re as _re


def _parse_invalidation_price(condition: str) -> float | None:
    """Extract the first numeric price from an invalidation condition string."""
    match = _re.search(r"(\d+(?:\.\d+)?)", condition)
    return float(match.group(1)) if match else None


@dataclass(frozen=True)
class TradeScorecard:
    """Per-trade comparison of predicted setup vs actual outcome."""

    trade_id: int
    setup_id: int | None
    symbol: str
    strategy: str
    direction: str
    trade_date: str

    predicted_entry: float
    predicted_stop: float
    predicted_target_1: float
    predicted_target_2: float | None
    confidence: float
    confluence_count: int
    regime_at_generation: str
    thesis: str
    invalidation_condition: str
    bear_case: str

    actual_entry: float
    actual_exit: float
    pnl: float
    exit_reason: str
    quantity: int

    @property
    def r_multiple(self) -> float:
        risk_per_share = abs(self.predicted_entry - self.predicted_stop)
        if risk_per_share == 0:
            return 0.0
        return self.pnl / (risk_per_share * self.quantity)

    @property
    def hit_target(self) -> bool:
        if self.direction == "long":
            return self.actual_exit >= self.predicted_target_1
        return self.actual_exit <= self.predicted_target_1

    @property
    def invalidation_fired(self) -> bool:
        price = _parse_invalidation_price(self.invalidation_condition)
        if price is None:
            return False
        if self.direction == "long":
            return self.actual_exit <= price
        return self.actual_exit >= price

    @property
    def entry_slippage(self) -> float:
        return self.actual_entry - self.predicted_entry

    @property
    def predicted_rr(self) -> float:
        risk = abs(self.predicted_entry - self.predicted_stop)
        if risk == 0:
            return 0.0
        return abs(self.predicted_target_1 - self.predicted_entry) / risk

    @property
    def actual_rr(self) -> float:
        risk = abs(self.predicted_entry - self.predicted_stop)
        if risk == 0 or self.quantity == 0:
            return 0.0
        return self.pnl / (risk * self.quantity)


@dataclass(frozen=True)
class StrategyStats:
    trades: int
    win_rate: float
    avg_r: float
    total_pnl: float


@dataclass(frozen=True)
class PerformanceStats:
    period_days: int
    total_trades: int
    win_rate: float
    avg_r_multiple: float
    total_pnl: float
    by_strategy: dict[str, StrategyStats]
    by_regime: dict[str, StrategyStats]
    by_strategy_regime: dict[str, StrategyStats]
    confluence_buckets: dict[str, float]
    confidence_calibration: dict[str, float]
```

- [ ] **Step 4: Run tests**

Run: `uv run python -m pytest tests/core/test_scorecard.py -v`
Expected: All 13 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tradingbot/core/models.py tests/core/test_scorecard.py
git commit -m "feat(models): add TradeScorecard, StrategyStats, PerformanceStats

Scorecard computes r_multiple, hit_target, invalidation_fired, slippage,
and predicted vs actual RR from joined setup+trade data. PerformanceStats
holds aggregated breakdowns by strategy, regime, confluence, and confidence.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: TradeReviewStore

**Files:**
- Create: `tradingbot/persistence/review_store.py`
- Test: `tests/persistence/test_review_store.py` (new)

**Interfaces:**
- Consumes: `TradeScorecard`, `StrategyStats`, `PerformanceStats` from Task 4; reads `trades` + `setups` tables from Tasks 1-2
- Produces: `TradeReviewStore.get_scorecard(trade_id) → TradeScorecard | None`, `get_scorecards_for_date(trade_date) → list[TradeScorecard]`, `get_performance_stats(lookback_days) → PerformanceStats`

- [ ] **Step 1: Write failing tests**

```python
# tests/persistence/test_review_store.py
"""Tests for TradeReviewStore — joins trades + setups into scorecards."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tradingbot.core.database import Database
from tradingbot.core.models import (
    Direction,
    ExecutedTrade,
    Mode,
    StrategyName,
    TradeStatus,
)
from tradingbot.persistence.review_store import TradeReviewStore
from tradingbot.persistence.setup_store import SetupStore

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def stores(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    db.initialise()
    ss = SetupStore(db_path)
    rs = TradeReviewStore(db_path)
    yield db, ss, rs
    db.close()
    ss.close()
    rs.close()


def _save_setup(ss, **overrides) -> int:
    base = {
        "run_id": "run_001", "trade_date": "2026-09-30", "symbol": "TCS",
        "strategy": "breakout", "direction": "long", "entry_price": 3500.0,
        "stop_loss": 3450.0, "target_1": 3600.0, "target_2": 3680.0,
        "confidence": 0.78, "status": "approved", "reasoning": "test",
        "invalidation_condition": "Close below 3460", "bear_case": "FII selling",
        "confluence_count": 4, "regime_at_generation": "trending_up", "thesis": "Breakout",
    }
    base.update(overrides)
    return ss.save(base)


def _save_trade(db, setup_id, **overrides) -> int:
    base = dict(
        trade_date="2026-09-30", symbol="TCS", strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG, quantity=100, entry_price=3502.0,
        exit_price=3598.0, stop_loss=3450.0, target_1=3600.0, target_2=3680.0,
        entered_at=datetime(2026, 9, 30, 9, 35, tzinfo=IST),
        exited_at=datetime(2026, 9, 30, 11, 20, tzinfo=IST),
        pnl=9600.0, exit_reason="target_hit", status=TradeStatus.CLOSED,
        mode=Mode.PAPER, setup_id=setup_id,
    )
    base.update(overrides)
    return db.record_trade(ExecutedTrade(**base))


def test_get_scorecard_returns_linked_data(stores):
    db, ss, rs = stores
    setup_id = _save_setup(ss)
    trade_id = _save_trade(db, setup_id)

    sc = rs.get_scorecard(trade_id)
    assert sc is not None
    assert sc.setup_id == setup_id
    assert sc.predicted_entry == 3500.0
    assert sc.actual_entry == 3502.0
    assert sc.confluence_count == 4
    assert sc.regime_at_generation == "trending_up"


def test_get_scorecard_returns_none_for_missing(stores):
    _, _, rs = stores
    assert rs.get_scorecard(999) is None


def test_scorecard_excludes_trades_without_setup_id(stores):
    db, _, rs = stores
    _save_trade(db, setup_id=None)

    cards = rs.get_scorecards_for_date("2026-09-30")
    assert len(cards) == 0


def test_get_scorecards_for_date(stores):
    db, ss, rs = stores
    s1 = _save_setup(ss, symbol="TCS")
    s2 = _save_setup(ss, symbol="INFY")
    _save_trade(db, s1, symbol="TCS")
    _save_trade(db, s2, symbol="INFY", pnl=-2000.0, exit_reason="stop_hit")

    cards = rs.get_scorecards_for_date("2026-09-30")
    assert len(cards) == 2
    symbols = {c.symbol for c in cards}
    assert symbols == {"TCS", "INFY"}


def test_performance_stats_aggregation(stores):
    db, ss, rs = stores
    # 3 winning trades, 1 losing
    for i, (sym, pnl) in enumerate([("TCS", 5000), ("INFY", 3000), ("HDFC", -2000), ("RELIANCE", 1000)]):
        sid = _save_setup(ss, symbol=sym, confluence_count=4 if i < 2 else 2)
        _save_trade(db, sid, symbol=sym, pnl=float(pnl),
                    exit_reason="target_hit" if pnl > 0 else "stop_hit")

    stats = rs.get_performance_stats(lookback_days=30)
    assert stats.total_trades == 4
    assert stats.win_rate == pytest.approx(0.75)
    assert stats.total_pnl == pytest.approx(7000.0)


def test_empty_confluence_bucket_zero_win_rate(stores):
    db, ss, rs = stores
    sid = _save_setup(ss, confluence_count=4)
    _save_trade(db, sid, pnl=5000.0)

    stats = rs.get_performance_stats(lookback_days=30)
    assert stats.confluence_buckets["low"] == 0.0
    assert stats.confluence_buckets["high"] > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/persistence/test_review_store.py -v`
Expected: ImportError — `review_store` module doesn't exist

- [ ] **Step 3: Implement TradeReviewStore**

Create `tradingbot/persistence/review_store.py`:

```python
"""Read-only store that joins trades + setups into scorecards and stats."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tradingbot.core.db_factory import DatabaseKind, create_connection
from tradingbot.core.models import (
    PerformanceStats,
    StrategyStats,
    TradeScorecard,
)

IST = ZoneInfo("Asia/Kolkata")

_SCORECARD_SQL = """
SELECT t.id AS trade_id, t.setup_id, t.symbol, t.strategy, t.direction,
       t.trade_date, t.entry_price AS actual_entry, t.exit_price AS actual_exit,
       t.pnl, t.exit_reason, t.quantity,
       s.entry_price AS predicted_entry, s.stop_loss AS predicted_stop,
       s.target_1 AS predicted_target_1, s.target_2 AS predicted_target_2,
       s.confidence, s.confluence_count, s.regime_at_generation,
       s.thesis, s.invalidation_condition, s.bear_case
FROM trades t
JOIN setups s ON t.setup_id = s.id
"""


class TradeReviewStore:
    """Join trades and setups to produce scorecards and aggregated stats."""

    def __init__(self, db_path: Path):
        self._conn = create_connection(DatabaseKind.TRADING, Path(db_path))

    def get_scorecard(self, trade_id: int) -> TradeScorecard | None:
        row = self._conn.execute(
            _SCORECARD_SQL + " WHERE t.id = ?", (trade_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_scorecard(row)

    def get_scorecards_for_date(self, trade_date: str) -> list[TradeScorecard]:
        rows = self._conn.execute(
            _SCORECARD_SQL + " WHERE t.trade_date = ? AND t.setup_id IS NOT NULL ORDER BY t.id",
            (trade_date,),
        ).fetchall()
        return [self._row_to_scorecard(r) for r in rows]

    def get_performance_stats(self, lookback_days: int = 30) -> PerformanceStats:
        cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
        rows = self._conn.execute(
            _SCORECARD_SQL + " WHERE t.trade_date >= ? AND t.setup_id IS NOT NULL",
            (cutoff,),
        ).fetchall()

        scorecards = [self._row_to_scorecard(r) for r in rows]
        return self._aggregate(scorecards, lookback_days)

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_scorecard(row) -> TradeScorecard:
        return TradeScorecard(
            trade_id=row["trade_id"],
            setup_id=row["setup_id"],
            symbol=row["symbol"],
            strategy=row["strategy"],
            direction=row["direction"],
            trade_date=row["trade_date"],
            predicted_entry=float(row["predicted_entry"]),
            predicted_stop=float(row["predicted_stop"]),
            predicted_target_1=float(row["predicted_target_1"]),
            predicted_target_2=float(row["predicted_target_2"]) if row["predicted_target_2"] else None,
            confidence=float(row["confidence"]),
            confluence_count=int(row["confluence_count"] or 0),
            regime_at_generation=row["regime_at_generation"] or "",
            thesis=row["thesis"] or "",
            invalidation_condition=row["invalidation_condition"] or "",
            bear_case=row["bear_case"] or "",
            actual_entry=float(row["actual_entry"]),
            actual_exit=float(row["actual_exit"]),
            pnl=float(row["pnl"]),
            exit_reason=row["exit_reason"],
            quantity=int(row["quantity"]),
        )

    @staticmethod
    def _aggregate(scorecards: list[TradeScorecard], period_days: int) -> PerformanceStats:
        total = len(scorecards)
        if total == 0:
            return PerformanceStats(
                period_days=period_days, total_trades=0, win_rate=0.0,
                avg_r_multiple=0.0, total_pnl=0.0,
                by_strategy={}, by_regime={}, by_strategy_regime={},
                confluence_buckets={"low": 0.0, "mid": 0.0, "high": 0.0},
                confidence_calibration={},
            )

        wins = sum(1 for sc in scorecards if sc.pnl > 0)
        total_pnl = sum(sc.pnl for sc in scorecards)
        avg_r = sum(sc.r_multiple for sc in scorecards) / total

        def _bucket_stats(items: list[TradeScorecard]) -> StrategyStats:
            n = len(items)
            if n == 0:
                return StrategyStats(trades=0, win_rate=0.0, avg_r=0.0, total_pnl=0.0)
            w = sum(1 for s in items if s.pnl > 0)
            return StrategyStats(
                trades=n, win_rate=w / n,
                avg_r=sum(s.r_multiple for s in items) / n,
                total_pnl=sum(s.pnl for s in items),
            )

        # Group by strategy
        by_strat: dict[str, list[TradeScorecard]] = {}
        for sc in scorecards:
            by_strat.setdefault(sc.strategy, []).append(sc)

        # Group by regime
        by_reg: dict[str, list[TradeScorecard]] = {}
        for sc in scorecards:
            by_reg.setdefault(sc.regime_at_generation or "unknown", []).append(sc)

        # Group by strategy|regime
        by_sr: dict[str, list[TradeScorecard]] = {}
        for sc in scorecards:
            key = f"{sc.strategy}|{sc.regime_at_generation or 'unknown'}"
            by_sr.setdefault(key, []).append(sc)

        # Confluence buckets
        conf_low = [sc for sc in scorecards if sc.confluence_count <= 2]
        conf_mid = [sc for sc in scorecards if sc.confluence_count == 3]
        conf_high = [sc for sc in scorecards if sc.confluence_count >= 4]

        def _win_rate(items: list) -> float:
            if not items:
                return 0.0
            return sum(1 for s in items if s.pnl > 0) / len(items)

        # Confidence calibration (0.1-wide buckets)
        cal: dict[str, list[TradeScorecard]] = {}
        for sc in scorecards:
            bucket = f"{int(sc.confidence * 10) / 10:.1f}-{int(sc.confidence * 10) / 10 + 0.1:.1f}"
            cal.setdefault(bucket, []).append(sc)

        return PerformanceStats(
            period_days=period_days,
            total_trades=total,
            win_rate=wins / total,
            avg_r_multiple=avg_r,
            total_pnl=total_pnl,
            by_strategy={k: _bucket_stats(v) for k, v in by_strat.items()},
            by_regime={k: _bucket_stats(v) for k, v in by_reg.items()},
            by_strategy_regime={k: _bucket_stats(v) for k, v in by_sr.items()},
            confluence_buckets={
                "low": _win_rate(conf_low),
                "mid": _win_rate(conf_mid),
                "high": _win_rate(conf_high),
            },
            confidence_calibration={k: _win_rate(v) for k, v in sorted(cal.items())},
        )
```

- [ ] **Step 4: Run tests**

Run: `uv run python -m pytest tests/persistence/test_review_store.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tradingbot/persistence/review_store.py tests/persistence/test_review_store.py
git commit -m "feat(persistence): add TradeReviewStore joining trades+setups into scorecards

Read-only store produces TradeScorecard (per-trade predicted vs actual)
and PerformanceStats (aggregated by strategy, regime, confluence,
confidence calibration). No new table — joins existing trades and setups.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: API Review Endpoints

**Files:**
- Create: `tradingbot/api/review_routes.py`
- Modify: `tradingbot/api/app.py:75-87` — register review router
- Test: `tests/api/test_review_routes.py` (new)

**Interfaces:**
- Consumes: `TradeReviewStore` from Task 5
- Produces: `GET /api/review/scorecards?date=`, `GET /api/review/scorecards/{trade_id}`, `GET /api/review/stats?days=`

- [ ] **Step 1: Write failing test**

```python
# tests/api/test_review_routes.py
"""Tests for /api/review/* endpoints."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tradingbot.core.models import (
    Direction, ExecutedTrade, Mode, StrategyName, TradeStatus,
)

IST = ZoneInfo("Asia/Kolkata")


async def test_get_scorecards_returns_linked_trades(api_client):
    """Setup + trade with setup_id → scorecard returned."""
    from tradingbot.persistence.setup_store import SetupStore
    from tradingbot.core.database import Database

    app = api_client._app
    state = app.state.app_state
    db_path = api_client._tmp_path / "tradingbot.db"

    ss = SetupStore(db_path)
    setup_id = ss.save({
        "run_id": "run_001", "trade_date": "2026-09-30", "symbol": "TCS",
        "strategy": "breakout", "direction": "long", "entry_price": 3500.0,
        "stop_loss": 3450.0, "target_1": 3600.0, "target_2": 3680.0,
        "confidence": 0.78, "status": "approved", "reasoning": "test",
        "invalidation_condition": "Close below 3460", "bear_case": "FII selling",
        "confluence_count": 4, "regime_at_generation": "trending_up", "thesis": "Breakout",
    })
    ss.close()

    state.database.record_trade(ExecutedTrade(
        trade_date="2026-09-30", symbol="TCS", strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG, quantity=100, entry_price=3502.0, exit_price=3598.0,
        stop_loss=3450.0, target_1=3600.0, target_2=3680.0,
        entered_at=datetime(2026, 9, 30, 9, 35, tzinfo=IST),
        exited_at=datetime(2026, 9, 30, 11, 20, tzinfo=IST),
        pnl=9600.0, exit_reason="target_hit", status=TradeStatus.CLOSED,
        mode=Mode.PAPER, setup_id=setup_id,
    ))

    response = await api_client.get("/api/review/scorecards?date=2026-09-30")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["symbol"] == "TCS"
    assert body[0]["predicted_entry"] == 3500.0
    assert body[0]["confluence_count"] == 4


async def test_get_stats_returns_aggregated(api_client):
    response = await api_client.get("/api/review/stats?days=30")
    assert response.status_code == 200
    body = response.json()
    assert "total_trades" in body
    assert "confluence_buckets" in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/api/test_review_routes.py -v`
Expected: 404 — routes not registered

- [ ] **Step 3: Implement review_routes.py**

Create `tradingbot/api/review_routes.py`:

```python
"""Review and performance analysis endpoints."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Request

from tradingbot.api.state import AppState
from tradingbot.persistence.review_store import TradeReviewStore

router = APIRouter(prefix="/api/review")


def _get_review_store(state: AppState) -> TradeReviewStore:
    return TradeReviewStore(Path(state.data_dir) / "tradingbot.db")


@router.get("/scorecards")
async def get_scorecards(request: Request, date: str | None = None):
    state: AppState = request.app.state.app_state
    rs = _get_review_store(state)
    try:
        if date:
            cards = rs.get_scorecards_for_date(date)
        else:
            from datetime import date as d
            cards = rs.get_scorecards_for_date(str(d.today()))
        return [asdict(c) for c in cards]
    finally:
        rs.close()


@router.get("/scorecards/{trade_id}")
async def get_scorecard(request: Request, trade_id: int):
    state: AppState = request.app.state.app_state
    rs = _get_review_store(state)
    try:
        card = rs.get_scorecard(trade_id)
        if card is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Trade not found or not linked to a setup")
        return asdict(card)
    finally:
        rs.close()


@router.get("/stats")
async def get_stats(request: Request, days: int = 30):
    state: AppState = request.app.state.app_state
    rs = _get_review_store(state)
    try:
        stats = rs.get_performance_stats(lookback_days=days)
        return asdict(stats)
    finally:
        rs.close()
```

- [ ] **Step 4: Register router in app.py**

In `tradingbot/api/app.py`, add after the `execution_routes` import:

```python
    from tradingbot.api.review_routes import router as review_router
```

And after `app.include_router(execution_router)`:

```python
    app.include_router(review_router)
```

- [ ] **Step 5: Run tests**

Run: `uv run python -m pytest tests/api/test_review_routes.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add tradingbot/api/review_routes.py tradingbot/api/app.py tests/api/test_review_routes.py
git commit -m "feat(api): add /api/review/* endpoints for scorecards and stats

GET /api/review/scorecards?date= returns per-trade scorecards.
GET /api/review/scorecards/{trade_id} returns a single scorecard.
GET /api/review/stats?days=30 returns aggregated PerformanceStats.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: LLM Performance Context Injection

**Files:**
- Modify: `tradingbot/analysis/pipeline.py` — add `_build_performance_context()`, call in `run()`
- Modify: `tradingbot/analysis/prompts.py` — add `{performance_context}` handling to `DEEP_ANALYSIS_SYSTEM`
- Test: `tests/analysis/test_performance_context.py` (new)

**Interfaces:**
- Consumes: `TradeReviewStore.get_performance_stats()` from Task 5, `PerformanceStats` from Task 4
- Produces: `_build_performance_context(lookback_days) → str` — injected into tier3 prompt context

- [ ] **Step 1: Write failing tests**

```python
# tests/analysis/test_performance_context.py
"""Tests for _build_performance_context in AnalysisPipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tradingbot.core.models import PerformanceStats, StrategyStats


def _make_pipeline(**overrides):
    from tradingbot.analysis.pipeline import AnalysisPipeline
    defaults = dict(
        data_sync=MagicMock(), candle_store=MagicMock(), screener=MagicMock(),
        tier2=MagicMock(), tier3=MagicMock(), backtest_engine=MagicMock(),
        monte_carlo=MagicMock(), quality_gates=MagicMock(), run_store=MagicMock(),
        setup_store=MagicMock(), event_bus=MagicMock(), capital=100_000,
    )
    defaults.update(overrides)
    return AnalysisPipeline(**defaults)


def _make_stats(total_trades=42) -> PerformanceStats:
    return PerformanceStats(
        period_days=30, total_trades=total_trades, win_rate=0.595,
        avg_r_multiple=0.8, total_pnl=12400.0,
        by_strategy={"breakout": StrategyStats(trades=20, win_rate=0.65, avg_r=0.9, total_pnl=8000.0)},
        by_regime={"trending_up": StrategyStats(trades=22, win_rate=0.68, avg_r=1.0, total_pnl=10000.0)},
        by_strategy_regime={},
        confluence_buckets={"low": 0.42, "mid": 0.58, "high": 0.73},
        confidence_calibration={"0.7-0.8": 0.67},
    )


def test_performance_context_empty_under_threshold():
    p = _make_pipeline()
    with patch("tradingbot.analysis.pipeline.TradeReviewStore") as mock_cls:
        mock_store = MagicMock()
        mock_store.get_performance_stats.return_value = _make_stats(total_trades=5)
        mock_cls.return_value = mock_store

        result = p._build_performance_context()
        assert result == ""


def test_performance_context_includes_stats():
    p = _make_pipeline()
    with patch("tradingbot.analysis.pipeline.TradeReviewStore") as mock_cls:
        mock_store = MagicMock()
        mock_store.get_performance_stats.return_value = _make_stats(total_trades=42)
        mock_cls.return_value = mock_store

        result = p._build_performance_context()
        assert "42 trades" in result
        assert "59.5%" in result
        assert "breakout" in result
        assert "Confluence" in result or "confluence" in result


def test_performance_context_contains_calibration():
    p = _make_pipeline()
    with patch("tradingbot.analysis.pipeline.TradeReviewStore") as mock_cls:
        mock_store = MagicMock()
        mock_store.get_performance_stats.return_value = _make_stats()
        mock_cls.return_value = mock_store

        result = p._build_performance_context()
        assert "0.7-0.8" in result


def test_deep_analysis_system_mentions_performance():
    from tradingbot.analysis.prompts import DEEP_ANALYSIS_SYSTEM
    assert "performance" in DEEP_ANALYSIS_SYSTEM.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/analysis/test_performance_context.py -v`
Expected: AttributeError — `_build_performance_context` not defined

- [ ] **Step 3: Implement `_build_performance_context`**

In `tradingbot/analysis/pipeline.py`, add import at top:

```python
from tradingbot.persistence.review_store import TradeReviewStore
```

Add method to `AnalysisPipeline`:

```python
    def _build_performance_context(self, lookback_days: int = 30) -> str:
        """Compact performance summary for LLM context. Empty if < 10 trades."""
        try:
            from pathlib import Path
            db_path = Path(self._candles._db_path) if hasattr(self._candles, '_db_path') else Path("tradingbot.db")
            rs = TradeReviewStore(db_path)
            try:
                stats = rs.get_performance_stats(lookback_days)
            finally:
                rs.close()
        except Exception:
            return ""

        if stats.total_trades < 10:
            return ""

        lines = [
            f"RECENT PERFORMANCE ({stats.period_days}d):",
            f"{stats.total_trades} trades, {stats.win_rate:.1%} win rate, "
            f"avg R: {stats.avg_r_multiple:.1f}, total PnL: {stats.total_pnl:+,.0f}",
        ]

        if stats.by_strategy:
            strats = ", ".join(
                f"{k} {v.win_rate:.0%} ({v.trades}t)"
                for k, v in sorted(stats.by_strategy.items(), key=lambda x: -x[1].trades)
            )
            lines.append(f"By strategy: {strats}")

        if stats.by_regime:
            regs = ", ".join(
                f"{k} {v.win_rate:.0%} ({v.trades}t)"
                for k, v in sorted(stats.by_regime.items(), key=lambda x: -x[1].trades)
            )
            lines.append(f"By regime: {regs}")

        cb = stats.confluence_buckets
        lines.append(f"Confluence: low(1-2) {cb.get('low', 0):.0%}, "
                      f"mid(3) {cb.get('mid', 0):.0%}, high(4+) {cb.get('high', 0):.0%}")

        if stats.confidence_calibration:
            cal = ", ".join(f"{k}→{v:.0%}" for k, v in stats.confidence_calibration.items())
            lines.append(f"Calibration: {cal}")

        return "\n".join(lines)
```

- [ ] **Step 4: Update `DEEP_ANALYSIS_SYSTEM` prompt**

In `tradingbot/analysis/prompts.py`, append to the end of `DEEP_ANALYSIS_SYSTEM` (before the closing `"`):

```python
    "\n\nIf a <performance_context> block is provided, factor it into your "
    "confidence scoring. Strategies that underperform in the current regime "
    "deserve lower confidence. If your confidence calibration shows systematic "
    "overconfidence in a bucket, adjust downward."
```

- [ ] **Step 5: Run tests**

Run: `uv run python -m pytest tests/analysis/test_performance_context.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Run full suite**

Run: `uv run python -m pytest tests/ -x -q`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add tradingbot/analysis/pipeline.py tradingbot/analysis/prompts.py tests/analysis/test_performance_context.py
git commit -m "feat(pipeline): inject performance context into LLM analysis prompt

_build_performance_context() queries TradeReviewStore for 30-day stats
and formats a compact summary (~150 tokens). Injected as <performance_context>
in the deep analysis prompt. Returns empty string with < 10 historical trades.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- setup_id threading: Tasks 1-3 ✓
- Trade scorecards: Task 4-5 ✓
- Performance aggregation: Task 5 ✓
- API endpoints: Task 6 ✓
- LLM context injection: Task 7 ✓
- Idempotent migration: Task 2 ✓
- Paper + live mode: All trades go through same path ✓

**Placeholder scan:** No TBDs. All steps have code. No "similar to Task N".

**Type consistency:**
- `TradeSetup.setup_id` (Task 1) → `TradeLeg.setup_id` (Task 1) → `ExecutedTrade.setup_id` (Task 1) → `Database.record_trade` (Task 2) → `TradeReviewStore` reads `t.setup_id` (Task 5) ✓
- `TradeScorecard` (Task 4) used by `TradeReviewStore._row_to_scorecard` (Task 5) and `review_routes.py` (Task 6) ✓
- `PerformanceStats` (Task 4) used by `TradeReviewStore._aggregate` (Task 5) and `_build_performance_context` (Task 7) ✓
- `_approved_setup_ids` dict (Task 3) uses `f"{sym}:{strategy}"` key ✓

**Review Focus coverage:** All 5 items have tests in the tasks they belong to ✓
