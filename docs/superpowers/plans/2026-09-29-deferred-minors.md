# Deferred Minors Cleanup Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three deferred minor findings from the pipeline-intelligence-gaps review: redundant candle reads in `_run_backtests`, four hardcoded `datetime(2025, 1, 1)` start dates, and a weak test assertion.

**Architecture:** All changes are in `tradingbot/analysis/pipeline.py` and `tradingbot/api/analysis_routes.py` for the runtime fixes, and `tests/analysis/test_pipeline.py` for the test fix. No new files. No new dependencies. Tasks are independent — Task 3 (test assertion) can ship first with zero risk.

**Tech Stack:** Python 3.12, existing `BacktestConfig.lookback_days` from `tradingbot/core/config.py`, `CandleStore.read`.

**Spec:** `docs/superpowers/plans/2026-09-29-deferred-minors.md` (this file)

## Global Constraints

- Python 3.12, `from __future__ import annotations` in every file touched
- No new dependencies
- `AnalysisPipeline.__init__` signature change must be backward-compatible (new param is keyword-only with default)
- `analysis_routes.py` constructs `AnalysisPipeline` — must pass `lookback_days` from `config.backtest.lookback_days`
- `BacktestConfig.lookback_days` default is `365` (from `config.toml` via `backtest_raw.get("lookback_days", 365)`)
- Every task ends with `pytest tests/analysis/ -x -q` passing

## Review Focus

- **`lookback_days=0`:** Rolling lookback of 0 days produces `from_dt == now` — candle read returns empty df. All four methods must handle empty df gracefully (they already do via existing guards — verify no new crash path opened).
- **`lookback_days` not passed by API route:** `AnalysisPipeline` must default to 365 so existing tests and any call site that omits it still works correctly.
- **Single candle read, empty result:** `_run_backtests` reads once before the loop — if the df is empty, no strategy runs. Verify the `len(df) == 0` guard fires correctly and `results` stays empty.
- **`datetime(2025, 1, 1)` removal in `_compute_nifty_5d_change_from_store`:** This method only needs ~10 days of data. Using `lookback_days` (up to 365) is more data than needed but harmless — verify no performance regression assumption is introduced.
- **Test assertion tightening:** Strengthened assertion must still pass when `InsufficientDataError` is raised (not just empty df). Both branches produce `"insufficient"` in the fallback string — verify.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `tradingbot/analysis/pipeline.py` | Modify | Tasks 1 + 2: read-once + rolling lookback |
| `tradingbot/api/analysis_routes.py` | Modify | Task 2: pass `lookback_days` at construction |
| `tests/analysis/test_pipeline.py` | Modify | Tasks 1 + 2 + 3: new tests + strengthened assertion |

---

## Task 1: Read Candles Once Per Symbol in `_run_backtests`

**Files:**
- Modify: `tradingbot/analysis/pipeline.py` — `_run_backtests` method
- Modify: `tests/analysis/test_pipeline.py`

**Interfaces:**
- Produces: no change to `_run_backtests` external signature — same `(symbol, results, regime)` → `None`

- [ ] **Step 1.1: Write failing test**

```python
# tests/analysis/test_pipeline.py — add after existing _run_backtests test

def test_run_backtests_reads_candles_once_not_per_strategy(pipeline_deps):
    """candle_store.read must be called exactly once per symbol, not once per strategy."""
    from tradingbot.backtest.walk_forward import WalkForwardEngine

    wf = MagicMock(spec=WalkForwardEngine)
    mock_report = MagicMock()
    mock_report.total_trades = 0   # gate rejects — not the point
    wf.run.return_value = mock_report

    pipeline_deps["backtest_engine"] = wf
    pipeline_deps["candle_store"].read.return_value = _make_candle_df(300)

    p = AnalysisPipeline(**pipeline_deps)
    results = []
    p._run_backtests("TCS", results, regime={"regime": "trending_up"})

    # trending_up has 5 eligible strategies — read must still be called only once
    read_calls = [
        c for c in pipeline_deps["candle_store"].read.call_args_list
        if c.args[0] == "TCS" and c.args[1] == "15minute"
    ]
    assert len(read_calls) == 1, (
        f"Expected 1 candle read for TCS/15minute, got {len(read_calls)}"
    )
```

- [ ] **Step 1.2: Run to confirm failure**

```bash
source .venv/bin/activate && pytest tests/analysis/test_pipeline.py::test_run_backtests_reads_candles_once_not_per_strategy -x -q
```
Expected: `FAILED` — `assert 1 == 1` passes only if read was already once, else fails with count = 5.

