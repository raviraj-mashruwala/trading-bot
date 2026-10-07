# Pipeline Reorder: Claude-First Analysis — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorder the analysis pipeline so Claude proposes setups before backtesting, and backtest validates Claude's specific ideas as an informational score rather than a hard gate.

**Architecture:** Move the deep analysis loop (Claude LLM calls) before the backtest loop. After Claude proposes setups, map each setup's strategy to the closest generic strategy and run only that one backtest. Attach backtest stats to setup data as informational scores. Remove the "skip if 0 backtest passes" rule.

**Tech Stack:** Python, Claude (Anthropic API), WalkForwardEngine, MonteCarloSimulator

**Spec:** `docs/superpowers/specs/2026-10-07-pipeline-reorder-design.md`

## Global Constraints

- No changes to screening (Steps 1-4), adversarial review, Jev quality scoring, or execution
- Existing strategy classes and WalkForwardEngine are untouched
- The `build_deep_analysis_user_prompt` function signature changes (backtest_results becomes optional)
- All 10 StrategyName enum values: breakout, momentum, mean_reversion, vwap_bounce, orb, gap_and_go, pivot_point, relative_strength, bollinger_squeeze, supply_demand

## Review Focus

1. Claude proposes a strategy name not in STRATEGY_MAP and not in StrategyName — backtest should return "unvalidated", not crash. Test in Task 2.
2. Claude returns 0 setups for all 13 stocks (legitimate no-trade day) — pipeline should complete cleanly with 0 proposed, not error. Test in Task 1.
3. `backtest_results=[]` passed to `build_deep_analysis_user_prompt` — prompt should say "No prior backtest data" not render an empty section. Test in Task 3.
4. A stock with no 15m candle data (DuckDB empty) — should skip both deep analysis AND backtest, not crash. Already handled by `if not indicators: continue` check.
5. Strategy mapping is case-sensitive — Claude might return "Mean_Reversion" or "BREAKOUT". Map should be case-insensitive. Test in Task 2.

---

### Task 1: Reorder pipeline — deep analysis before backtest

**Files:**
- Modify: `tradingbot/analysis/pipeline.py:230-350` (the main per-stock loop)
- Test: `tests/analysis/test_pipeline.py` (existing, verify no regressions)

**Interfaces:**
- Consumes: `shortlist` (list of dicts with symbol, direction), `regime`, `sectors`, `perf_ctx` from earlier pipeline steps
- Produces: `all_setups` list (from deep analysis), `all_bt_results` dict (from targeted backtest), both passed to adversarial review

- [ ] **Step 1: Restructure the per-stock loop in pipeline.py**

Replace the current loop at `pipeline.py:230-311` with this new order:

