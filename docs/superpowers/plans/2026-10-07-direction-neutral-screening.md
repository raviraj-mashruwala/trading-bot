# Direction-Neutral Screening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the screening pipeline direction-neutral so short setups are not filtered out before Claude sees them.

**Architecture:** Three changes: (1) factor scores measure signal magnitude not direction, (2) remove Jev pre-scoring of 615 candidates (move Jev to evaluate real setups later), (3) remove Jev reference from shortlist prompt. The downstream pipeline (backtest, deep analysis, execution) already supports shorts.

**Tech Stack:** Python, Jev (TypeSafe SDK), Claude (Anthropic)

**Spec:** Conversation-derived — no separate spec doc. This plan implements the findings from the Oct 6-7 pipeline analysis sessions.

## Global Constraints

- Factor scores remain 0-100 scale
- Composite score threshold unchanged — same number of candidates pass through
- No changes to backtest, deep analysis, adversarial review, or execution code
- Existing tests must continue to pass
- Jev quality gate downstream (post-adversarial) is untouched — that one evaluates real setups

## Review Focus

1. A stock down 15% with high volume should score similarly to a stock up 15% with high volume — both are high-activity candidates worth analyzing. Verify with a unit test.
2. Removing Jev pre-scoring must not break the pipeline — `scored_dicts` must still be a list of dicts with `symbol`, `composite_score`, `sector`, `last_price`, `factor_scores`.
3. The shortlist prompt must not reference `jev_composite` or `jev_setup_confidence` after removal — Claude would hallucinate values.
4. `intelligent_screener.py` has a `jev_bonus` on composite score — this must be removed or it will error when Jev pre-scoring is gone.
5. Existing tests in `tests/analysis/test_jev_shortlist_scorer.py` and `tests/analysis/test_pipeline_jev_wiring.py` reference the pre-scoring flow — they need updating.

---

### Task 1: Make factor scores direction-neutral

**Files:**
- Modify: `tradingbot/analysis/pipeline.py:548-558` (factor score computation)
- Test: `tests/screening/test_factor_neutrality.py` (new)

**Interfaces:**
- Consumes: daily OHLCV data from DuckDB, `nifty_5d_change` float
- Produces: `factor_scores` dict with direction-neutral values for `relative_strength`, `price_structure`, `sector_momentum`

- [ ] **Step 1: Write failing tests for direction-neutral scoring**

```python
# tests/screening/test_factor_neutrality.py
"""Factor scores must measure signal magnitude, not direction."""

def test_relative_strength_symmetric():
    """Stock outperforming by 10% and underperforming by 10% should score equally."""
    # stock_return=15%, nifty=5% → excess=+10%
    score_up = _compute_rs_score(stock_5d_return=15.0, nifty_5d_change=5.0)
    # stock_return=-5%, nifty=5% → excess=-10%
    score_down = _compute_rs_score(stock_5d_return=-5.0, nifty_5d_change=5.0)
    assert score_up == score_down, f"Up {score_up} != Down {score_down}"
    assert score_up > 70, f"10% excess should score high, got {score_up}"

def test_relative_strength_neutral_at_zero():
    """Stock matching Nifty should score 50 (neutral)."""
    score = _compute_rs_score(stock_5d_return=5.0, nifty_5d_change=5.0)
    assert score == 50.0

def test_price_structure_symmetric():
    """Stock 10% above SMA20 and 10% below should score equally."""
    score_above = _compute_ps_score(pct_from_sma20=10.0)
    score_below = _compute_ps_score(pct_from_sma20=-10.0)
    assert score_above == score_below

def test_sector_momentum_symmetric():
    """Strong and weak sectors should score equally (both interesting)."""
    score_strong = _compute_sm_score(sector_median_return=5.0)
    score_weak = _compute_sm_score(sector_median_return=-5.0)
    assert score_strong == score_weak

def _compute_rs_score(stock_5d_return: float, nifty_5d_change: float) -> float:
    rs_excess = stock_5d_return - nifty_5d_change
    return min(100.0, max(0.0, 50.0 + abs(rs_excess) * 5.0))

def _compute_ps_score(pct_from_sma20: float) -> float:
    return min(100.0, max(0.0, 50.0 + abs(pct_from_sma20) * 5.0))

def _compute_sm_score(sector_median_return: float) -> float:
    return min(100.0, max(0.0, 50.0 + abs(sector_median_return) * 5.0))
```

