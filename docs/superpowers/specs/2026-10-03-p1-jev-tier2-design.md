# P1 Jev Integration: Tier 2 Regime + Sectors + Live Monitor

**Date:** 2026-10-03
**Scope:** Replace Tier 2 regime and sector Claude calls with Jev, add live regime monitor
**Priority:** P1 — pre-market speed + intraday regime awareness

---

## 1. Problem Statement

Tier 2 analysis makes 3 sequential Claude calls (~15-20s total, ~$0.10):
1. `analyze_regime()` — classify market regime (~5s)
2. `analyze_sectors()` — identify sector opportunities (~5s)  
3. `shortlist()` — pick 10-15 candidates (~8s)

Calls #1 and #2 are classification/scoring tasks — Jev handles these in ~100ms each. Call #3 (shortlist) requires reasoning over 50+ stocks with text generation — stays on Claude.

Additionally, regime is classified once pre-market and assumed static all day. Intraday regime shifts (VIX spikes, sudden selling) go undetected.

## 2. Goals

- Regime classification: ~100ms (was ~5s)
- Sector analysis: ~150ms (was ~5s)
- Pre-market pipeline: ~10s faster end-to-end
- Live regime monitoring every 5 minutes during market hours
- Same return schemas so downstream code (shortlist, backtest, Tier 3) doesn't change

## 3. Non-Goals

- Replacing shortlist() Claude call (needs text generation)
- Changing Tier 1 screening (separate work item)
- Changing Tier 3 deep analysis

---

## 4. Architecture

### 4.1 Component Map

```
NEW FILES:
  analysis/jev_tier2.py              — Jev regime + sector analyzer
  executor/regime_monitor.py         — Live regime check during market hours
  tests/analysis/test_jev_tier2.py   — 8 tests
  tests/executor/test_regime_monitor.py — 4 tests

MODIFIED FILES:
  analysis/pipeline.py               — Use JevTier2 for regime/sectors when available
  executor/executor.py               — Add regime monitor to tick loop
```

### 4.2 Data Flow

```
PRE-MARKET (pipeline.py):
  MarketContextFetcher → market_ctx (nifty, vix, fii/dii, sectors)
  ├─ Jev: analyze_regime(market_ctx) → regime dict (~100ms)
  ├─ Jev: analyze_sectors(sector_data) → sector analysis (~150ms)
  └─ Claude: shortlist(regime, sectors, scored_stocks) → picks (~8s, unchanged)

MARKET HOURS (executor.py tick loop):
  Every 5 min:
    Jev: regime_check(market_data, current_regime) → {changed: bool, new_regime}
    If changed → log event, update state
```

### 4.3 Fallback Chain

```
Jev available → use Jev for regime + sectors
Jev fails     → fall back to Claude Tier2Analyzer (original behavior)
Claude fails  → pipeline aborts as before
```

---

## 5. Component Specifications

### 5.1 JevTier2Analyzer (`analysis/jev_tier2.py`)

Same constructor signature as Tier2Analyzer but takes JevClient instead of LLMProvider.

**`analyze_regime()`** — 6 Jev questions, 1 call:

| ID | Type | Options/Levels |
|----|------|----------------|
| `regime` | Choice | trending_up, trending_down, range_bound, volatile, low_vol_squeeze |
| `regime_confidence_level` | Score (4) | Low clarity, Some signal, Clear signal, Very strong signal |
| `bias` | Choice | bullish, bearish, neutral |
| `risk_appetite` | Choice | aggressive, moderate, defensive |
| `trend_strength` | Score (4) | No trend, Weak, Moderate, Strong |
| `institutional_sentiment` | Score (5) | Strongly bearish, Mildly bearish, Neutral, Mildly bullish, Strongly bullish |

Returns dict matching REGIME_SCHEMA:
```python
{
    "regime": "trending_up",
    "regime_confidence": 0.82,  # regime_confidence_level.score / 3
    "bias": "bullish",
    "key_levels": {},  # empty — Jev can't compute price levels
    "sectors_in_play": [],  # populated from sector analysis
    "sectors_to_avoid": [],
    "risk_appetite": "moderate",
    "reasoning": "jev: regime=trending_up(conf=0.82), bias=bullish, strength=0.75",
}
```