```python
        # --- Phase 1: Claude Deep Analysis (ALL shortlisted stocks) ---
        all_setups: list[dict[str, Any]] = []
        if not shortlist:
            self._bus.emit_sync("strategy.deep_analysis", {"status": "skipped", "reason": "no shortlisted stocks"})
        for i, pick in enumerate(shortlist):
            if _is_cancelled():
                log.info("Pipeline cancelled during deep analysis at %d/%d", i, len(shortlist))
                break
            sym = pick["symbol"]
            direction = pick.get("direction", "long")

            # Fetch indicators for Claude's context
            indicators, price_action = await _aio.to_thread(
                self._fetch_indicators_for_symbol, sym,
            )
            self._bus.emit_sync("strategy.indicators", {
                "symbol": sym, "progress": f"{i+1}/{len(shortlist)}",
                "has_data": bool(indicators),
                "status": "fetching" if i + 1 < len(shortlist) else "done",
                "message": f"Indicators {sym} ({i+1}/{len(shortlist)})",
            })

            if not indicators:
                log.warning("Skipping %s — no indicator data", sym)
                continue

            # Claude deep analysis — no backtest data yet
            self._bus.emit_sync("strategy.deep_analysis", {
                "symbol": sym, "progress": f"{i+1}/{len(shortlist)}",
                "status": "fetching", "message": f"Analyzing {sym} ({i+1}/{len(shortlist)})",
            })
            deep = await self._tier3.deep_analyze(
                symbol=sym,
                direction=direction,
                regime=regime,
                indicators=indicators,
                backtest_results=[],
                price_action=price_action,
                performance_context=perf_ctx,
            )
            llm_calls += 1
            if isinstance(deep.get("_usage") if isinstance(deep, dict) else None, LLMUsage):
                total_cost += deep.pop("_usage").cost_usd()
            all_setups.append(deep)
            setups_list = deep.get("setups", []) if isinstance(deep, dict) else []
            n_setups = len(setups_list)
            setup_summaries = []
            for s in setups_list[:3]:
                setup_summaries.append({
                    "strategy": s.get("strategy", "unknown"),
                    "direction": s.get("direction", "long"),
                    "entry": s.get("entry_price", 0),
                    "stop": s.get("stop_loss", 0),
                    "target_1": s.get("target_1", 0),
                    "confidence": s.get("confidence", 0),
                    "edge": s.get("edge_description", "")[:80],
                })
            self._bus.emit_sync("strategy.deep_analysis", {
                "symbol": sym, "progress": f"{i+1}/{len(shortlist)}",
                "setups_found": n_setups,
                "setups": setup_summaries,
                "status": "fetching" if i + 1 < len(shortlist) else "done",
                "message": f"{sym}: {n_setups} setups found ({i+1}/{len(shortlist)})",
            })

        self._bus.emit_sync("strategy.setups", {
            "total_setups": sum(len(s.get("setups", [])) for s in all_setups),
            "symbols_analyzed": len(shortlist),
        })

        # --- Phase 2: Backtest Validation (only stocks with Claude-proposed setups) ---
        all_bt_results: dict[str, list[dict]] = {}
        setups_with_data = [s for s in all_setups if s.get("setups")]
        bt_symbols = [s["symbol"] for s in setups_with_data]

        if not bt_symbols:
            self._bus.emit_sync("strategy.backtest", {"status": "skipped", "reason": "no setups proposed"})
        for i, setup_result in enumerate(setups_with_data):
            if _is_cancelled():
                log.info("Pipeline cancelled during backtest validation at %d/%d", i, len(bt_symbols))
                break
            sym = setup_result["symbol"]
            proposed_setups = setup_result.get("setups", [])

            # Run targeted backtest for each proposed strategy
            bt_results: list[Any] = []
            for setup in proposed_setups:
                strategy_name = setup.get("strategy", "unknown")
                matched = _match_strategy(strategy_name)
                if matched is not None:
                    await _aio.to_thread(
                        self._run_single_backtest, sym, matched, bt_results,
                    )
                    setup["backtest_status"] = "validated" if bt_results else "failed"
                    if bt_results:
                        last_bt = bt_results[-1]
                        setup["backtest_win_rate"] = last_bt.get("win_rate", 0)
                        setup["backtest_profit_factor"] = last_bt.get("profit_factor", 0)
                        setup["backtest_expectancy_r"] = last_bt.get("expectancy_r", 0)
                        setup["backtest_total_trades"] = last_bt.get("total_trades", 0)
                else:
                    setup["backtest_status"] = "unvalidated"
                    log.info("No matching strategy for %s/%s — marking unvalidated", sym, strategy_name)

            all_bt_results[sym] = bt_results
            self._bus.emit_sync("strategy.backtest", {
                "symbol": sym, "progress": f"{i+1}/{len(bt_symbols)}",
                "strategies_tested": len(proposed_setups),
                "strategies_validated": len(bt_results),
                "status": "fetching" if i + 1 < len(bt_symbols) else "done",
                "message": f"Backtest {sym} ({i+1}/{len(bt_symbols)}): {len(bt_results)} validated",
            })
```

- [ ] **Step 2: Remove the old backtest-first loop and skip logic**

Delete lines 240-272 (the old `_run_backtests` call, the backtest gate, and the "skip if 0 backtest passes" block). The new code from Step 1 replaces it entirely.