- [ ] **Step 1.3: Move candle read outside the strategy loop**

In `tradingbot/analysis/pipeline.py`, replace `_run_backtests`:

```python
    def _run_backtests(self, symbol: str, results: list, regime: dict | None = None) -> None:
        """Run backtest for regime-eligible strategies on one symbol.

        Reads candles once outside the strategy loop. Uses self._backtest
        (injected WalkForwardEngine). Appends passing BacktestReports to results.
        """
        from tradingbot.strategy.strategies import STRATEGY_REGISTRY

        eligible = self._get_regime_eligible_strategies(regime or {})

        from_dt = datetime.now(tz=IST) - __import__("datetime").timedelta(days=self._lookback_days)
        df = self._candles.read(symbol, "15minute", from_dt, datetime.now(tz=IST))
        if len(df) == 0:
            return

        for strategy_name, strategy in STRATEGY_REGISTRY.items():
            if strategy_name not in eligible:
                continue
            report = self._backtest.run(symbol, df, strategy)
            if report.total_trades >= 5:
                trade_pnls = (
                    [report.avg_winner] * report.winners
                    + [report.avg_loser] * report.losers
                )
                mc = self._mc.run(trade_pnls) if trade_pnls else None
                gate = self._gates.evaluate(report, mc)
                if gate.passed:
                    results.append(report)
```

**Note:** `self._lookback_days` is added in Task 2. For Task 1 alone, use a temporary constant:

```python
        from_dt = datetime.now(tz=IST) - __import__("datetime").timedelta(days=365)
```

Then Task 2 replaces it with `self._lookback_days`.

- [ ] **Step 1.4: Run test**

```bash
source .venv/bin/activate && pytest tests/analysis/test_pipeline.py::test_run_backtests_reads_candles_once_not_per_strategy -x -q
```
Expected: PASS.

- [ ] **Step 1.5: Full analysis suite**

```bash
source .venv/bin/activate && pytest tests/analysis/ -x -q
```
Expected: all pass.

- [ ] **Step 1.6: Commit**

```bash
git add tradingbot/analysis/pipeline.py tests/analysis/test_pipeline.py
git commit -m "perf(pipeline): read candles once per symbol in _run_backtests

Previously candle_store.read was called inside the strategy loop — N reads
for N eligible strategies per symbol. Single read before the loop; all
strategies share the same DataFrame.

Co-Authored-By: Claude Sonnet 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Replace Hardcoded `datetime(2025, 1, 1)` with Rolling Lookback

**Files:**
- Modify: `tradingbot/analysis/pipeline.py` — `__init__`, `_run_backtests`, `_fetch_indicators_for_symbol`, `_drop_correlated_setups`, `_compute_nifty_5d_change_from_store`
- Modify: `tradingbot/api/analysis_routes.py` — `AnalysisPipeline(...)` constructor call
- Modify: `tests/analysis/test_pipeline.py`

**Interfaces:**
- Produces: `AnalysisPipeline.__init__` gains `lookback_days: int = 365` as keyword-only param with default
- Produces: `self._lookback_days: int` — used by all four methods above

- [ ] **Step 2.1: Write failing tests**

```python
# tests/analysis/test_pipeline.py — add after Task 1 test

def test_pipeline_accepts_lookback_days_param(pipeline_deps):
    """AnalysisPipeline must accept lookback_days kwarg without raising."""
    p = AnalysisPipeline(**pipeline_deps, lookback_days=90)
    assert p._lookback_days == 90


def test_run_backtests_uses_lookback_days_for_from_dt(pipeline_deps):
    """from_dt passed to candle_store.read must be approximately now - lookback_days."""
    from datetime import timedelta

    pipeline_deps["candle_store"].read.return_value = pd.DataFrame()
    p = AnalysisPipeline(**pipeline_deps, lookback_days=60)
    p._run_backtests("TCS", [], regime={"regime": "trending_up"})

    call = next(
        c for c in pipeline_deps["candle_store"].read.call_args_list
        if c.args[0] == "TCS" and c.args[1] == "15minute"
    )
    from_dt = call.args[2]
    expected_approx = datetime.now(tz=IST) - timedelta(days=60)
    delta = abs((from_dt - expected_approx).total_seconds())
    assert delta < 5, f"from_dt off by {delta:.1f}s — expected ~60 days ago"
