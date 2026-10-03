# Trading Bot: Complete Decision Workflow
### Every decision point, what runs it today, what should run it tomorrow

---

## PHASE 1: PRE-MARKET ANALYSIS (7:00 AM – 9:00 AM)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  TIER 1 — DETERMINISTIC SCREENING                                          ║
║  screener.py:46 → ~1500 stocks → ~50-100 candidates                       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                             ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 1. LIQUIDITY FILTER                    🟢 DETERMINISTIC                │
║  │    liquidity_filter.py                                                  │
║  │    • Min volume threshold                                               │
║  │    • Min price threshold                                                │
║  │    • Min market cap                                                     │
║  │    ~1500 → ~300 stocks passed, ~1200 rejected                           │
║  │    STAYS DETERMINISTIC — safety floor, never bypassed                   │
║  └──────────────┬─────────────────────────┬────────────┘                   ║
║                  │ passed                   │ rejected                       ║
║                  ▼                          ▼                                ║
║  ┌──────────────────────┐  ┌───────────────────────────────┐               ║
║  │ ~300 liquid stocks   │  │ 1b. 🟡 JEV RESCUE POOL (NEW) │               ║
║  │ (proceed to scoring) │  │     intelligent_screener.py   │               ║
║  │                      │  │                               │               ║
║  │                      │  │ Near-misses (≥60% of each     │               ║
║  │                      │  │ threshold) get Jev eval:      │               ║
║  │                      │  │                               │               ║
║  │                      │  │ Noul: unusual_activity?       │               ║
║  │                      │  │ Noul: tradeable_despite?      │               ║
║  │                      │  │ Score: opportunity_quality     │               ║
║  │                      │  │                               │               ║
║  │                      │  │ rescue = 0.4×unusual          │               ║
║  │                      │  │       + 0.3×tradeable         │               ║
║  │                      │  │       + 0.3×quality           │               ║
║  │                      │  │ rescue > 0.55 → SAVED         │               ║
║  │                      │  │                               │               ║
║  │                      │  │ Example: INFY vol 95K vs      │               ║
║  │                      │  │ 100K min, but today vol 5x    │               ║
║  │                      │  │ → rescued with bonus score    │               ║
║  │                      │  │                               │               ║
║  │                      │  │ ~10-20 stocks rescued/day     │               ║
║  │                      │  │ ~100ms per stock, ~$0.001     │               ║
║  └──────────┬───────────┘  └──────────────┬────────────────┘               ║
║              │                             │                                ║
║              └──────────┬──────────────────┘                                ║
║                         ▼                                                   ║
║              ~310-320 candidates                                            ║
║                         │                                                   ║
║                         ▼                                                   ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 2. 9-FACTOR COMPOSITE SCORING                                           │
║  │    factor_scorer.py:28                                                  │
║  │                                                                          │
║  │    🟢 DETERMINISTIC CORE (kept):                                        │
║  │    ┌──────────────────────────────────────────┐                         ║
║  │    │ volume_surge        × weight             │                         ║
║  │    │ relative_strength   × weight             │                         ║
║  │    │ atr_expansion       × weight             │                         ║
║  │    │ price_structure     × weight             │                         ║
║  │    │ delivery_pct        × weight             │                         ║
║  │    │ sector_momentum     × weight             │                         ║
║  │    │ gap_analysis        × weight             │                         ║
║  │    │ candlestick_pattern × weight             │                         ║
║  │    │ volume_profile      × weight             │                         ║
║  │    └──────────────────────────────────────────┘                         ║
║  │                                                                          │
║  │    + 🟡 JEV REGIME-ADAPTIVE WEIGHTS (NEW)                               │
║  │    ──────────────────────────────────────                                │
║  │    Weights shift based on today's regime:                               │
║  │                                                                          │
║  │    TRENDING UP:                                                          │
║  │      relative_strength ×1.5  sector_momentum ×1.4                      │
║  │      volume_surge ×1.3       price_structure ×0.8                      │
║  │                                                                          │
║  │    RANGE BOUND:                                                          │
║  │      price_structure ×1.5    volume_profile ×1.4                       │
║  │      candlestick ×1.3        relative_strength ×0.7                    │
║  │                                                                          │
║  │    VOLATILE:                                                             │
║  │      atr_expansion ×1.5      volume_surge ×1.4                         │
║  │      gap_analysis ×1.4       price_structure ×0.7                      │
║  │                                                                          │
║  │    Blend scales with regime_confidence:                                  │
║  │      conf 0.3 → weights barely shift (ambiguous)                       │
║  │      conf 0.85 → full adaptation                                       │
║  │                                                                          │
║  │    + Rescued stocks get jev_bonus on composite score                    │
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              ▼                                              ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 3. SECTOR FILTER                                                        │
║  │                                                                          │
║  │    🟢 DETERMINISTIC CORE (kept):                                        │
║  │    • Pearson ρ > 0.7 → drop weaker stock                               │
║  │                                                                          │
║  │    + 🟡 JEV SMART SECTOR CAPS (NEW, replaces fixed cap)                │
║  │    ───────────────────────────────────────────────                       │
║  │    Sector caps flex by Jev sector_strength scores:                      │
║  │                                                                          │
║  │    sector_strength > 0.7 → cap = base + 2 (strong)                     │
║  │    sector_strength > 0.5 → cap = base + 1                              │
║  │    sector_strength < 0.3 → cap = base - 1 (weak)                      │
║  │    otherwise             → cap = base (unchanged)                      │
║  │                                                                          │
║  │    Example (base cap = 3):                                              │
║  │      Banking strength=0.85 → cap=5 (gets more slots)                   │
║  │      IT strength=0.25      → cap=2 (loses a slot)                      │
║  │      Pharma strength=0.40  → cap=3 (unchanged)                         │
║  │                                                                          │
║  │    Result: opportunities go where strength actually is                  │
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              ▼                                              ║
║                     50-100 candidates                                       ║
║              (smarter, regime-aware, with rescued stocks)                   ║
╚══════════════════════════════════════════════════════════════════════════════╝
                               │
                               ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║  TIER 2 — MARKET CONTEXT + SHORTLISTING                                    ║
