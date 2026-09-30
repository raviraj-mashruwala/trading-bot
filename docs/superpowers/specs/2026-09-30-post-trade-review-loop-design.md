# Post-Trade Review Loop — Design Spec

## Goal

Close the feedback loop between setup predictions and trade outcomes. Today, `SetupStore` (predictions) and the `trades` table (outcomes) are siloed with zero linkage — `setup_id` is never carried through the execution pipeline. This spec adds:

1. **setup_id threading** — carry `setup_id` from `SetupStore.save()` through `TradeSetup → TradeLeg → ExecutedTrade → trades` table
2. **Trade scorecards** — per-trade comparison of predicted vs actual outcomes
3. **Performance aggregation** — stats by strategy×regime, confluence vs win rate, confidence calibration
4. **LLM performance context** — compact stats summary injected into analysis prompt so Claude adjusts based on real track record

## Success Criteria

- Every closed trade links back to its originating setup via `setup_id`
- API returns scorecards showing predicted entry/stop/target vs actual fill/exit/pnl
- Aggregate stats show win rate breakdowns by strategy×regime, confluence level, and confidence bucket
- Analysis pipeline injects a ~150-token performance summary into Claude's context when ≥10 historical trades exist
- All migrations idempotent on existing databases
- Works for both paper and live mode trades

## Non-Goals

- Frontend dashboard UI (API only — frontend is a separate effort)
- Automated strategy parameter tuning based on results
- Real-time PnL streaming during trade execution (already exists in executor)

---

## Architecture

### Data Flow

```
SetupStore.save(setup_dict) → setup_id (int)
    ↓ set on TradeSetup
TradeSetup.to_leg(setup_id=setup_id, ...) → TradeLeg(setup_id=setup_id)
    ↓ carried through TradePlan
Executor._close(leg) → ExecutedTrade(setup_id=leg.setup_id)
    ↓ persisted
trades table (setup_id INTEGER → setups.id)
    ↓ joined at query time
TradeReviewStore → TradeScorecard / PerformanceStats
    ↓ formatted
AnalysisPipeline._build_performance_context() → prompt injection
```

### Existing Tables (unchanged except adding setup_id column to trades)

**setups** (owned by `SetupStore`):
- id, run_id, trade_date, symbol, strategy, direction
- entry_price, stop_loss, target_1, target_2, confidence
- status, reasoning, rejection_reason
- thesis, invalidation_condition, bear_case, confluence_count
- entry_trigger, regime_at_generation, timeframe_alignment
- created_at, updated_at

**trades** (owned by `Database`):
- id, trade_date, symbol, strategy, direction, quantity
- entry_price, exit_price, stop_loss, target_1, target_2
- entered_at, exited_at, pnl, exit_reason, status, mode
- **NEW: setup_id INTEGER** (nullable, no FK constraint — keeps migration simple)

**execution_decisions** (owned by `Database`):
- id, trade_date, timestamp, symbol, decision_type, reason
- momentum_snapshot, candle_snapshot, escalated, llm_response, outcome

---

## Component Design

### 1. setup_id Threading

**Models touched:**

- `TradeSetup` (`core/models.py`) — add `setup_id: int | None = None`
- `TradeSetup.to_leg()` — pass `setup_id` through to TradeLeg
- `TradeLeg` (`core/models.py`) — add `setup_id: int | None = None`
- `ExecutedTrade` (`core/models.py`) — add `setup_id: int | None = None`

**Persistence touched:**

- `Database.__init__()` (`core/database.py`) — idempotent `ALTER TABLE trades ADD COLUMN setup_id INTEGER`
- `Database.record_trade()` — include `setup_id` in INSERT

**Executor touched:**

- `Executor._close()` (`executor/executor.py`) — pass `state.setup_id` (from leg) into `ExecutedTrade`
- `LegState` (`executor/executor.py`) — carry `setup_id` from leg

**Pipeline touched:**

- `AnalysisPipeline.run()` (`analysis/pipeline.py`) — after `setup_store.save()` returns `row_id`, propagate to `TradeSetup` before `to_leg()` is called. The pipeline saves setups in the adversarial approval loop; the returned id must reach the `TradeSetup` object that later becomes a `TradeLeg`.

**All new fields are `None`-defaulted** so existing code paths that don't set `setup_id` continue working. No breaking changes.

### 2. TradeScorecard Model

Frozen dataclass in `core/models.py`:

```python
@dataclass(frozen=True)
class TradeScorecard:
    # Identity
    trade_id: int
    setup_id: int | None
    symbol: str
    strategy: str
    direction: str
    trade_date: str

    # Predicted (from setup)
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

    # Actual (from trade)
    actual_entry: float
    actual_exit: float
    pnl: float
    exit_reason: str
    quantity: int

    # Computed metrics
    r_multiple: float          # pnl / (risk_per_share * quantity)
    hit_target: bool           # exit_price reached target_1
    invalidation_fired: bool   # exit crossed invalidation_condition price
    entry_slippage: float      # actual_entry - predicted_entry
    predicted_rr: float        # (target_1 - entry) / (entry - stop)
    actual_rr: float           # pnl / risk_amount
```

### 3. PerformanceStats Model

Frozen dataclass in `core/models.py`:

```python
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
    by_strategy_regime: dict[str, StrategyStats]  # key: "momentum|trending_up"
    confluence_buckets: dict[str, float]           # "low": 0.42, "mid": 0.58, "high": 0.73
    confidence_calibration: dict[str, float]       # "0.5-0.6": 0.48, "0.6-0.7": 0.55, ...
```