```

- [ ] **Step 2.2: Run to confirm failure**

```bash
source .venv/bin/activate && pytest tests/analysis/test_pipeline.py -k "lookback" -x -q
```
Expected: `TypeError: __init__() got an unexpected keyword argument 'lookback_days'`

- [ ] **Step 2.3: Add `lookback_days` to `AnalysisPipeline.__init__`**

In `tradingbot/analysis/pipeline.py`, change `__init__` signature:

```python
    def __init__(
        self,
        data_sync: Any,
        candle_store: Any,
        screener: Any,
        tier2: Any,
        tier3: Any,
        backtest_engine: Any,
        monte_carlo: Any,
        quality_gates: Any,
        run_store: Any,
        setup_store: Any,
        event_bus: Any,
        capital: float,
        instrument_cache: Any = None,
        context_fetcher: Any = None,
        lookback_days: int = 365,
    ):
```

Add to the `__init__` body (after existing assignments):

```python
        self._lookback_days = lookback_days
```

- [ ] **Step 2.4: Replace all four hardcoded `datetime(2025, 1, 1)` with rolling lookback**

Pattern to apply in all four methods. Replace every:
```python
datetime(2025, 1, 1, tzinfo=IST)
```
With:
```python
datetime.now(tz=IST) - __import__("datetime").timedelta(days=self._lookback_days)
```

Wait — `datetime` is already imported at module level (`from datetime import date, datetime`). Use `timedelta` properly. Add `timedelta` to the existing import at the top of `pipeline.py`:

Current line 15:
```python
from datetime import date, datetime
```
Change to:
```python
from datetime import date, datetime, timedelta
```

Then replace all four occurrences:

**In `_compute_nifty_5d_change_from_store`** (line ~367):
```python
# Before:
            df = self._candles.read(
                "NIFTY 50", "day",
                datetime(2025, 1, 1, tzinfo=IST),
                datetime.now(tz=IST),
            )
# After:
            df = self._candles.read(
                "NIFTY 50", "day",
                datetime.now(tz=IST) - timedelta(days=self._lookback_days),
                datetime.now(tz=IST),
            )
```

**In `_fetch_indicators_for_symbol`** (line ~409):
```python
# Before:
            df = self._candles.read(
                symbol, "15minute",
                datetime(2025, 1, 1, tzinfo=IST),
                datetime.now(tz=IST),
            )
# After:
            df = self._candles.read(
                symbol, "15minute",
                datetime.now(tz=IST) - timedelta(days=self._lookback_days),
                datetime.now(tz=IST),
            )
```

**In `_drop_correlated_setups`** (line ~468):
```python
# Before:
                df = self._candles.read(
                    sym, "day",
                    datetime(2025, 1, 1, tzinfo=IST),
                    datetime.now(tz=IST),
                )
# After:
                df = self._candles.read(
                    sym, "day",
                    datetime.now(tz=IST) - timedelta(days=self._lookback_days),
                    datetime.now(tz=IST),
                )
```

**In `_run_backtests`** (already updated in Task 1 with the temporary 365 constant):
```python
# Replace the temporary constant from Task 1:
        from_dt = datetime.now(tz=IST) - timedelta(days=365)
# With:
        from_dt = datetime.now(tz=IST) - timedelta(days=self._lookback_days)
```

- [ ] **Step 2.5: Pass `lookback_days` in `analysis_routes.py`**

In `tradingbot/api/analysis_routes.py`, find the `AnalysisPipeline(...)` constructor call (around line 68) and add:

```python
        pipeline = AnalysisPipeline(
            data_sync=data_sync,
            candle_store=candle_store,
            screener=Tier1Screener(config.screening, candle_store),
            tier2=Tier2Analyzer(provider),
            tier3=Tier3Analyzer(provider),
            backtest_engine=WalkForwardEngine(),
            monte_carlo=MonteCarloSimulator(capital=config.general.capital),
            quality_gates=QualityGates(),
            run_store=state.run_store,
            setup_store=state.setup_store,
            event_bus=state.event_bus,
            capital=config.general.capital,
            instrument_cache=instrument_cache,
            context_fetcher=MarketContextFetcher(),
            lookback_days=config.backtest.lookback_days,   # ← add this line
        )
```

- [ ] **Step 2.6: Run tests**

```bash
source .venv/bin/activate && pytest tests/analysis/test_pipeline.py -k "lookback" -x -q
```
Expected: both tests PASS.

- [ ] **Step 2.7: Full analysis suite**

```bash
source .venv/bin/activate && pytest tests/analysis/ -x -q
```
Expected: all pass.

- [ ] **Step 2.8: Commit**

```bash
git add tradingbot/analysis/pipeline.py tradingbot/api/analysis_routes.py tests/analysis/test_pipeline.py
git commit -m "fix(pipeline): replace hardcoded datetime(2025,1,1) with rolling lookback