║  tier2_analyzer.py → 50-100 → ~10 stocks                                  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                             ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 4. MARKET REGIME CLASSIFICATION                                         ║
║  │    tier2_analyzer.py:30                                                 ║
║  │                                                                          ║
║  │    TODAY:  🔴 CLAUDE LLM  (~5s, ~$0.02)                                ║
║  │    ───────────────────────────────────────                               ║
║  │    Claude reads Nifty, VIX, FII/DII, breadth                           ║
║  │    Returns: regime label + text reasoning                                ║
║  │    Problem: slow, no calibrated confidence, overkill                    ║
║  │                                                                          ║
║  │    TOMORROW:  🟡 JEV CHOICE  (~100ms, ~$0.00004)                       ║
║  │    ───────────────────────────────────────                               ║
║  │    Choice: trending_up/down, range_bound, volatile, low_vol_squeeze     ║
║  │    + Score: trend_strength (0-3)                                        ║
║  │    + Score: institutional_sentiment (0-4)                               ║
║  │    Returns: regime + confidence + probabilities                          ║
║  │    Bonus: if confidence < 0.4, regime is genuinely ambiguous            ║
║  │           → trade smaller / skip directional strategies                 ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              ▼                                              ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 5. SECTOR ROTATION ANALYSIS                                             ║
║  │    tier2_analyzer.py:57                                                 ║
║  │                                                                          ║
║  │    TODAY:  🔴 CLAUDE LLM  (~5s, ~$0.03)                                ║
║  │    ───────────────────────────────────────                               ║
║  │    Claude reads sector indices, flows, news                             ║
║  │    Returns: leaders/laggards text                                       ║
║  │                                                                          ║
║  │    TOMORROW:  🟡 JEV SCORE + NOUL  (~150ms, ~$0.00006)                 ║
║  │    ───────────────────────────────────────                               ║
║  │    Per sector (9 sectors, 18 questions, 1 call):                        ║
║  │      Score: momentum (0-4)                                              ║
║  │      Noul:  rotation_in (money flowing in?)                             ║
║  │    Code: composite = 0.6 × momentum + 0.4 × rotation                   ║
║  │    Returns: ranked sector list with scores                              ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              ▼                                              ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 6. REGIME → STRATEGY GATE              🟢 DETERMINISTIC                │
║  │    pipeline.py:29                                                       ║
║  │    ┌─────────────────────────────────────────┐                          ║
║  │    │ trending_up   → momentum, breakout, ORB │                          ║
║  │    │ trending_down → short momentum, reversal│                          ║
║  │    │ range_bound   → mean reversion, range   │                          ║
║  │    │ volatile      → ORB, gap fill           │                          ║
║  │    │ low_vol_squeeze → breakout              │                          ║
║  │    └─────────────────────────────────────────┘                          ║
║  │    STAYS DETERMINISTIC — lookup table, no AI needed                     ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              ▼                                              ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 7. CANDIDATE SHORTLISTING                                               ║
║  │    tier2_analyzer.py:81                                                 ║
║  │                                                                          ║
║  │    TODAY:  🔴 CLAUDE LLM  (~10s, ~$0.05)                               ║
║  │    ───────────────────────────────────────                               ║
║  │    Claude reads all 50-100 candidates in one prompt                     ║
║  │    Returns: top 10-15 picks with reasoning                              ║
║  │    Problem: context rot with 50 stocks, opaque ranking                  ║
║  │                                                                          ║
║  │    TOMORROW:  🟡 JEV COMPOSITE SCORING  (~1s async, ~$0.002)           ║
║  │    ───────────────────────────────────────                               ║
║  │    Per stock (4 questions each):                                        ║
║  │      Score: setup_quality (0-4)                                         ║
║  │      Noul:  regime_alignment                                            ║
║  │      Noul:  risk_reward_attractive                                      ║
║  │      Noul:  volume_conviction                                           ║
║  │    Code: composite = weighted sum → sort → top 10                       ║
║  │    + Filter: setup_confidence > 0.4                                     ║
║  │    Returns: transparent ranked list with per-dimension scores           ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              ▼                                              ║
║                        ~10 shortlisted                                      ║
╚══════════════════════════════════════════════════════════════════════════════╝
                               │
                               ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║  TIER 3 — DEEP ANALYSIS + SETUP DESIGN (per stock)                         ║
