# Pipeline Reorder: Claude-First Analysis

## Problem

The analysis pipeline screens 1,617 stocks down to 13 shortlisted candidates, then produces 0 trade setups. This has happened on consecutive runs. The root cause is structural:

1. **Generic backtests gate Claude.** 10 predefined strategies (breakout, momentum, mean_reversion, etc.) run before Claude sees any data. When all 10 fail the quality gates on all 13 stocks (130 backtests, 130 failures), Claude never gets to propose setups.

2. **Strategy mismatch.** The generic strategies test fixed signal logic (e.g., "buy when price touches Bollinger lower band"). Claude would propose specific confluence-based setups (e.g., "short at RSI 80 near BB upper with VWAP target") that no generic strategy tests. The gatekeeper tests different trades than Claude would propose.

3. **Quality gates are too strict.** `expectancy_r >= 0.3` kills profitable strategies running at 0.15-0.20R. `max_consecutive_losses <= 8` is statistically unrealistic for 773-trade datasets. `risk_of_ruin <= 5%` is more conservative than institutional standards.

## Solution

Reorder the pipeline so Claude proposes setups first, then backtest validates those specific ideas. Backtest becomes an informational score (visible in UI), not a hard gate.

## Current Flow

```
1. Market Context (regime)
2. Fetch Universe (1,617 stocks)
3. Filter Candidates (615 pass Tier 1 screen)
4. Claude Shortlist (13 high-conviction candidates)
5. Fetch Intraday Data (15m/5m/1m for 13 stocks)
6. Backtest 10 Generic Strategies per stock ← GATE (kills everything)
7. Claude Deep Analysis (only if backtest passes) ← NEVER REACHED
8. Adversarial Review
9. Jev Quality Score
10. Save & Generate Plan
```

## New Flow

```
1. Market Context (regime)
2. Fetch Universe (1,617 stocks)
3. Filter Candidates (615 pass Tier 1 screen)
4. Claude Shortlist (13 high-conviction candidates)
5. Fetch Intraday Data (15m/5m/1m for 13 stocks)
6. Claude Deep Analysis (ALL shortlisted stocks with indicators) ← MOVED UP
7. Backtest Validation (validates Claude's specific setups) ← MOVED DOWN, INFORMATIONAL
8. Adversarial Review (unchanged)
9. Jev Quality Score (unchanged, informational)
10. Save & Generate Plan
```

## Design

### Step 6 (new): Claude Deep Analysis — runs for ALL shortlisted stocks

Currently gated by backtest. After reorder, runs for every shortlisted stock that has indicator data.

**Input:** Symbol, direction (advisory), regime, technical indicators (RSI, MACD, VWAP, Bollinger, pivots, S/R levels, candle patterns across 15m/5m/1m), recent price action.

**No backtest results in the prompt** at this stage. Claude proposes setups purely from indicator confluence. The prompt already works this way — backtest results were often empty anyway.

**Output per stock:** 0-3 setups with strategy name, direction, entry_price, stop_loss, target_1, target_2, confidence, edge_description. Or `no_trade_reason`.

**No changes to the deep analysis prompt or schema.** The prompt and schema already support this — they don't require backtest data.

### Step 7 (new): Backtest Validation — informational, not a gate

After Claude proposes setups, validate each one by backtesting the closest matching generic strategy.

**Strategy mapping:** Map Claude's proposed strategy name to the closest generic strategy:

```python
STRATEGY_MAP = {
    "breakout": "breakout",
    "momentum": "momentum", 
    "mean_reversion": "mean_reversion",
    "vwap_bounce": "vwap_bounce",
    "orb": "orb",
    "gap_and_go": "gap_and_go",
    "pivot_point": "pivot_point",
    "relative_strength": "relative_strength",
    "bollinger_squeeze": "bollinger_squeeze",
    "supply_demand": "supply_demand",
    # Fuzzy matches for Claude's creative names
    "vwap_mean_reversion": "mean_reversion",
    "rsi_divergence": "mean_reversion",
    "support_bounce": "supply_demand",
    "resistance_rejection": "supply_demand",
    "trend_continuation": "momentum",
    "pullback_entry": "mean_reversion",
}
```