**`analyze_sectors()`** — 18 Jev questions, 1 call (9 sectors × 2):

| Per Sector | Type | Purpose |
|---|---|---|
| `{sector}_momentum` | Score (5) | Weak → Strong momentum |
| `{sector}_rotation` | Noul | Is money rotating into this sector? |

Sectors: banking, it, pharma, auto, metal, fmcg, energy, realty, infra.

Returns dict matching SECTOR_SCHEMA:
```python
{
    "sectors": [
        {"name": "banking", "intraday_bias": "bullish", "theme": "sector rotation",
         "catalyst": "jev: momentum=0.85, rotation=0.78"},
        ...
    ],
    "reasoning": "jev: 9 sectors scored, ranked by composite",
}
```

Sectors sorted by composite = 0.6 × momentum + 0.4 × rotation. Top 3 get "bullish" bias, bottom 3 get "bearish", middle 3 get "neutral".

**`shortlist()`** — delegates to the original Tier2Analyzer (Claude). JevTier2 doesn't replace this call.

### 5.2 RegimeMonitor (`executor/regime_monitor.py`)

```python
class RegimeMonitor:
    def __init__(self, jev_client: JevClient, check_interval_seconds: int = 300):
        ...
    
    def should_check(self, now: datetime) -> bool:
        """True if 5 min elapsed since last check."""
    
    def check(self, market_data: dict, current_regime: str) -> RegimeCheckResult:
        """Sync Jev call: 2 questions (regime_changed + new_regime)."""
```

Returns:
```python
@dataclass(frozen=True)
class RegimeCheckResult:
    changed: bool
    new_regime: str | None
    confidence: float
```

### 5.3 Pipeline Wiring (`analysis/pipeline.py`)

- Add `jev_config` parameter to `AnalysisPipeline.__init__`
- If `jev_config` and `jev_config.enabled` and `JevClient.available`:
  - Create `JevTier2Analyzer(jev_client)` 
  - Use for `analyze_regime()` and `analyze_sectors()`
  - Use original `self._tier2` (Claude) for `shortlist()`
- If Jev fails: fall back to `self._tier2` for that call
- If no Jev: use `self._tier2` for everything (existing behavior)

### 5.4 Executor Wiring (`executor/executor.py`)

- `Executor.__init__` gets optional `regime_monitor: RegimeMonitor`
- In `tick()`, after kill switch check, before leg iteration:
  - If `regime_monitor` and `regime_monitor.should_check(now)`:
    - Call `regime_monitor.check(market_data, current_regime)`
    - If changed: log warning, store new regime

---

## 6. Test Plan

### 6.1 test_jev_tier2.py (8 tests)

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_regime_trending_up` | Correct regime + confidence from Jev answers |
| 2 | `test_regime_volatile_low_confidence` | Low confidence → 0.33 |
| 3 | `test_regime_jev_fails_returns_none` | Jev returns None → method returns None |
| 4 | `test_sectors_ranked_by_composite` | Top sector has highest 0.6×momentum + 0.4×rotation |
| 5 | `test_sectors_bias_assignment` | Top 3 bullish, bottom 3 bearish, middle neutral |
| 6 | `test_sectors_jev_fails_returns_none` | Jev returns None → None |
| 7 | `test_regime_returns_all_schema_fields` | Result has all REGIME_SCHEMA keys |
| 8 | `test_sectors_returns_all_schema_fields` | Result has sectors array with correct shape |

### 6.2 test_regime_monitor.py (4 tests)

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_should_check_respects_interval` | False before interval, True after |
| 2 | `test_check_detects_regime_change` | noul > 0.7 → changed=True |
| 3 | `test_check_no_change` | noul < 0.7 → changed=False |
| 4 | `test_check_jev_fails_returns_no_change` | Jev None → changed=False |

---

## 7. Estimated Effort

~450 lines, 12 new tests, 4 new files + 2 modified. ~1 day.