║  tier3_analyzer.py → 10 stocks → 5-8 trade setups                         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                             ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 8. BACKTEST ALL STRATEGIES             🟢 DETERMINISTIC                │
║  │    pipeline.py:661 → backtester.py                                      ║
║  │    For each stock × each allowed strategy:                              ║
║  │      Walk-forward backtest → win rate, PF, drawdown                     ║
║  │    STAYS DETERMINISTIC — pure computation                               ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              ▼                                              ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 9. QUALITY GATES                       🟢 DETERMINISTIC                │
║  │    quality_gates.py                                                     ║
║  │    • Min trades threshold                                               ║
║  │    • Min win rate                                                       ║
║  │    • Min profit factor                                                  ║
║  │    STAYS DETERMINISTIC                                                  ║
║  │                                                                          ║
║  │    + NEW 🟡 JEV OVERFIT DETECTION  (~100ms)                            ║
║  │    ──────────────────────────────────                                    ║
║  │      Noul: backtest_credible (statistical validity)                     ║
║  │      Noul: overfitted (curve-fitting signals)                           ║
║  │      Noul: risk_reward_realistic (ATR-based check)                      ║
║  │      Score: setup_confluence (1-3 independent signals)                  ║
║  │      Filter: overfit > 0.6 → REJECT                                    ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              ▼                                              ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 10. DEEP ANALYSIS + SETUP DESIGN     🔴 CLAUDE LLM (STAYS)            ║
║  │     tier3_analyzer.py (deep_analyze)                                    ║
║  │     Claude reads: technicals, backtest, regime, sector                  ║
║  │     GENERATES: entry/exit logic, specific prices, rationale             ║
║  │     ⚠️  CANNOT MOVE TO JEV — requires text generation                  ║
║  │                                                                          ║
║  │     But: fewer stocks reach here (Jev pre-filtered)                     ║
║  │     Before: 10 stocks × Claude = 10 calls                              ║
║  │     After:  6-7 stocks × Claude = 6-7 calls (Jev filtered 3-4)         ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              ▼                                              ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 11. ADVERSARIAL REVIEW               🔴 CLAUDE LLM (STAYS)            ║
║  │     tier3_analyzer.py (validate_portfolio)                              ║
║  │     Claude reviews: correlation, concentration, regime fit              ║
║  │     GENERATES: risk warnings, counter-arguments                         ║
║  │     ⚠️  CANNOT MOVE TO JEV — requires reasoning + prose                ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              ▼                                              ║
║                     5-8 trade setups                                        ║
╚══════════════════════════════════════════════════════════════════════════════╝
                               │
                               ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║  PLAN CONSTRUCTION + RISK SIZING                                            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                             ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 12. VET SETUP                          🟢 DETERMINISTIC                │