If no match: backtest status = "unvalidated" (no close generic strategy exists).

**What the backtest produces per setup:**
- `backtest_strategy`: which generic strategy was tested
- `backtest_win_rate`, `backtest_profit_factor`, `backtest_expectancy_r`: raw stats
- `backtest_total_trades`: sample size
- `backtest_status`: "validated" (strategy has edge), "weak" (positive but below thresholds), "failed" (negative edge), "unvalidated" (no matching strategy)

**No quality gates.** The stats are attached to the setup data and shown in the UI. Adversarial review sees them and can factor them into its decision.

**Backtest runs only the single matched strategy, not all 10.** Saves ~90% of backtest time per stock.

### Adversarial Review — unchanged, but sees backtest validation

The adversarial prompt already receives backtest results. Now it sees per-setup validation:

```
LXCHEM setup 1 (mean_reversion, short):
  Backtest validation: mean_reversion — 45% WR, PF 1.15, expectancy 0.13R, 82 trades
  Status: weak (positive edge but below institutional thresholds)
```

Adversarial can use this as one input among many — not as a veto.

### Jev Quality Score — unchanged

Already converted to score-only (not a gate) earlier this session. Sees backtest stats in the same format.

### What is removed

1. **The "skip deep analysis if 0 backtest passes" rule** — deleted entirely.
2. **The backtest-before-deep-analysis ordering** — deep analysis moves before backtest.
3. **Quality gate hard rejections on backtest** — quality gates become a scoring function that labels results as validated/weak/failed, not a pass/fail gate.

### What is NOT changed

1. **Screening (Steps 1-4)** — untouched.
2. **Intraday data fetch (Step 5)** — untouched.
3. **Deep analysis prompt and schema** — untouched (already works without backtest data).
4. **Adversarial review prompt and logic** — untouched.
5. **Jev quality check** — untouched.
6. **The 10 generic strategies** — kept, used for validation.
7. **WalkForwardEngine** — untouched, just called differently.
8. **Execution pipeline** — untouched.

## Files Changed

| File | Change |
|------|--------|
| `tradingbot/analysis/pipeline.py` | Reorder: move deep analysis loop before backtest. Remove skip. Backtest validates Claude's proposed setups. |
| `tradingbot/analysis/pipeline.py` | Add `STRATEGY_MAP` for fuzzy matching Claude's strategy names to generic strategies. |
| `tradingbot/analysis/pipeline.py` | Backtest results attached to setup data as informational scores, not used as gate. |
| `tradingbot/analysis/prompts.py` | Remove backtest results from deep analysis user prompt (Claude proposes without backtest context). |
| `tradingbot/api/analysis_routes.py` | Remove `min_trades`, `min_win_rate`, `min_profit_factor` from QualityGates constructor (no longer used as gate). |

## Success Criteria

1. Pipeline run on the same data (trending_down, 13 shortlisted stocks) produces at least some setups with backtest validation scores.
2. Claude deep analysis runs for all 13 shortlisted stocks (not gated).
3. Backtest validation runs only for stocks with Claude-proposed setups (not all 13).
4. Backtest scores are visible in the setup data saved to the store.
5. Adversarial review sees backtest validation scores.
6. Total pipeline time is similar or faster (removed 10 min Jev pre-scoring, added ~15 min Claude calls, removed ~35 min of 130 generic backtests, added ~5 min of targeted backtests).

## Risks

1. **More LLM calls.** 13 Claude calls instead of 0-5. Cost: ~$0.39/run. Acceptable.
2. **Claude proposes bad setups without backtest context.** Mitigated by adversarial review + Jev scoring + backtest validation scores visible to adversarial.
3. **Strategy mapping is imperfect.** Claude might propose a strategy that maps to the wrong generic. Mitigated by "unvalidated" fallback — setup still goes through, just without backtest evidence.
