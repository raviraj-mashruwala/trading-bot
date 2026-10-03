# Jev Integration Plan: Trading Bot × TypeSafe AI

## The Thesis

The trading bot has **three layers of decision-making**:

1. **Deterministic rules** (Tier 1 screening, entry guard, risk limits) — fast but rigid
2. **LLM calls to Claude** (Tier 2/3 analysis, LLM escalator) — smart but slow (~3-10s) and expensive (~$0.01-0.05/call)
3. **Nothing yet** (gaps where decisions could be better but aren't worth an LLM call)

Jev fills all three gaps:
- **Replace** Claude where the task is really classification/scoring (not generation) → 50-200x faster, 400x cheaper
- **Enhance** deterministic rules with calibrated probabilistic signals → smarter without losing speed
- **Fill gaps** where decisions weren't worth an LLM call but are worth a $0.000042 Jev call

**Net effect:** Faster pre-market analysis, real-time intelligence during market hours (100ms vs 5s), richer signals at every decision point, and ~95% cost reduction on AI inference.

---

## Integration Map

### 0. INTELLIGENT TIER 1 SCREENING (Pre-market)

**Current:** `screener.py:46` — rigid deterministic pipeline  
**Problem:** Three chokepoints kill good opportunities:

1. **Liquidity filter** — binary pass/fail. Stock with avg volume 95K vs 100K threshold → dead. Even if today's pre-market volume is 5x normal.
2. **9-factor scorer** — fixed weights regardless of regime. Momentum factors matter in trends, structure factors in ranges. Same weights every day = wrong priorities half the time.
3. **Correlation filter** — dumb sector cap (max 3/sector). Strong sector with 6 setups capped at 3, while weak sector with 0 gets empty slots.

**Jev enhancement:** Three intelligence layers wrapping the deterministic core.

**Layer A: Rescue Pool** — Stocks that barely miss thresholds (≥60% of each) get Jev evaluation:

```python
# Per near-miss stock (3 questions, ~100ms):
questions = {
    "unusual_activity": Noul(
        instructions="Despite failing liquidity thresholds, does this stock show unusual activity worth investigating?",
        criteria={
            "true": "Today's volume significantly above average, or strong technicals compensate",
            "false": "No unusual activity — rightfully filtered out",
        },
    ),
    "tradeable_despite_threshold": Noul(
        instructions="Can this stock be safely traded intraday despite barely missing thresholds?",
    ),
    "opportunity_quality": Score(
        instructions="How strong is the trading opportunity, ignoring the threshold it failed?",
        criteria=[
            "Weak — no compelling setup even if liquid enough",
            "Moderate — decent setup, worth watching",
            "Strong — clear opportunity being missed by rigid filter",
        ],
    ),
}
# rescue_score = 0.4 × unusual + 0.3 × tradeable + 0.3 × quality
# rescue_score > 0.55 → RESCUED
```

**Layer B: Regime-Adaptive Weights** — Factor weights shift based on today's regime:

```
TRENDING UP:   relative_strength ×1.5  sector_momentum ×1.4  volume_surge ×1.3
RANGE BOUND:   price_structure ×1.5    volume_profile ×1.4   candlestick ×1.3
VOLATILE:      atr_expansion ×1.5      volume_surge ×1.4     gap_analysis ×1.4
LOW_VOL_SQUEEZE: volume_surge ×1.5     atr_expansion ×1.5    volume_profile ×1.3

Blend strength scales with regime_confidence:
  confidence 0.3 → weights barely shift (ambiguous regime)
  confidence 0.85 → full regime adaptation
```

**Layer C: Smart Sector Caps** — Sector caps flex by sector strength from Jev:

```
sector_strength > 0.7  → cap = base + 2  (strong sector gets more slots)
sector_strength > 0.5  → cap = base + 1
sector_strength < 0.3  → cap = base - 1  (weak sector loses a slot)
otherwise              → cap = base       (unchanged)
```

**Impact:** ~10-20 rescued stocks per day. Regime-aware ranking prioritizes right factors. Strong sectors get proportional representation. Cost: ~$0.001 for rescue pool Jev calls.

**Implementation:** `screening/intelligent_screener.py` (already written — wraps existing deterministic screener, never bypasses safety).

**Hierarchy:** Deterministic hard filter runs first (safety floor). Jev only adds near-misses back or reweights — never lets through truly untradeable stocks.

---

### 1. MARKET REGIME CLASSIFICATION (Tier 2)

**Current:** `tier2_analyzer.py:30` — Claude call to classify market regime  
**Problem:** 3-8s latency, ~$0.02/call, text parsing needed  
**Jev replacement:** Single Choice question

```python
from typesafe_sdk import Choice, Score, Noul, TypeSafeClient

def classify_regime(market_data: dict) -> dict:
    with TypeSafeClient() as client:
        response = client.system_one(
            state={
                "nifty_change_pct": market_data["nifty_change"],
                "vix_level": market_data["vix"],
                "vix_change_pct": market_data["vix_change"],
                "advance_decline_ratio": market_data["adv_dec"],
                "fii_flow_crores": market_data["fii_flow"],
                "dii_flow_crores": market_data["dii_flow"],
                "nifty_above_200dma": market_data["above_200dma"],
                "breadth_pct": market_data["breadth"],
            },
            questions={
                "regime": Choice(
                    instructions="What is the current market regime based on the data?",
                    criteria={
                        "trending_up": "Broad uptrend — rising index, healthy breadth, institutional buying",
                        "trending_down": "Broad downtrend — falling index, poor breadth, institutional selling",
                        "range_bound": "Sideways — low directional conviction, mixed signals",
                        "volatile": "High VIX, sharp intraday swings, uncertain direction",
                        "low_vol_squeeze": "Compressed volatility, low VIX, narrow range — breakout likely",
                    },
                ),
                "trend_strength": Score(
                    instructions="How strong is the prevailing directional trend?",
                    criteria=[
                        "No clear trend — choppy or flat",
                        "Weak trend — some directional bias but fragile",
                        "Moderate trend — clear direction with some counter-signals",
                        "Strong trend — broad participation, aligned indicators",
                    ],
                ),
                "institutional_sentiment": Score(
                    instructions="How bullish is institutional flow (FII + DII combined)?",
                    criteria=[
                        "Strongly bearish — heavy net selling",
                        "Mildly bearish — net selling but not extreme",
                        "Neutral — mixed or minimal flow",
                        "Mildly bullish — net buying",
                        "Strongly bullish — heavy net buying from both FII and DII",
                    ],
                ),
            },
        )
    return {
        "regime": response.answers["regime"].choice,
        "regime_confidence": response.answers["regime"].confidence,
        "regime_probabilities": response.answers["regime"].probabilities,
        "trend_strength": response.answers["trend_strength"].score / 3,  # normalize 0-1
        "institutional_sentiment": response.answers["institutional_sentiment"].score / 4,
    }
```

**Impact:** ~100ms instead of ~5s. Calibrated confidence tells you when the regime is ambiguous (range_bound at 0.35, volatile at 0.30 → act cautiously). Run every 5 minutes during market hours for live regime tracking.

---

### 2. SECTOR ROTATION SCORING (Tier 2)

**Current:** `tier2_analyzer.py:57` — Claude analyzes sector rotation  
**Problem:** Slow, expensive, unstructured output  
**Jev replacement:** Composite scoring per sector

```python
SECTORS = ["banking", "it", "pharma", "auto", "metal", "fmcg", "energy", "realty", "infra"]

def score_sectors(sector_data: dict) -> dict:
    questions = {}
    for sector in SECTORS:
        questions[f"{sector}_momentum"] = Score(
            instructions=f"How strong is `{sector}` sector's momentum based on its data?",
            criteria=[
                "Weak — underperforming, declining, no institutional interest",
                "Below average — flat or lagging the market",
                "Average — in line with broader market",
                "Above average — outperforming with some catalysts",
                "Strong — leading sector with heavy flows and clear momentum",
            ],
        )
        questions[f"{sector}_rotation_in"] = Noul(
            instructions=f"Is money rotating INTO `{sector}` sector (vs rotating out)?",
        )

    with TypeSafeClient() as client:
        response = client.system_one(state=sector_data, questions=questions)

    results = {}
    for sector in SECTORS:
        momentum = response.answers[f"{sector}_momentum"].score / 4
        rotation = response.answers[f"{sector}_rotation_in"].noul
        results[sector] = {
            "momentum": momentum,
            "rotation_signal": rotation,
            "composite": 0.6 * momentum + 0.4 * rotation,
        }
    return results
```

**Impact:** 18 questions (9 sectors × 2) in ONE call. ~150ms. Speculative fan-out — ask everything, use what matters. Composite scoring pattern gives tunable sector ranking.

---

### 3. STOCK SHORTLISTING (Tier 2)

**Current:** `tier2_analyzer.py:81` — Claude ranks candidates from ~50 stocks  
**Problem:** LLM processes all 50 in one prompt → context rot, expensive  
**Jev replacement:** Multi-dimension scoring per stock, then rank in code

```python
def score_candidates(candidates: list[dict], market_context: dict) -> list[dict]:
    scored = []
    # Process in batches of ~10 (state size management)
    for stock in candidates:
        state = {
            "stock": stock,
            "market_regime": market_context["regime"],
            "sector_strength": market_context["sector_scores"].get(stock["sector"]),
        }
        questions = {
            "setup_quality": Score(
                instructions="How promising is this stock as an intraday trade setup today?",
                criteria=[
                    "Poor — no clear edge, conflicting signals",
                    "Below average — some signals but weak conviction",
                    "Decent — tradeable setup with moderate conviction",
                    "Good — clear setup with multiple confirming signals",
                    "Excellent — textbook setup with strong confluence",
                ],
            ),
            "regime_alignment": Noul(
                instructions="Does this stock's setup align with the current `market_regime`?",
            ),
            "risk_reward_attractive": Noul(
                instructions=(
                    "Based on the technical levels, does this stock offer "
                    "an attractive risk:reward ratio (at least 2:1)?"
                ),
            ),
            "volume_conviction": Noul(
                instructions="Does volume data suggest institutional participation or accumulation?",
            ),
        }
        with TypeSafeClient() as client:
            response = client.system_one(state=state, questions=questions)

        composite = (
            0.35 * (response.answers["setup_quality"].score / 4)
            + 0.25 * response.answers["regime_alignment"].noul
            + 0.25 * response.answers["risk_reward_attractive"].noul
            + 0.15 * response.answers["volume_conviction"].noul
        )
        scored.append({
            **stock,
            "jev_composite": composite,
            "jev_setup_confidence": response.answers["setup_quality"].confidence,
            "jev_answers": response.answers,
        })

    # Rank by composite, filter by confidence
    scored.sort(key=lambda x: x["jev_composite"], reverse=True)
    return [s for s in scored if s["jev_setup_confidence"] > 0.4]
```

**Impact:** ~50 calls × 100ms ≈ 5s total (parallelize with async client → <1s). Currently a single Claude call that takes 10-15s. More granular: you get per-dimension scores to explain WHY a stock was ranked.

---

### 4. ENTRY GUARD ENHANCEMENT (Market Hours)

**Current:** `entry_guard.py:24` — 10 hard-coded rules return VETO/WAIT/ENTER  
**Problem:** Binary rules miss nuance. Momentum at -55 vetoes entry but -61 doesn't — arbitrary boundary  
**Jev enhancement:** Add probabilistic layer alongside existing rules

```python
def enhanced_entry_evaluation(leg: TradeLeg, momentum: MomentumSnapshot) -> dict:
    # Keep existing deterministic rules as hard vetoes
    deterministic = existing_entry_guard.evaluate(leg, momentum)
    if deterministic.verdict == "VETO" and deterministic.confidence > 0.9:
        return deterministic  # hard rules still override

    # Jev adds nuance for borderline cases
    state = {
        "direction": leg.direction.value,
        "planned_entry": leg.entry_price,
        "current_price": momentum.last_price,
        "price_drift_pct": abs(momentum.last_price - leg.entry_price) / leg.entry_price * 100,
        "momentum_1m": momentum.score_1m,
        "momentum_5m": momentum.score_5m,
        "vwap_distance_pct": momentum.vwap_distance_pct,
        "volume_ratio": momentum.volume_ratio,
        "pattern": momentum.pattern,
        "time_since_open_minutes": momentum.minutes_since_open,
        "strategy": leg.strategy.value,
    }

    with TypeSafeClient() as client:
        response = client.system_one(
            state=state,
            questions={
                "enter_now": Noul(
                    instructions=(
                        "Given the live momentum data, should this trade be entered NOW? "
                        "Consider direction alignment, momentum strength, volume confirmation, "
                        "and VWAP positioning."
                    ),
                    criteria={
                        "true": "Momentum, volume, and price action all support immediate entry",
                        "false": "Conditions are unfavorable — wait or skip",
                    },
                ),
                "momentum_quality": Score(
                    instructions="How favorable is the current momentum for this trade's direction?",
                    criteria=[
                        "Hostile — momentum strongly against the trade direction",
                        "Unfavorable — weak or conflicting momentum",
                        "Neutral — no strong momentum either way",
                        "Favorable — momentum aligns with trade direction",
                        "Ideal — strong, clean momentum with volume confirmation",
                    ],
                ),
                "fading_risk": Noul(
                    instructions="Is there a risk that the move has already played out (late entry)?",
                ),
            },
        )

    enter_prob = response.answers["enter_now"].noul
    momentum_quality = response.answers["momentum_quality"].score / 4
    fading_risk = response.answers["fading_risk"].noul

    # Three-way routing
    if enter_prob > 0.75 and fading_risk < 0.4:
        return {"verdict": "ENTER", "confidence": enter_prob, "momentum_quality": momentum_quality}
    elif enter_prob < 0.3 or fading_risk > 0.7:
        return {"verdict": "VETO", "confidence": 1 - enter_prob, "reason": "jev_low_conviction"}
    else:
        return {"verdict": "WAIT", "confidence": enter_prob, "momentum_quality": momentum_quality}
```

**Impact:** This is THE killer integration. Currently the LLM escalator (`llm_escalator.py:46`) takes 3-8s for marginal entries — an eternity in live trading. Jev does it in ~100ms. Can run EVERY tick (every 5s) instead of only on escalation. The confidence-gated routing pattern naturally handles the ENTER/WAIT/VETO decision with calibrated probabilities.

---

### 5. REPLACE LLM ESCALATOR (Market Hours)

**Current:** `llm_escalator.py:46,55` — Claude for marginal entry/exit decisions  
**Problem:** 3-8s latency during live trading is unacceptable for time-sensitive decisions  
**Jev replacement:** Direct replacement with structured questions

```python
class JevEscalator:
    """Replaces LLMEscalator for sub-200ms entry/exit decisions."""

    def __init__(self):
        self.client = TypeSafeClient()

    def evaluate_entry(self, leg: TradeLeg, candles: list, momentum: dict) -> dict:
        response = self.client.system_one(
            state={
                "setup": {
                    "symbol": leg.symbol,
                    "direction": leg.direction.value,
                    "strategy": leg.strategy.value,
                    "entry_price": leg.entry_price,
                    "stop_loss": leg.stop_loss,
                    "target_1": leg.target_1,
                },
                "live_candles_5m": candles[-6:],  # last 30 min
                "momentum": momentum,
            },
            questions={
                "should_enter": Noul(
                    instructions="Should this trade be entered based on the live price action?",
                    criteria={
                        "true": "Price action confirms the setup thesis — enter",
                        "false": "Price action contradicts or invalidates the setup — skip",
                    },
                ),
                "invalidated": Noul(
                    instructions="Has the original trade setup been invalidated by current price action?",
                ),
                "timing": Choice(
                    instructions="What is the best action right now?",
                    criteria={
                        "enter_now": "Conditions are favorable — execute immediately",
                        "wait_5min": "Close but not quite — reassess in 5 minutes",
                        "skip": "Setup is no longer valid — do not enter",
                    },
                ),
            },
        )
        return {
            "enter": response.answers["should_enter"].noul > 0.6,
            "invalidated": response.answers["invalidated"].noul > 0.7,
            "action": response.answers["timing"].choice,
            "action_confidence": response.answers["timing"].confidence,
        }

    def evaluate_exit(self, position: Position, candles: list, momentum: dict) -> dict:
        response = self.client.system_one(
            state={
                "position": {
                    "symbol": position.symbol,
                    "direction": position.direction.value,
                    "entry_price": position.entry_price,
                    "current_pnl_pct": position.unrealized_pnl_pct,
                    "time_in_trade_minutes": position.duration_minutes,
                },
                "live_candles_5m": candles[-6:],
                "momentum": momentum,
            },
            questions={
                "exit_now": Noul(
                    instructions="Should this position be closed immediately?",
                    criteria={
                        "true": "Momentum exhausted, reversal signals, or risk elevated — close now",
                        "false": "Position still has favorable momentum — hold",
                    },
                ),
                "momentum_exhaustion": Noul(
                    instructions="Is the momentum that drove this trade showing signs of exhaustion?",
                ),
                "reversal_risk": Score(
                    instructions="How likely is a reversal against this position in the next 30 minutes?",
                    criteria=[
                        "Very unlikely — strong trend continuation signals",
                        "Unlikely — some noise but trend intact",
                        "Possible — mixed signals, caution warranted",
                        "Likely — multiple reversal signals forming",
                        "Very likely — clear reversal pattern underway",
                    ],
                ),
            },
        )
        reversal_risk = response.answers["reversal_risk"].score / 4

        if response.answers["exit_now"].noul > 0.8:
            return {"action": "EXIT", "reason": "jev_high_conviction_exit"}
        elif reversal_risk > 0.7 and response.answers["momentum_exhaustion"].noul > 0.6:
            return {"action": "TIGHTEN_STOP", "reversal_risk": reversal_risk}
        else:
            return {"action": "HOLD", "reversal_risk": reversal_risk}
```

**Impact:** Entry/exit decisions in ~100ms instead of ~5s. Can evaluate EVERY open position EVERY tick. Currently only escalates to Claude for borderline cases — with Jev, you get continuous probabilistic assessment of every position.

---

### 6. SETUP QUALITY GATES (Tier 3)

**Current:** `risk_manager.py:66` — `vet_setup` uses hard thresholds (min confidence, min R:R)  
**Problem:** Binary pass/fail misses nuanced quality signals  
**Jev enhancement:** Add multi-dimensional quality assessment

```python
def jev_vet_setup(setup: TradeSetup, backtest_results: dict) -> dict:
    with TypeSafeClient() as client:
        response = client.system_one(
            state={
                "setup": setup.dict(),
                "backtest": {
                    "win_rate": backtest_results["win_rate"],
                    "profit_factor": backtest_results["profit_factor"],
                    "max_drawdown": backtest_results["max_drawdown"],
                    "trade_count": backtest_results["n_trades"],
                    "avg_r_multiple": backtest_results["avg_r"],
                },
            },
            questions={
                "backtest_credible": Noul(
                    instructions=(
                        "Is the backtest result statistically credible? "
                        "Consider trade count, consistency, and whether results "
                        "could be from curve-fitting."
                    ),
                ),
                "setup_confluence": Score(
                    instructions="How many independent signals support this trade setup?",
                    criteria=[
                        "Single signal — one indicator or pattern only",
                        "Two signals — some confluence",
                        "Three+ signals — strong multi-factor confluence",
                    ],
                ),
                "risk_reward_realistic": Noul(
                    instructions=(
                        "Are the target and stop-loss levels realistic based on "
                        "the stock's ATR and recent price action?"
                    ),
                ),
                "overfitted": Noul(
                    instructions=(
                        "Does this setup show signs of overfitting — too-perfect backtest, "
                        "narrow conditions, or cherry-picked parameters?"
                    ),
                ),
            },
        )

    credible = response.answers["backtest_credible"].noul
    confluence = response.answers["setup_confluence"].score / 2
    rr_realistic = response.answers["risk_reward_realistic"].noul
    overfitted = response.answers["overfitted"].noul

    quality = 0.3 * credible + 0.3 * confluence + 0.25 * rr_realistic + 0.15 * (1 - overfitted)
    return {
        "quality_score": quality,
        "pass": quality > 0.5 and overfitted < 0.6 and credible > 0.4,
        "details": {
            "backtest_credible": credible,
            "confluence": confluence,
            "rr_realistic": rr_realistic,
            "overfit_risk": overfitted,
        },
    }
```

**Impact:** Catches overfitted setups and unrealistic R:R — things hard-coded rules miss. The overfit detection alone could prevent significant losses from curve-fitted strategies.

---

### 7. POST-TRADE REVIEW SCORING (Review)

**Current:** `review_store.py` — Stores reviews, but scoring is manual or LLM  
**Jev enhancement:** Automated multi-dimension trade grading

```python
def grade_trade(trade: ExecutedTrade, plan_leg: TradeLeg) -> dict:
    with TypeSafeClient() as client:
        response = client.system_one(
            state={
                "plan": {
                    "entry_price": plan_leg.entry_price,
                    "stop_loss": plan_leg.stop_loss,
                    "target_1": plan_leg.target_1,
                    "strategy": plan_leg.strategy.value,
                },
                "execution": {
                    "actual_entry": trade.entry_price,
                    "actual_exit": trade.exit_price,
                    "entry_slippage_pct": trade.entry_slippage_pct,
                    "exit_reason": trade.exit_reason,
                    "duration_minutes": trade.duration_minutes,
                    "pnl_pct": trade.pnl_pct,
                    "r_multiple": trade.r_multiple,
                },
            },
            questions={
                "execution_quality": Score(
                    instructions="How well was this trade executed vs. the plan?",
                    criteria=[
                        "Poor — large slippage, missed entry/exit, deviated from plan",
                        "Acceptable — minor deviations, reasonable execution",
                        "Good — executed close to plan with minimal slippage",
                        "Excellent — textbook execution, optimal timing",
                    ],
                ),
                "plan_was_good": Noul(
                    instructions="Was the original trade plan well-designed (regardless of outcome)?",
                ),
                "learned_something": Noul(
                    instructions="Does this trade reveal a pattern worth noting for future reference?",
                ),
            },
        )

    return {
        "execution_grade": response.answers["execution_quality"].score / 3,
        "plan_quality": response.answers["plan_was_good"].noul,
        "notable": response.answers["learned_something"].noul > 0.6,
    }
```

---

### 8. NEWS/ANNOUNCEMENT SCREENING (New Capability)

**Currently:** Does not exist — no news integration  
**Jev enables:** Fast, cheap screening of news for trading-relevant signals

```python
def screen_news(headlines: list[dict], watchlist: list[str]) -> list[dict]:
    """Screen news headlines for trading-relevant signals. ~100ms per batch."""
    state = {
        "headlines": headlines,  # [{title, source, time, snippet}]
        "watchlist": watchlist,
    }
    questions = {
        "market_moving": Noul(
            instructions="Do any of these headlines contain market-moving information?",
        ),
        "sentiment_shift": Choice(
            instructions="What is the dominant sentiment shift in these headlines?",
            criteria={
                "bullish": "Positive catalysts — upgrades, beats, policy support",
                "bearish": "Negative catalysts — downgrades, misses, regulatory risk",
                "neutral": "No clear directional signal",
                "mixed": "Conflicting signals across headlines",
            },
        ),
        "urgency": Noul(
            instructions="Do these headlines require immediate action (position adjustment)?",
        ),
    }
    with TypeSafeClient() as client:
        response = client.system_one(state=state, questions=questions)

    return {
        "market_moving": response.answers["market_moving"].noul,
        "sentiment": response.answers["sentiment_shift"].choice,
        "sentiment_confidence": response.answers["sentiment_shift"].confidence,
        "urgent": response.answers["urgency"].noul > 0.8,
    }
```

**Impact:** At $0.042/Mtok, you can screen news every 60 seconds for pennies. Currently impossible with Claude's pricing. Enables event-driven position management.

---

### 9. LIVE REGIME MONITOR (New Capability)

**Currently:** Regime classified once pre-market, static all day  
**Jev enables:** Continuous regime reassessment during market hours

```python
async def regime_monitor_tick(market_data: dict, current_regime: str) -> dict:
    """Run every 5 minutes during market hours. ~100ms."""
    async with AsyncTypeSafeClient() as client:
        response = await client.system_one(
            state=market_data,
            questions={
                "regime_changed": Noul(
                    instructions=f"Has the market regime changed from `{current_regime}`?",
                ),
                "new_regime": Choice(
                    instructions="What is the current market regime?",
                    criteria={
                        "trending_up": "Broad uptrend",
                        "trending_down": "Broad downtrend",
                        "range_bound": "Sideways, no conviction",
                        "volatile": "High volatility, sharp swings",
                        "low_vol_squeeze": "Compressed volatility, breakout imminent",
                    },
                ),
            },
        )
    changed = response.answers["regime_changed"].noul
    if changed > 0.7:
        return {
            "regime_shift": True,
            "new_regime": response.answers["new_regime"].choice,
            "confidence": response.answers["new_regime"].confidence,
        }
    return {"regime_shift": False}
```

**Impact:** Regime shifts mid-day (e.g., sudden VIX spike) now trigger position reassessment within 5 minutes. Currently the bot trades the morning's regime assumption all day.

---

## Architecture Summary

```
BEFORE (Current):
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Tier 1     │────▸│  Tier 2/3    │────▸│  Executor   │
│  Determin.  │     │  Claude LLM  │     │  Rules +    │
│  Screening  │     │  5-15s/call  │     │  LLM escape │
│  ~1s        │     │  ~$0.10/run  │     │  3-8s/call  │
└─────────────┘     └──────────────┘     └─────────────┘

AFTER (With Jev):
┌──────────────────┐  ┌──────────────┐  ┌─────────────┐  ┌──────────────┐
│  Tier 1          │  │  Tier 2      │  │  Tier 3     │  │  Executor    │
│  Determin.       │  │  JEV         │  │  Claude LLM │  │  Rules + JEV │
│  + 🟡 JEV INTEL  │─▸│  Regime ✓    │─▸│  Deep setup  │─▸│  Entry ✓     │
│  Rescue pool ✓   │  │  Sectors ✓   │  │  design only │  │  Exit ✓      │
│  Adaptive wt ✓   │  │  Shortlist ✓ │  │  (kept)      │  │  Regime ✓    │
│  Smart caps ✓    │  │  100ms/call  │  │              │  │  News ✓      │
│  ~1.5s           │  │  ~$0.001/run │  │              │  │  100ms/call  │
└──────────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
```

### What Stays on Claude
- **Tier 3 deep analysis** — genuine reasoning: designing entry/exit strategies, writing trade rationale, adversarial review of setups. This needs text generation.
- **Complex edge cases** — when Jev confidence is very low, escalate to Claude as ultimate fallback.

### What Moves to Jev
- **Tier 1:** Rescue pool, regime-adaptive weights, smart sector caps (NEW)
- Market regime classification (Choice)
- Sector rotation scoring (Score + Noul)  
- Candidate shortlisting (composite Score)
- Entry guard enhancement (Noul + Score)
- LLM escalator replacement (Noul + Choice)
- Exit decisions (Noul + Score)
- Setup quality gates (Noul × 4)
- Post-trade grading (Score + Noul)

### New Capabilities (Only Possible with Jev's Speed/Cost)
- **Intelligent screening with rescue pool (Tier 1)**
- Live regime monitoring (every 5 min)
- News/announcement screening (every 60s)
- Per-position continuous risk assessment (every tick)
- Per-tick momentum quality scoring (real-time)

---

## Cost Comparison

| Component | Current (Claude) | With Jev | Savings |
|-----------|-----------------|----------|---------|
| Tier 1 intelligent screening | N/A (deterministic only) | ~$0.001/run | New capability |
| Regime classification | ~$0.02/call | ~$0.00004/call | 500x |
| Sector analysis | ~$0.03/call | ~$0.00006/call | 500x |
| Stock shortlisting (50 stocks) | ~$0.05/call | ~$0.002/run | 25x |
| Entry decisions (per day) | ~$0.10 (5-10 escalations) | ~$0.001 (every tick) | 100x |
| Exit decisions (per day) | ~$0.05 (escalations only) | ~$0.001 (every tick) | 50x |
| Live regime monitor | N/A (too expensive) | ~$0.003/day | New |
| News screening | N/A (too expensive) | ~$0.005/day | New |
| **Daily total** | **~$0.25-0.50** | **~$0.015** | **~95%** |

---

## Implementation Priority

| Priority | Integration | Effort | Impact |
|----------|-------------|--------|--------|
| **P0** | Replace LLM escalator with Jev | 1 day | 50x faster entry/exit decisions |
| **P0** | Entry guard enhancement | 1 day | Calibrated probabilities vs. hard rules |
| **P1** | Regime classification | 0.5 day | Faster pre-market + live monitoring |
| **P1** | Sector scoring | 0.5 day | Granular sector rotation signals |
| **P1** | Intelligent Tier 1 screening | 1 day | Rescue pool + adaptive weights + smart caps |
| **P1** | Live regime monitor | 0.5 day | Catch intraday regime shifts |
| **P2** | Stock shortlisting | 1 day | More transparent ranking |
| **P2** | Setup quality gates | 0.5 day | Overfit detection |
| **P2** | News screening | 1 day | New: event-driven trading |
| **P3** | Post-trade review | 0.5 day | Automated trade grading |

**Total estimated effort:** ~8 days for full integration.

---

## Technical Setup

```bash
# 1. Install SDK
pip install typesafe-sdk

# 2. Add API key to .env
echo "TYPESAFE_API_KEY=ts_..." >> .env

# 3. Add to config.toml
# [jev]
# model = "jev-latest"
# entry_confidence_threshold = 0.6
# exit_confidence_threshold = 0.75
# regime_check_interval_minutes = 5
```

Create a thin wrapper at `core/jev_client.py` that:
1. Reads API key from env
2. Uses `AsyncTypeSafeClient` for market-hours calls
3. Logs all questions/answers to `execution_decisions` table for auditability
4. Falls back to Claude when Jev confidence < 0.3

---

*The single biggest win: replacing the LLM escalator. Every 5-second tick, every open position gets a probabilistic exit assessment. That's the difference between "check occasionally when things look bad" and "continuous intelligent monitoring."*