║  │     risk_manager.py:66                                                  ║
║  │     • confidence >= min_confidence (0.6)                                ║
║  │     • reward:risk >= min_rr (2.0)                                       ║
║  │     STAYS DETERMINISTIC — threshold checks                              ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              ▼                                              ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 13. POSITION SIZING                    🟢 DETERMINISTIC                │
║  │     risk_manager.py:46                                                  ║
║  │     shares = (capital × risk_pct) / stop_distance                       ║
║  │     STAYS DETERMINISTIC — pure math                                     ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              ▼                                              ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 14. SELECT LEGS                        🟢 DETERMINISTIC                │
║  │     risk_manager.py:88                                                  ║
║  │     • Rank by confidence                                                ║
║  │     • Size to fit exposure ceiling (50% capital)                        ║
║  │     • Max trades per day cap                                            ║
║  │     STAYS DETERMINISTIC — ranking + allocation math                     ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              ▼                                              ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 15. SAVE TRADE PLAN                    🟢 DETERMINISTIC                │
║  │     plan_store.py → trade_plans/YYYY-MM-DD.json                         ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              ▼                                              ║
║                   PLAN READY (JSON file)                                    ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## PHASE 2: MARKET HOURS EXECUTION (9:15 AM – 3:30 PM)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  EXECUTION START (9:15 AM)                                                  ║
║  executor.py:106 → start()                                                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                             ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 16. VET PLAN FOR EXECUTION             🟢 DETERMINISTIC                │
║  │     risk_manager.py:135                                                 ║
║  │     • Plan age < 24 hours                                               ║
║  │     • Capital available                                                 ║
║  │     • Position limit not reached                                        ║
║  │     STAYS DETERMINISTIC                                                 ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              ▼                                              ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 17. VET LEG AT OPEN                    🟢 DETERMINISTIC                │
║  │     risk_manager.py:163                                                 ║
║  │     • Price drift from plan < max_drift_pct                             ║
║  │     STAYS DETERMINISTIC                                                 ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              ▼                                              ║
║               Begin tick loop (every 5 seconds)                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
                               │
                               ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║  TICK LOOP — EVERY 5 SECONDS                                                ║