Four methods used a fixed 2025-01-01 start date, causing candle reads to
grow unboundedly as time passes. Now uses self._lookback_days (default 365,
configurable via BacktestConfig.lookback_days) computed as now - timedelta.
API route passes config.backtest.lookback_days at construction time.

Co-Authored-By: Claude Sonnet 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Strengthen Weak Test Assertion

**Files:**
- Modify: `tests/analysis/test_pipeline.py` — `test_fetch_indicators_returns_empty_on_empty_df`

**Interfaces:**
- No production code changes — test-only

- [ ] **Step 3.1: Locate and read the current test**

Current test (line ~362 in `tests/analysis/test_pipeline.py`):

```python
def test_fetch_indicators_returns_empty_on_empty_df(pipeline_deps):
    """Empty candle df must not propagate — returns ({}, fallback string)."""
    pipeline_deps["candle_store"].read.return_value = pd.DataFrame()
    p = AnalysisPipeline(**pipeline_deps)
    indicators, price_action = p._fetch_indicators_for_symbol("TCS")
    assert indicators == {}
    assert "TCS" in price_action   # ← weak: only checks symbol name present
```

The assertion `"TCS" in price_action` passes even if the fallback message is wrong. The implementation returns `f"{symbol}: insufficient candle data for indicators"` — the word "insufficient" distinguishes the error branch from a happy-path return.

- [ ] **Step 3.2: Update assertion — no need for a separate failing test since this is a test-only change**

Replace the weak assertion in `tests/analysis/test_pipeline.py`:

```python
def test_fetch_indicators_returns_empty_on_empty_df(pipeline_deps):
    """Empty candle df must not propagate — returns ({}, fallback string)."""
    pipeline_deps["candle_store"].read.return_value = pd.DataFrame()
    p = AnalysisPipeline(**pipeline_deps)
    indicators, price_action = p._fetch_indicators_for_symbol("TCS")
    assert indicators == {}
    assert "TCS" in price_action
    assert "insufficient" in price_action.lower() or "failed" in price_action.lower(), (
        f"Fallback message must say why it failed, got: {price_action!r}"
    )
```

- [ ] **Step 3.3: Run test to verify it passes with current implementation**

```bash
source .venv/bin/activate && pytest tests/analysis/test_pipeline.py::test_fetch_indicators_returns_empty_on_empty_df -x -q
```
Expected: PASS — `_fetch_indicators_for_symbol` returns `f"{symbol}: insufficient candle data for indicators"` when df is empty, which contains "insufficient".

- [ ] **Step 3.4: Full analysis suite**

```bash
source .venv/bin/activate && pytest tests/analysis/ -x -q
```
Expected: all pass.

- [ ] **Step 3.5: Commit**

```bash
git add tests/analysis/test_pipeline.py
git commit -m "test(pipeline): strengthen weak fallback message assertion

Previous assertion only checked symbol name present in price_action.
Now verifies the message conveys the actual failure reason ('insufficient'
or 'failed'), preventing silent rot if the error branch changes.

Co-Authored-By: Claude Sonnet 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Minor 1 (read-once) → Task 1 ✓
- Minor 2 (rolling lookback) → Task 2 ✓
- Minor 3 (weak assertion) → Task 3 ✓

**Placeholder scan:** No TBDs. All code blocks present and complete.

**Type consistency:**
- `lookback_days: int = 365` added to `__init__` and stored as `self._lookback_days: int` — consistent across all four methods ✓
- `timedelta` imported at module level — no repeated `__import__` needed after Step 2.4 ✓
- `_run_backtests` Task 1 uses temporary `timedelta(days=365)` — Task 2 replaces it with `self._lookback_days`. If tasks run out of order, the temporary constant still works; no crash ✓

**Review Focus coverage:**
- `lookback_days=0` → rolling from_dt equals now → candle read returns empty → `len(df) == 0` guard fires in all four methods → no crash. Covered by existing empty-df tests ✓
- `lookback_days` not passed → defaults to 365 → `test_pipeline_accepts_lookback_days_param` verifies explicit set; omission tested implicitly by all existing tests that construct without it ✓
- Single candle read, empty result → `_run_backtests` returns early → `test_run_backtests_reads_candles_once_not_per_strategy` with empty df produces 0 results, no crash ✓
- `_compute_nifty_5d_change_from_store` using up to 365 days for a 5-day calc → returns float, no correctness issue — harmless over-read ✓
- Strengthened assertion still passes for `InsufficientDataError` branch → `_fetch_indicators_for_symbol` returns `f"{symbol}: insufficient data for indicators"` which contains "insufficient" ✓