### 4. TradeReviewStore

New file: `tradingbot/persistence/review_store.py`

No new table — reads from existing `trades` + `setups` via JOIN:

```sql
SELECT t.*, s.confidence, s.confluence_count, s.regime_at_generation,
       s.thesis, s.invalidation_condition, s.bear_case,
       s.entry_price AS predicted_entry, s.stop_loss AS predicted_stop,
       s.target_1 AS predicted_target_1, s.target_2 AS predicted_target_2
FROM trades t
LEFT JOIN setups s ON t.setup_id = s.id
WHERE t.trade_date = ? AND t.setup_id IS NOT NULL
```

**Methods:**

- `get_scorecard(trade_id: int) → TradeScorecard | None`
- `get_scorecards_for_date(trade_date: str) → list[TradeScorecard]`
- `get_performance_stats(lookback_days: int = 30) → PerformanceStats`

**Scorecard computation:**
- `r_multiple = pnl / (abs(predicted_entry - predicted_stop) * quantity)` — zero-safe
- `hit_target = (actual_exit >= predicted_target_1)` for longs, `<=` for shorts
- `invalidation_fired` — parse numeric price from `invalidation_condition` string if it contains a number, check if exit crossed it. If unparseable, `False`.
- `entry_slippage = actual_entry - predicted_entry`

**PerformanceStats aggregation:**
- Group scorecards by strategy, regime, strategy×regime
- Confluence buckets: low (1-2), mid (3), high (4+)
- Confidence calibration: 0.1-wide buckets from 0.5 to 1.0
- Win = `pnl > 0`

Constructor takes a DB connection (same factory pattern as other stores).

### 5. API Endpoints

New file: `tradingbot/api/review_routes.py`

| Endpoint | Method | Response |
|---|---|---|
| `/api/review/scorecards?date=YYYY-MM-DD` | GET | `list[TradeScorecard]` as JSON |
| `/api/review/scorecards/{trade_id}` | GET | Single `TradeScorecard` as JSON |
| `/api/review/stats?days=30` | GET | `PerformanceStats` as JSON |

Registered on the existing FastAPI app in `api/app.py`.

### 6. LLM Performance Context

New method on `AnalysisPipeline`:

`_build_performance_context(lookback_days: int = 30) → str`

- Calls `TradeReviewStore.get_performance_stats(lookback_days)`
- Returns empty string if `total_trades < 10` (not enough data)
- Formats a ~150-token block:

```
RECENT PERFORMANCE (30d):
42 trades, 59.5% win rate, avg R: 0.8, total PnL: +₹12,400
By strategy: momentum 65% (20t), breakout 52% (15t), vwap_bounce 57% (7t)
By regime: trending_up 68% (22t), range_bound 45% (12t), volatile 50% (8t)
Confluence: low(1-2) 42%, mid(3) 58%, high(4+) 73%
Calibration: 0.5-0.6→48%, 0.6-0.7→55%, 0.7-0.8→67%, 0.8+→78%
NOTE: momentum in range_bound underperforms (38%). Confidence bucket 0.8+ overcalibrated (predicted 85%, actual 78%).
```

**Injection point:** Added as `<performance_context>` block in the deep analysis system prompt (`prompts.py`). The prompt text tells Claude to factor this into confidence scoring and strategy selection.

**Called from:** `AnalysisPipeline.run()`, at the start, before tier2/tier3. The string is passed through to `tier3.deep_analyze()` as a new `performance_context` parameter.

---

## Migration Strategy

All schema changes use idempotent `ALTER TABLE ... ADD COLUMN` wrapped in try/except (same pattern as existing `SetupStore` migration). Safe to run on existing databases with historical data — new columns default to NULL, and trades recorded before this change simply have `setup_id = NULL` (excluded from scorecard queries via `WHERE setup_id IS NOT NULL`).

## Testing Strategy

- Unit tests for each model's computed fields (r_multiple, hit_target, invalidation_fired)
- Unit tests for TradeReviewStore with in-memory SQLite (insert known setups + trades, verify scorecard fields)
- Unit tests for PerformanceStats aggregation (known distribution → verify buckets)
- Integration test: pipeline saves setup → executor closes trade → review store returns linked scorecard
- Test that `_build_performance_context` returns empty string with < 10 trades
- Test idempotent migration (create store twice on same DB)

## File Map

| File | Action |
|---|---|
| `tradingbot/core/models.py` | Modify — add setup_id to TradeSetup, TradeLeg, ExecutedTrade; add TradeScorecard, StrategyStats, PerformanceStats |
| `tradingbot/core/database.py` | Modify — ALTER TABLE migration + record_trade includes setup_id |
| `tradingbot/core/risk_manager.py` | No change — setup_id flows through to_leg() automatically |
| `tradingbot/executor/executor.py` | Modify — LegState carries setup_id, _close() passes it to ExecutedTrade |
| `tradingbot/persistence/setup_store.py` | No change — already returns row_id from save() |
| `tradingbot/persistence/review_store.py` | Create — TradeReviewStore with scorecard + stats queries |
| `tradingbot/analysis/pipeline.py` | Modify — set setup_id after save(), add _build_performance_context() |
| `tradingbot/analysis/prompts.py` | Modify — add performance_context placeholder to DEEP_ANALYSIS_SYSTEM |
| `tradingbot/api/review_routes.py` | Create — /api/review/* endpoints |
| `tradingbot/api/app.py` | Modify — register review_routes router |