║  executor.py:152 → tick()                                                  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                             ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 18. KILL SWITCH CHECK                  🟢 DETERMINISTIC                │
║  │     executor.py:163 → risk_manager.py:178                               ║
║  │     if realised_pnl < -(capital × 0.02):                               ║
║  │         CLOSE ALL → STOP TRADING                                        ║
║  │     STAYS DETERMINISTIC — non-negotiable safety                         ║
║  └──────────────────┬─────────────────┬────────────────┘                   ║
║                      │ OK              │ BREACHED                           ║
║                      ▼                 ▼                                    ║
║                  continue          EMERGENCY EXIT                           ║
║                      │                                                      ║
║  ╔═══════════════════╧═══════════════════════════════╗                      ║
║  ║  NEW 🟡 JEV: LIVE REGIME MONITOR (every 5 min)   ║                      ║
║  ║  ─────────────────────────────────────────────    ║                      ║
║  ║  Choice: current regime                           ║                      ║
║  ║  Noul: regime_changed from morning classification ║                      ║
║  ║  If changed (noul > 0.7):                         ║                      ║
║  ║    → Flag open positions in wrong-regime strats   ║                      ║
║  ║    → Tighten stops on directional trades          ║                      ║
║  ║    → Pause new entries until reassessed            ║                      ║
║  ║  ~100ms, runs inside tick without blocking        ║                      ║
║  ╚═══════════════════╤═══════════════════════════════╝                      ║
║                      │                                                      ║
║  ╔═══════════════════╧═══════════════════════════════╗                      ║
║  ║  NEW 🟡 JEV: NEWS SCREENING (every 60s)          ║                      ║
║  ║  ─────────────────────────────────────────────    ║                      ║
║  ║  Noul: market_moving headline detected            ║                      ║
║  ║  Choice: sentiment (bullish/bearish/neutral)      ║                      ║
║  ║  Noul: urgent (needs immediate action)            ║                      ║
║  ║  If urgent + market_moving > 0.8:                 ║                      ║
║  ║    → Tighten all stops                            ║                      ║
║  ║    → Pause new entries                            ║                      ║
║  ║  ~100ms, negligible cost                          ║                      ║
║  ╚═══════════════════╤═══════════════════════════════╝                      ║
║                      │                                                      ║
║                      ▼                                                      ║
║       ┌──── For each leg in plan ────┐                                     ║
║       │                               │                                     ║
║       ▼                               ▼                                     ║
║  PENDING ENTRY                   OPEN POSITION                              ║
║  (not yet filled)                (filled, managing)                          ║
║       │                               │                                     ║
║       ▼                               ▼                                     ║
║  ┌─ ENTRY PATH ─┐              ┌─ EXIT PATH ─┐                            ║
║  │ Steps 19-22   │              │ Steps 23-27  │                            ║
║  └───────────────┘              └──────────────┘                            ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