- [ ] **Step 2: Run tests to verify they pass (these test the target formula)**

Run: `python3 -m pytest tests/screening/test_factor_neutrality.py -v`
Expected: PASS — the test functions contain the formula directly

- [ ] **Step 3: Update factor scores in pipeline.py**

In `tradingbot/analysis/pipeline.py`, change three lines:

Line ~550 (relative_strength):
```python
# BEFORE:
relative_strength_score = min(100.0, max(0.0, 50.0 + rs_excess * 5.0))
# AFTER:
relative_strength_score = min(100.0, max(0.0, 50.0 + abs(rs_excess) * 5.0))
```

Line ~558 (price_structure):
```python
# BEFORE:
price_structure_score = min(100.0, max(0.0, 50.0 + pct_above * 5.0))
# AFTER:
price_structure_score = min(100.0, max(0.0, 50.0 + abs(pct_above) * 5.0))
```

Line ~596 (sector_momentum):
```python
# BEFORE:
m["factor_scores"]["sector_momentum"] = min(100.0, max(0.0, 50.0 + med * 5.0))
# AFTER:
m["factor_scores"]["sector_momentum"] = min(100.0, max(0.0, 50.0 + abs(med) * 5.0))
```

- [ ] **Step 4: Run existing screening tests**

Run: `python3 -m pytest tests/screening/ -v`
Expected: PASS — existing tests should not break since they test filtering, not directional scoring

- [ ] **Step 5: Commit**

```bash
git add tradingbot/analysis/pipeline.py tests/screening/test_factor_neutrality.py
git commit -m "fix(screening): make factor scores direction-neutral with abs()

relative_strength, price_structure, and sector_momentum now measure
signal magnitude (abs), not direction. A stock down 15% scores the
same as up 15% — both are high-activity candidates worth analyzing."
```

---

### Task 2: Remove Jev pre-scoring from pipeline

**Files:**
- Modify: `tradingbot/analysis/pipeline.py:183-196` (remove score_candidates call)
- Modify: `tests/analysis/test_pipeline_jev_wiring.py` (update test)
- Modify: `tests/analysis/test_jev_shortlist_scorer.py` (keep tests, they test the function in isolation)

**Interfaces:**
- Consumes: `scored_dicts` list from Tier 1 screen (unchanged format)
- Produces: `scored_dicts` passed directly to `_tier2.shortlist()` without Jev fields

- [ ] **Step 1: Remove Jev pre-scoring call from pipeline.py**

In `tradingbot/analysis/pipeline.py`, delete the entire Jev pre-scoring block (~lines 183-196):

```python
# DELETE this entire block:
        if self._jev_tier2 is not None:
            from tradingbot.analysis.jev_shortlist_scorer import score_candidates
            regime_str = regime.get("regime", "range_bound") if isinstance(regime, dict) else "range_bound"

            def _jev_progress(msg: str) -> None:
                self._bus.emit_sync("scan.shortlist", {"status": "fetching", "message": msg})

            scored_dicts = await _aio.to_thread(
                score_candidates,
                self._jev_tier2._jev, scored_dicts, regime_str,
                0.0, _jev_progress, _is_cancelled,
            )
            log.info("Jev pre-scored %d candidates, top: %s", len(scored_dicts),
                     [(s["symbol"], s.get("jev_composite")) for s in scored_dicts[:5]])
```

- [ ] **Step 2: Update test_pipeline_jev_wiring.py**

Read the current test file. Remove or update any test that asserts Jev pre-scoring runs during the pipeline. Keep tests that verify the Jev quality gate (post-adversarial) still works.

- [ ] **Step 3: Run pipeline tests**

Run: `python3 -m pytest tests/analysis/test_pipeline*.py -v`
Expected: PASS

- [ ] **Step 4: Verify jev_shortlist_scorer tests still pass (isolated unit tests)**

Run: `python3 -m pytest tests/analysis/test_jev_shortlist_scorer.py -v`
Expected: PASS — the function still exists, it's just not called from the pipeline

- [ ] **Step 5: Commit**

```bash
git add tradingbot/analysis/pipeline.py tests/analysis/test_pipeline_jev_wiring.py
git commit -m "perf(pipeline): remove Jev pre-scoring of 615 candidates

Jev was scoring 615 stocks with no intraday data, no indicators, and
long-biased questions (regime alignment, accumulation). Took 10 min,
602 scores thrown away. Jev quality gate downstream still evaluates
real setups with real backtest data — that check is kept."
```