- [ ] **Step 3: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('tradingbot/analysis/pipeline.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 4: Run existing pipeline tests**

Run: `.venv/bin/python -m pytest tests/analysis/test_pipeline.py -v --tb=short`
Expected: Pre-existing failures only (3 known: asdict issue)

- [ ] **Step 5: Commit**

```bash
git add tradingbot/analysis/pipeline.py
git commit -m "refactor(pipeline): reorder — Claude deep analysis before backtest

Claude now proposes setups first from indicator data, then backtest
validates each proposed strategy specifically. Backtest is informational
(scores attached to setup), not a gate. Removes the skip-if-0-backtest
rule that was blocking all setups."
```

---

### Task 2: Add strategy mapping and single-backtest method

**Files:**
- Modify: `tradingbot/analysis/pipeline.py` (add `_match_strategy` function and `_run_single_backtest` method)
- Create: `tests/analysis/test_strategy_mapping.py`

**Interfaces:**
- Consumes: Claude's `setup["strategy"]` string
- Produces: `StrategyName` enum value or `None`, used by Task 1's backtest loop

- [ ] **Step 1: Write failing tests for strategy mapping**

```python
# tests/analysis/test_strategy_mapping.py
"""Tests for mapping Claude's strategy names to generic strategies."""

from tradingbot.analysis.pipeline import _match_strategy
from tradingbot.core.models import StrategyName


def test_exact_match():
    assert _match_strategy("breakout") == StrategyName.BREAKOUT


def test_case_insensitive():
    assert _match_strategy("Mean_Reversion") == StrategyName.MEAN_REVERSION
    assert _match_strategy("BREAKOUT") == StrategyName.BREAKOUT


def test_fuzzy_match():
    assert _match_strategy("vwap_mean_reversion") == StrategyName.MEAN_REVERSION
    assert _match_strategy("rsi_divergence") == StrategyName.MEAN_REVERSION
    assert _match_strategy("trend_continuation") == StrategyName.MOMENTUM
    assert _match_strategy("support_bounce") == StrategyName.SUPPLY_DEMAND
    assert _match_strategy("resistance_rejection") == StrategyName.SUPPLY_DEMAND
    assert _match_strategy("pullback_entry") == StrategyName.MEAN_REVERSION


def test_unknown_returns_none():
    assert _match_strategy("quantum_flux_arbitrage") is None
    assert _match_strategy("") is None


def test_underscore_and_space_variants():
    assert _match_strategy("gap and go") == StrategyName.GAP_AND_GO
    assert _match_strategy("bollinger squeeze") == StrategyName.BOLLINGER_SQUEEZE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/analysis/test_strategy_mapping.py -v`
Expected: FAIL — `_match_strategy` not defined

- [ ] **Step 3: Implement `_match_strategy` and `_run_single_backtest`**

Add to `tradingbot/analysis/pipeline.py` (module level, before the class):

```python
from tradingbot.core.models import StrategyName

_STRATEGY_MAP: dict[str, StrategyName] = {
    # Exact matches
    "breakout": StrategyName.BREAKOUT,
    "momentum": StrategyName.MOMENTUM,
    "mean_reversion": StrategyName.MEAN_REVERSION,
    "vwap_bounce": StrategyName.VWAP_BOUNCE,
    "orb": StrategyName.ORB,
    "gap_and_go": StrategyName.GAP_AND_GO,
    "pivot_point": StrategyName.PIVOT_POINT,
    "relative_strength": StrategyName.RELATIVE_STRENGTH,
    "bollinger_squeeze": StrategyName.BOLLINGER_SQUEEZE,
    "supply_demand": StrategyName.SUPPLY_DEMAND,
    # Fuzzy matches for Claude's creative names
    "vwap_mean_reversion": StrategyName.MEAN_REVERSION,
    "rsi_divergence": StrategyName.MEAN_REVERSION,
    "support_bounce": StrategyName.SUPPLY_DEMAND,
    "resistance_rejection": StrategyName.SUPPLY_DEMAND,
    "trend_continuation": StrategyName.MOMENTUM,
    "pullback_entry": StrategyName.MEAN_REVERSION,
    "gap and go": StrategyName.GAP_AND_GO,
    "bollinger squeeze": StrategyName.BOLLINGER_SQUEEZE,
}


def _match_strategy(name: str) -> StrategyName | None:
    """Map Claude's strategy name to the closest generic strategy."""
    normalized = name.lower().strip().replace(" ", "_")
    # Try exact match first
    if normalized in _STRATEGY_MAP:
        return _STRATEGY_MAP[normalized]
    # Try with spaces instead of underscores
    spaced = normalized.replace("_", " ")
    if spaced in _STRATEGY_MAP:
        return _STRATEGY_MAP[spaced]
    # Try enum value match
    try:
        return StrategyName(normalized)
    except ValueError:
        pass
    # Try substring match against known strategies
    for key, val in _STRATEGY_MAP.items():
        if key in normalized or normalized in key:
            return val
    return None
```

Add `_run_single_backtest` method to `AnalysisPipeline` class:

```python
    def _run_single_backtest(self, symbol: str, strategy_name: StrategyName, results: list) -> None:
        """Run ONE specific strategy backtest for validation. No quality gate."""
        from tradingbot.strategy.strategies import STRATEGY_REGISTRY

        strategy = STRATEGY_REGISTRY.get(strategy_name)
        if strategy is None:
            return

        df = None
        if getattr(self, '_duckdb', None) is not None:
            df = self._duckdb.read(symbol, "15m", days=180)
        if (df is None or df.empty) and self._candles is not None:
            from_dt = datetime.now(tz=IST) - timedelta(days=self._lookback_days)
            df = self._candles.read(symbol, "15minute", from_dt, datetime.now(tz=IST))
        if df is None or len(df) == 0:
            return

        log.info("Validating %s/%s (%d candles)", symbol, strategy_name.value, len(df))
        report = self._backtest.run(symbol, df, strategy)
        if report.total_trades >= 3:
            from dataclasses import asdict
            results.append(asdict(report))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/analysis/test_strategy_mapping.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tradingbot/analysis/pipeline.py tests/analysis/test_strategy_mapping.py
git commit -m "feat(pipeline): add strategy mapping and single-backtest validation

_match_strategy maps Claude's strategy names to generic StrategyName
enum values (case-insensitive, fuzzy). _run_single_backtest validates
one specific strategy without quality gates — raw stats attached to
setup data for informational display."
```

---

### Task 3: Update deep analysis prompt for optional backtest results

**Files:**
- Modify: `tradingbot/analysis/prompts.py:502-534` (build_deep_analysis_user_prompt)
- Test: verify prompt renders cleanly with empty backtest_results

**Interfaces:**
- Consumes: `backtest_results: list[dict]` (now always `[]` when called before backtest)
- Produces: user prompt string with "No prior backtest data" instead of empty section

- [ ] **Step 1: Update the prompt builder to handle empty backtest results**

In `tradingbot/analysis/prompts.py`, change the `bt_text` section:

```python
    bt_text = "\n".join(
        f"  {b['strategy']}: {b['total_trades']} trades, "
        f"win_rate={b['win_rate']:.0%}, PF={b['profit_factor']:.1f}, "
        f"expectancy_r={b['expectancy_r']:.2f}"
        for b in backtest_results
    )
    if not bt_text:
        bt_text = "  No prior backtest data — propose setups based on indicator confluence."
```

- [ ] **Step 2: Verify prompt renders**

Run: `python3 -c "from tradingbot.analysis.prompts import build_deep_analysis_user_prompt; p = build_deep_analysis_user_prompt('TEST', 'long', {'regime': 'trending_down'}, {'RSI': 75}, [], 'Price dropped 2%'); print(p[:200])"`
Expected: Contains "No prior backtest data"

- [ ] **Step 3: Commit**

```bash
git add tradingbot/analysis/prompts.py
git commit -m "fix(prompts): handle empty backtest results in deep analysis prompt

When deep analysis runs before backtest (new pipeline order), backtest
results are empty. Prompt now shows 'No prior backtest data — propose
setups based on indicator confluence' instead of a blank section."
```

---

### Task 4: Update stepper order in frontend and backend

**Files:**
- Modify: `tradingbot/api/analysis_routes.py` (_PIPELINE_STEP_EVENTS order)
- Modify: `web/src/lib/store.ts` (PIPELINE_STEPS order)
- Modify: `web/src/components/analysis/pipeline-stepper.tsx` (STEPS display order)

**Interfaces:**
- Consumes: WebSocket events from pipeline
- Produces: correct step ordering in UI

- [ ] **Step 1: Reorder steps — deep analysis before backtest**

In `tradingbot/api/analysis_routes.py`, change `_PIPELINE_STEP_EVENTS`:

```python
_PIPELINE_STEP_EVENTS = (
    "scan.context", "scan.universe", "scan.filtered", "scan.shortlist",
    "strategy.indicators", "strategy.deep_analysis", "strategy.backtest",
    "strategy.setups", "strategy.sized",
)
```

In `web/src/lib/store.ts`, change `PIPELINE_STEPS`:

```typescript
const PIPELINE_STEPS = [
  "scan.context", "scan.universe", "scan.filtered", "scan.shortlist",
  "strategy.indicators", "strategy.deep_analysis", "strategy.backtest",
  "strategy.setups", "strategy.sized",
] as const;
```

In `web/src/components/analysis/pipeline-stepper.tsx`, change `STEPS`:

```typescript
const STEPS = [
  { key: "scan.context", label: "Market Context" },
  { key: "scan.universe", label: "Fetch Universe" },
  { key: "scan.filtered", label: "Filter Candidates" },
  { key: "scan.shortlist", label: "LLM Shortlist" },
  { key: "strategy.indicators", label: "Technical Indicators" },
  { key: "strategy.deep_analysis", label: "Deep Analysis" },
  { key: "strategy.backtest", label: "Backtest Validation" },
  { key: "strategy.setups", label: "Strategy Setups" },
  { key: "strategy.sized", label: "Risk Sizing" },
];
```

- [ ] **Step 2: TypeScript check**

Run: `cd web && npx tsc --noEmit --pretty 2>&1 | grep -v data-sync-section | grep -i error`
Expected: No errors from our files

- [ ] **Step 3: Commit**

```bash
git add tradingbot/api/analysis_routes.py web/src/lib/store.ts web/src/components/analysis/pipeline-stepper.tsx
git commit -m "feat(ui): reorder stepper — deep analysis before backtest validation

Pipeline now runs: indicators → deep analysis → backtest validation.
Stepper reflects new order. Backtest step renamed to 'Backtest Validation'
to clarify it validates Claude's proposed setups."
```

---

### Task 5: Remove QualityGates from pipeline constructor

**Files:**
- Modify: `tradingbot/api/analysis_routes.py:118-122` (remove QualityGates from pipeline construction)
- Modify: `tradingbot/analysis/pipeline.py` (remove `self._gates` usage, keep `_run_backtests` for backward compat but remove gate evaluation)

**Interfaces:**
- Consumes: nothing new
- Produces: pipeline no longer requires QualityGates instance

- [ ] **Step 1: In analysis_routes.py, remove QualityGates from pipeline construction**

The `QualityGates` import and instantiation at lines 118-122 can be removed since backtest validation no longer uses gates. The `_run_single_backtest` method (Task 2) doesn't call `self._gates.evaluate()`.

Remove from `analysis_routes.py`:
```python
# DELETE these lines from pipeline construction:
            quality_gates=QualityGates(
                min_trades=5, min_win_rate=0.40, min_profit_factor=1.2,
            ),
```

In `pipeline.py`, make `quality_gates` optional in `__init__` (set to `None` default) so existing code doesn't break if passed.

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('tradingbot/api/analysis_routes.py').read()); ast.parse(open('tradingbot/analysis/pipeline.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/ --tb=line 2>&1 | tail -5`
Expected: Same pre-existing failures, no new ones

- [ ] **Step 4: Commit**

```bash
git add tradingbot/api/analysis_routes.py tradingbot/analysis/pipeline.py
git commit -m "refactor(pipeline): remove QualityGates from pipeline construction

Backtest validation no longer uses quality gates as a pass/fail gate.
Raw stats are attached to setup data for informational display.
QualityGates class is kept for potential future use but not instantiated."
```