### ENTRY PATH (Steps 19-22)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  ENTRY DECISION CHAIN                                                       ║
║  executor.py:203 → _evaluate_entry()                                       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                             ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 19. MOMENTUM SCORING                   🟢 DETERMINISTIC                │
║  │     momentum_scorer.py:36 → update()                                    ║
║  │                                                                          ║
║  │     From 1m + 5m candles, computes:                                     ║
║  │     ┌────────────────────────────────────────┐                          ║
║  │     │ momentum_1m   [-100, +100]             │                          ║
║  │     │ momentum_5m   [-100, +100]             │                          ║
║  │     │ volume_ratio   (vs 20-day avg)         │                          ║
║  │     │ volume_trend   (rising/falling/flat)   │                          ║
║  │     │ vwap_position  (above/below/at)        │                          ║
║  │     │ patterns       (engulfing, doji, etc)  │                          ║
║  │     │ body_dominance (0-1)                   │                          ║
║  │     │ trend_alignment (bool)                 │                          ║
║  │     │ strength       (strong/moderate/weak)  │                          ║
║  │     └────────────────────────────────────────┘                          ║
║  │     Formula: direction × (body% × 0.6 + close_pos × 0.4)              ║
║  │     Last candle weighted 3×                                             ║
║  │     STAYS DETERMINISTIC — fast numeric computation                      ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              ▼                                              ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 20. ENTRY GUARD (10 RULES)             🟢 DETERMINISTIC                │
║  │     entry_guard.py:24 → evaluate()                                      ║
║  │                                                                          ║
║  │     Rule 1:  Window expired?           → VETO (1.0)                    ║
║  │     Rule 2:  Max wait expired?         → VETO (1.0)                    ║
║  │     Rule 3:  Price drift > max%?       → VETO (1.0)                    ║
║  │     Rule 4:  LONG + mom_5m < -60?      → VETO (0.9)                    ║
║  │     Rule 5:  SHORT + mom_5m > +60?     → VETO (0.9)                    ║
║  │     Rule 6:  Volume ratio < 0.3?       → WAIT (0.7)                    ║
║  │     Rule 7:  No alignment + low body?  → WAIT (0.6)                    ║
║  │     Rule 8:  LONG below VWAP falling?  → WAIT (0.6)                    ║
║  │     Rule 9:  Counter-pattern detected? → WAIT (0.5)                    ║
║  │     Rule 10: Aligned + volume + trend? → ENTER (0.8)                   ║
║  │     Gray zone: none matched            → conf 0.39                     ║
║  │                                                                          ║
║  │     STAYS DETERMINISTIC — hard vetoes are safety rails                  ║
║  │                                                                          ║
║  │     + NEW 🟡 JEV ENHANCEMENT (parallel with rules)                     ║
║  │     ────────────────────────────────────────────                         ║
║  │     Runs alongside deterministic guard, doesn't override vetoes:        ║
║  │       Noul:  enter_now (momentum + volume + VWAP alignment)            ║
║  │       Score: momentum_quality (0-4: hostile → ideal)                   ║
║  │       Noul:  fading_risk (move already played out?)                    ║
║  │     Enriches confidence score for borderline cases                      ║
║  │     Example: Rule 10 says ENTER (0.8) but Jev fading_risk              ║
║  │              is 0.7 → downgrade to WAIT                                ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              │                                              ║
║              ┌───────────────┼───────────────┐                             ║
║              ▼               ▼               ▼                              ║
║           VETO            ENTER     WAIT / GRAY ZONE                       ║
║           (skip)          (order)    (conf < 0.4)                          ║
║              │               │               │                              ║
║              ▼               ▼               ▼                              ║
║           done          place order   ┌──────────────┐                     ║
║                                       │ 21. ESCALATE │                     ║
║                                       └──────┬───────┘                     ║
║                                              ▼                              ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 21. ESCALATION DECISION                                                 ║
║  │     executor.py:203 — if confidence < 0.4 AND not degraded             ║
║  │                                                                          ║
║  │     TODAY:  🔴 CLAUDE LLM  (~5-10s, ~$0.02)                            ║
║  │     ───────────────────────────────────────                              ║
║  │     llm_escalator.py:46 → evaluate_entry()                             ║
║  │     • Max 5 escalations/day                                             ║
║  │     • 10s timeout                                                       ║
║  │     • Prompt: leg + candles + momentum → Claude                         ║
║  │     • Returns: {action, confidence, reasoning}                          ║
║  │     • Problem: 5-10s in a 5s tick loop = missed ticks                  ║
║  │     • Fallback on timeout: WAIT                                         ║
║  │                                                                          ║
║  │     TOMORROW:  🟡 JEV  (~100ms, ~$0.00004)                             ║
║  │     ───────────────────────────────────────                              ║
║  │     Noul:   should_enter (setup thesis confirmed by price action?)     ║
║  │     Noul:   invalidated (setup broken?)                                ║
║  │     Choice: timing (enter_now / wait_5min / skip)                      ║
║  │     No daily cap needed — cheap enough to run every tick                ║
║  │     No timeout risk — 100ms always fits in 5s tick                     ║
║  │     Returns: structured decision with confidence                        ║
║  │                                                                          ║
║  │     FALLBACK: Jev confidence < 0.3 → THEN escalate to Claude           ║
║  │     (happens maybe 1-2×/day instead of 5-10×)                          ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              │                                              ║
║              ┌───────────────┼───────────────┐                             ║
║              ▼               ▼               ▼                              ║
║            SKIP          ENTER            WAIT                             ║
║           (done)        (order)      (reassess next                        ║
║                                       tick in 5s)                          ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