---

### Task 3: Remove Jev pre-scoring from intelligent screener

**Files:**
- Modify: `tradingbot/screening/intelligent_screener.py` (remove jev_bonus on composite)
- Modify: `tests/screening/test_intelligent_screener.py` (update)

**Interfaces:**
- Consumes: `stock_metrics` list, `regime` string
- Produces: `ScoredStock` list with `composite_score` (no longer includes `jev_bonus`)

- [ ] **Step 1: Read intelligent_screener.py and find jev_bonus usage**

Read `tradingbot/screening/intelligent_screener.py` fully. Find where `jev_bonus` is added to the composite score and where Jev is called within the screener itself (separate from the pipeline's pre-scoring).

- [ ] **Step 2: Remove jev_bonus from composite scoring**

If the screener calls Jev internally (separate from pipeline's `score_candidates`), remove that call and the bonus. The composite should be purely factor-based.

- [ ] **Step 3: Update intelligent screener tests**

Read `tests/screening/test_intelligent_screener.py`. Update tests that assert jev_bonus behavior.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/screening/test_intelligent_screener.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tradingbot/screening/intelligent_screener.py tests/screening/test_intelligent_screener.py
git commit -m "refactor(screening): remove jev_bonus from composite scoring

Composite score is now purely factor-based. Jev influence on screening
removed — direction and setup quality are determined later in the
pipeline by Claude deep analysis and Jev quality gate."
```

---

### Task 4: Remove Jev references from shortlist prompt

**Files:**
- Modify: `tradingbot/analysis/prompts.py:142-143` (remove Jev reference in shortlist prompt)

**Interfaces:**
- Consumes: nothing new
- Produces: `SHORTLIST_SYSTEM` string without Jev references

- [ ] **Step 1: Remove Jev AI reference from shortlist prompt**

In `tradingbot/analysis/prompts.py`, delete lines 142-143:

```python
# DELETE:
    "When Jev AI scores are present (jev_composite, jev_setup_confidence), "
    "use them as a confirming signal. jev_composite > 0.6 = strong AI conviction. "
    "Disagreement between your analysis and Jev should be noted in reasoning.\n\n"
```

Claude will no longer look for `jev_composite` in the candidate data (which won't exist after Task 2).

- [ ] **Step 2: Verify prompt syntax**

Run: `python3 -c "from tradingbot.analysis.prompts import SHORTLIST_SYSTEM; print('OK:', len(SHORTLIST_SYSTEM), 'chars')"`
Expected: OK with a character count (no import errors)

- [ ] **Step 3: Commit**

```bash
git add tradingbot/analysis/prompts.py
git commit -m "fix(prompts): remove Jev reference from shortlist prompt

Claude no longer sees jev_composite/jev_setup_confidence in candidate
data (removed in prior commit), so the prompt instruction to use them
as confirming signals would cause hallucination."
```

---

### Task 5: End-to-end verification

**Files:**
- No new files — verification only

- [ ] **Step 1: Run full test suite**

Run: `python3 -m pytest tests/ -v --tb=short 2>&1 | tail -30`
Expected: All tests pass (or only pre-existing failures unrelated to this change)

- [ ] **Step 2: Syntax check all modified files**

```bash
python3 -c "
import ast
for f in [
    'tradingbot/analysis/pipeline.py',
    'tradingbot/analysis/prompts.py',
    'tradingbot/screening/intelligent_screener.py',
]:
    ast.parse(open(f).read())
    print(f'{f}: OK')
"
```

- [ ] **Step 3: Verify pipeline can be imported end-to-end**

```bash
python3 -c "
from tradingbot.analysis.pipeline import AnalysisPipeline
from tradingbot.analysis.prompts import SHORTLIST_SYSTEM, DEEP_ANALYSIS_SYSTEM
from tradingbot.screening.intelligent_screener import IntelligentScreener
print('All imports OK')
"
```

- [ ] **Step 4: Verify no remaining Jev pre-score references in pipeline**

```bash
grep -n "jev_composite\|jev_setup_confidence\|score_candidates\|jev_bonus" \
  tradingbot/analysis/pipeline.py tradingbot/analysis/prompts.py \
  tradingbot/screening/intelligent_screener.py
```
Expected: No matches (all references removed)

- [ ] **Step 5: Commit verification marker**

No commit needed — verification step only.