### EXIT PATH (Steps 23-27)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  EXIT DECISION CHAIN (per open position, every 5s tick)                     ║
║  executor.py:337 → _manage_open_leg_smart()                                ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                             ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 22. HARD EXIT CHECKS                  🟢 DETERMINISTIC                 │
║  │     exit_manager.py:25 → decide()                                       ║
║  │                                                                          ║
║  │     Check 1: Time ≥ 15:10?     → CLOSE (square off)                    ║
║  │     Check 2: Price ≤ stop?     → CLOSE (stop loss hit)                 ║
║  │     Check 3: Price ≥ target 2? → CLOSE (full target)                   ║
║  │     Check 4: Price ≥ target 1? → BOOK 50% + trail stop                 ║
║  │                                                                          ║
║  │     STAYS DETERMINISTIC — non-negotiable safety                         ║
║  │     These ALWAYS override any AI decision                               ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              │                                              ║
║                    None triggered (HOLD)                                    ║
║                              │                                              ║
║                              ▼                                              ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 23. ADAPTIVE EXIT (MOMENTUM-BASED)     🟢 DETERMINISTIC                │
║  │     adaptive_exit_manager.py                                            ║
║  │     • Track peak momentum since entry                                   ║
║  │     • If momentum fallen X% from peak → tighten stop                   ║
║  │     STAYS DETERMINISTIC                                                 ║
║  │                                                                          ║
║  │     + NEW 🟡 JEV CONTINUOUS ASSESSMENT (every tick!)                    ║
║  │     ──────────────────────────────────────────────                       ║
║  │     Noul:  exit_now (momentum exhausted + reversal signals?)           ║
║  │     Noul:  momentum_exhaustion (drive fading?)                         ║
║  │     Score: reversal_risk (0-4: very unlikely → very likely)            ║
║  │                                                                          ║
║  │     Decision matrix:                                                    ║
║  │     ┌───────────────────┬──────────────────────────┐                    ║
║  │     │ exit_now > 0.8    │ → EXIT immediately       │                    ║
║  │     │ reversal > 0.7    │                           │                    ║
║  │     │  + exhaustion>0.6 │ → TIGHTEN STOP           │                    ║
║  │     │ otherwise         │ → HOLD (with risk score) │                    ║
║  │     └───────────────────┴──────────────────────────┘                    ║
║  │                                                                          ║
║  │     THIS IS THE BIGGEST WIN:                                            ║
║  │     Today: exit intelligence only fires on explicit escalation          ║
║  │     Tomorrow: every position evaluated every 5 seconds                  ║
║  │     Cost: ~$0.00004 × 12 ticks/min × 5 positions × 360 min = $0.009   ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              │                                              ║
║                   If deterministic + Jev both say HOLD                      ║
║                   but something feels off...                                ║
║                              │                                              ║
║                              ▼                                              ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 24. LLM EXIT ESCALATION (RARE)       🔴 CLAUDE (KEPT, RARE)           │
║  │     llm_escalator.py:55 → evaluate_exit()                              ║
║  │                                                                          ║
║  │     TODAY: Called when adaptive exit is uncertain                        ║
║  │     TOMORROW: Only called when Jev confidence < 0.3                    ║
║  │               on a position with significant unrealized P&L             ║
║  │     Maybe 0-1 calls/day instead of 3-5                                 ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              ▼                                              ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 25. TRAIL STOP RATCHET                 🟢 DETERMINISTIC                │
║  │     exit_manager.py:55                                                  ║
║  │     After T1 booked: move stop to breakeven                            ║
║  │     As price advances: ratchet stop higher                              ║
║  │     STAYS DETERMINISTIC                                                 ║
║  └─────────────────────────────────────────────────────┘                   ║
║                                                                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## PHASE 3: POST-MARKET (3:30 PM+)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  POST-TRADE REVIEW                                                          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                             ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 26. TRADE LOGGING                      🟢 DETERMINISTIC                │
║  │     database.py → executed_trades table                                 ║
║  │     Record: entry, exit, P&L, R-multiple, duration                     ║
║  │     STAYS DETERMINISTIC                                                 ║
║  └──────────────────────────┬──────────────────────────┘                   ║
║                              ▼                                              ║
║  ┌─────────────────────────────────────────────────────┐                   ║
║  │ 27. TRADE SCORECARD                                                     ║
║  │                                                                          ║
║  │     TODAY:  Manual or 🔴 CLAUDE                                         ║
║  │                                                                          ║
║  │     + NEW 🟡 JEV AUTOMATED GRADING  (~100ms)                           ║
║  │     ──────────────────────────────────                                   ║
║  │     Score: execution_quality (plan vs actual)                           ║
║  │     Noul:  plan_was_good (regardless of outcome)                       ║
║  │     Noul:  learned_something (notable pattern?)                        ║
║  │     Cheap enough to grade every single trade automatically              ║
║  └─────────────────────────────────────────────────────┘                   ║
║                                                                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## SUMMARY: DECISION ENGINE MAP

```
┌─────────────────────────────────────────────────────────────────────┐
│                    COMPLETE DECISION COUNT                           │
├─────────────────────────────────────┬───────────────────────────────┤
│  🟢 DETERMINISTIC (stays as core)    │  17 decision points           │
│     Liquidity filter (safety floor) │  • Hard rules, math, safety   │
│     9-factor scoring (base weights) │  • Kill switch, stops, sizing  │
│     Correlation filter (ρ check)    │  • Never bypassed by AI       │
│     Regime→strategy gate            │                               │
│     Backtest engine                 │                               │
│     Quality gates                   │                               │
│     Vet setup (confidence, R:R)     │                               │
│     Position sizing                 │                               │
│     Select legs                     │                               │
│     Vet plan for execution          │                               │
│     Vet leg at open                 │                               │
│     Kill switch (-2%)               │                               │
│     Momentum scoring                │                               │
│     Entry guard (10 rules)          │                               │
│     Hard exit checks                │                               │
│     Trail stop ratchet              │                               │
│     Trade logging                   │                               │
├─────────────────────────────────────┼───────────────────────────────┤
│  🟡 JEV (new + replaces Claude)     │  12 decision points           │
│  TIER 1 INTELLIGENCE:               │                               │
│     Rescue pool (near-misses) ←NEW  │  • 100ms per call             │
│     Regime-adaptive weights   ←NEW  │  • $0.00004 per call          │
│     Smart sector caps         ←NEW  │  • Calibrated confidence      │
│  TIER 2 REPLACEMENTS:               │  • Runs inside 5s tick        │
│     Regime classification     ←MOVE │  • Continuous, not occasional │
│     Sector scoring            ←MOVE │                               │
│     Candidate shortlisting    ←MOVE │                               │
│  EXECUTION LAYER:                    │                               │
│     Entry guard enhancement    ←NEW │                               │
│     Entry escalation          ←MOVE │                               │
│     Exit assessment           ←MOVE │                               │
│     Overfit detection          ←NEW │                               │
│     Live regime monitor        ←NEW │                               │
│     Trade grading              ←NEW │                               │
│    (News screening)            ←NEW │  (optional, needs feed)       │
├─────────────────────────────────────┼───────────────────────────────┤
│  🔴 CLAUDE LLM (stays, reduced)     │  3 decision points            │
│     Deep analysis + setup design    │  • Needs text generation      │
│     Adversarial review              │  • Needs multi-step reasoning │
│     Rare escalation fallback        │  • ~3-5 calls/day (was 15-20)│
└─────────────────────────────────────┴───────────────────────────────┘
```

```
HIERARCHY OF CONTROL (nothing overrides what's above it):

    ┌──────────────────────────────────────┐
    │  1. DETERMINISTIC SAFETY             │  Kill switch, stops, time
    │     Always runs. Never overridden.   │  cutoff, position limits
    ├──────────────────────────────────────┤
    │  2. DETERMINISTIC RULES              │  Entry guard hard vetoes,
    │     Run before any AI.               │  liquidity filter, sizing
    ├──────────────────────────────────────┤
    │  3. JEV (System One)                 │  Fast probabilistic layer.
    │     Enriches, never overrides #1/#2  │  Runs every tick. Cheap.
    ├──────────────────────────────────────┤
    │  4. CLAUDE (System Two)              │  Slow reasoning. Only for
    │     Only when Jev uncertain OR       │  generation tasks or when
    │     task needs text generation.      │  Jev confidence < 0.3
    └──────────────────────────────────────┘
```
