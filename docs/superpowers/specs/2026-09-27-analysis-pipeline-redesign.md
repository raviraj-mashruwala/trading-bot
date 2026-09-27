# Analysis Pipeline Redesign — Professional Grade

**Date:** 2026-09-27
**Status:** Approved (design review complete)
**Approach:** 3-Tier Professional Funnel (Approach A)

## Context

Current pipeline: 50 hardcoded Nifty stocks, yfinance 60-day data, 2 LLM calls (shortlist + setup), basic 5-strategy backtest, each run replaces previous TradePlan. Not production-grade.

Redesign goal: professional fund manager quality (1000+ Cr AUM perspective, 10+ YOE algo trading). Analysis is the core product — invest accordingly.

## Constraints

- **Capital:** ~4L INR + Kite intraday margin (~5x = ~20L effective)
- **Data source:** Zerodha Kite Connect API (paid, ~₹2000/month)
- **LLM:** Anthropic Claude API (pay-per-use credits, premium tier)
- **LLM calls:** Unlimited as needed for depth — not capped at 2
- **Execution:** Full Kite Connect integration (orders, positions, margins)
- **Python 3.13**, async, existing Next.js frontend

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Data Layer                               │
│  Kite Connect API → Local Cache (SQLite + Parquet)              │
│  Instruments · Daily candles · Intraday candles · Live ticks    │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│              Tier 1: Deterministic Screening                    │
│  ~1500 stocks → Liquidity filter → Multi-factor scoring         │
│  → Correlation filter → Pre-market enrichment → ~50-100 out     │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│              Tier 2: LLM Market & Sector Analysis               │
│  Call 1: Market regime → Call 2: Sector deep-dive               │
│  → Call 3: Candidate shortlist → ~10-15 out                     │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│              Tier 3: Deep Analysis & Validation                 │
│  Per-stock deep dive (1 call each) → Adversarial validation     │
│  → Approved setups with precise levels                          │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│              Backtesting Engine                                 │
│  Walk-forward · Monte Carlo · Transaction costs · Quality gates │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│              Persistence & Multi-Run Accumulation               │
│  Runs accumulate · Cross-run ranking · Staleness detection      │
│  → DailyPlan with ranked suggestions                            │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│              Kite Execution                                     │
│  Auth · Orders · Position monitor · Partial booking · Trail     │
│  Safety: daily loss limit, kill switch, network protection      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Section 1: Data Layer — Kite Connect Integration

### Instrument Universe

Daily refresh of all NSE instruments via `kite.instruments("NSE")`. Gives ~1800 actively traded equities with tokens, symbols, lot sizes, tick sizes.

Filter out: suspended stocks, illiquid (avg volume < 1L), penny stocks (< ₹10), SME segment. Working universe: ~1200-1500 tradable stocks.

### Local Data Cache (SQLite + Parquet)

Cannot hit Kite API for 1500 stocks every run (3 req/sec rate limit = 8+ minutes for one timeframe). Cache historical candles locally, refresh incrementally (only fetch new candles since last sync).

Daily sync job pulls previous day's data for entire universe. On-demand deep fetch pulls granular data for shortlisted stocks only.

### Multi-Timeframe Data Per Tier

| Tier | Timeframe | History | Stocks | Purpose |
|------|-----------|---------|--------|---------|
| Tier 1 Screen | Daily | 1 year | All ~1500 | Trend, RS, volume patterns, sector strength |
| Tier 1 Screen | 15-min | 2 months | All ~1500 | Intraday volatility profile, ATR |
| Tier 2 Deep | 5-min | 1 month | ~50-100 shortlisted | Entry precision, volume profile, VWAP |
| Tier 3 Setup | 1-min | 5 days | ~10-15 final | Exact entry/exit levels, order flow read |

### Live Data (During Market Hours)

Kite WebSocket for real-time ticks on shortlisted stocks. Pre-market: auction data, gap calculation. Replaces current NSE scraper entirely — Kite is the authoritative source.

### Margin & Capital (Live from Kite)

`kite.margins()` for actual available margin. Per-stock margin requirement via instrument data. Position sizing uses real margin, not config-hardcoded capital.

### Data Models

```python
InstrumentCache:
    token: int
    symbol: str
    exchange: str
    lot_size: int
    tick_size: float
    last_synced: datetime

CandleStore:
    symbol: str
    interval: str          # "day", "15minute", "5minute", "minute"
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

MarketSnapshot:
    nifty: float
    banknifty: float
    vix: float
    advance_decline_ratio: float
    sector_indices: dict   # sector_name → value + change_pct
```

### Sync Schedule

- **6:00 AM:** Refresh instrument list, sync previous day's daily candles for all stocks
- **8:45 AM (pre-market):** Fetch pre-open auction data
- **On-demand:** Deep fetch when Tier 1 shortlists stocks (5-min and 1-min candles)

---

## Section 2: Tier 1 — Deterministic Screening Engine

No LLM. Pure math. Scans all ~1500 stocks, outputs ~50-100 candidates.

### Phase 1A: Liquidity & Tradability Filter

Eliminates ~40% of universe:

- Average daily volume ≥ 5L (last 20 days)
- Price ₹50-5000 (practical for 4L capital + margin)
- Market cap ≥ 1000 Cr
- Bid-ask spread < 0.1% (from recent tick data)
- Must have traded every day last 10 sessions (no illiquid gaps)

### Phase 1B: Multi-Factor Scoring

Each stock scored 0-100 across weighted factors:

| Factor | Weight | What It Measures |
|--------|--------|------------------|
| Volume Surge | 15% | Today's volume vs 20-day avg. Institutional activity signal |
| Relative Strength (vs Nifty) | 15% | Outperformance over 5/20/60 days. Leaders and laggards |
| ATR Expansion | 10% | Volatility expanding = opportunity. Contracting = skip |
| Price Structure | 15% | Near support/resistance, 52w high/low, key moving averages |
| Delivery % Trend | 10% | Rising delivery % = conviction buying (from bhavcopy) |
| Sector Momentum | 10% | Sector index RS rank. Trade stocks in moving sectors |
| Gap Analysis | 10% | Pre-market gap size + historical gap behavior (fill vs go) |
| Candlestick Patterns | 10% | Multi-day patterns: inside bar, narrow range, engulfing |
| Volume Profile | 5% | POC location, value area width, naked POCs from recent sessions |

### Phase 1C: Correlation Filter

- If 5 bank stocks all pass, pick strongest 1-2 only
- Max 2-3 stocks per sector in shortlist
- Avoids correlated risk concentration (critical with 4L capital)

### Phase 1D: Pre-Market Enrichment (9:00 AM)

- Gap % from previous close (auction price)
- Pre-open volume vs average
- Adjust scores: big gap + volume = boost; gap against trend = penalize

### Output

Ranked list of ~50-100 stocks with composite scores, factor breakdown, sector tags. All passing stocks get full indicator computation:

- RSI (14), MACD (12,26,9), Bollinger Bands (20,2)
- SMA/EMA (9, 20, 50, 200 on daily)
- VWAP + standard deviation bands (from 15-min data)
- Pivot Points (Standard + Camarilla)
- Support/Resistance (swing high/low detection)
- ADX (trend strength)
- Supertrend (trailing stop reference)

---

## Section 3: Tier 2 — LLM Market & Sector Analysis

Three focused LLM calls. Each does one job well.

### Call 1: Market Regime Analysis

**Input:** Nifty, Bank Nifty, VIX levels + 5-day trend, advance/decline ratio, FII/DII flows (last 5 days), sector index heatmap, global cues (SGX Nifty, US futures from previous close).

**Output (structured JSON):**

```json
{
  "regime": "trending_up | trending_down | range_bound | volatile | low_vol_squeeze",
  "regime_confidence": 0.82,
  "bias": "bullish | bearish | neutral",
  "key_levels": {
    "nifty_support": 19200,
    "nifty_resistance": 19650,
    "banknifty_support": 44800,
    "banknifty_resistance": 45600
  },
  "sectors_in_play": ["banking", "IT", "auto"],
  "sectors_to_avoid": ["pharma", "realty"],
  "risk_appetite": "aggressive | moderate | defensive",
  "session_expectation": "Expiry day, expect range-bound first half, breakout post 1:30 PM"
}
```

### Call 2: Sector Deep-Dive

**Input:** Market regime from Call 1 + sector index data (Nifty IT, Bank, Pharma, Auto, Metal, Energy, FMCG, Realty) + top 3-5 stocks per in-play sector with Tier 1 scores and factor breakdown.

**Output (structured JSON):**

```json
{
  "sectors": [
    {
      "name": "banking",
      "theme": "credit growth data strong, rate cut expectations",
      "intraday_bias": "bullish",
      "catalyst": "RBI policy next week positioning"
    }
  ],
  "sector_pairs": ["banking + NBFC moving together"],
  "sector_divergences": ["IT decoupling from broader market — rupee weakness"],
  "cross_sector_picks": ["BAJFINANCE — benefits from banking + NBFC tailwind"]
}
```

### Call 3: Candidate Shortlisting

**Input:** Market regime + sector analysis + full Tier 1 scored list (~50-100 stocks) with composite scores, factor breakdown, key indicator values, recent price structure.

**Output (structured JSON):**

```json
{
  "shortlist": [
    {
      "symbol": "RELIANCE",
      "direction": "long",
      "conviction": "high",
      "primary_strategy": "vwap_mean_reversion",
      "reasoning": "3-day pullback to VWAP support with sector turning bullish, delivery % rising",
      "key_levels": {"support": 2480, "resistance": 2540, "vwap": 2505},
      "risk_flag": "earnings in 5 days — may limit upside"
    }
  ],
  "avoid_list": [
    {"symbol": "TATAMOTORS", "reason": "looks strong but heavy OI buildup at 650 CE, capped"}
  ],
  "max_positions_today": 3
}
```

### Prompt Engineering Principles (All Calls)

1. **Role anchoring:** "You are a senior proprietary trader at a top Indian brokerage with 15 years NSE intraday experience managing institutional capital."
2. **Chain-of-thought mandate:** "Think step by step. Show your reasoning before conclusions."
3. **Anti-hallucination:** "Use ONLY the data provided. Do NOT invent price levels, volumes, or news. If data is insufficient, say so."
4. **Structured output:** Force function/tool calling with strict JSON schema. No free-text parsing.
5. **Calibrated confidence:** "Confidence 0.8+ means you'd bet your own capital. 0.6-0.8 means worth watching. Below 0.6 means skip."
6. **Counter-reasoning:** "For each pick, state the strongest bear case (for longs) or bull case (for shorts)."
7. **Provider-agnostic:** All prompts use standard system/user message format. Tool/function calling schemas work across OpenAI, Anthropic, and Groq APIs.

---

## Section 4: Tier 3 — Deep Per-Stock Analysis & Setup Validation

### Phase 3A: Per-Stock Deep Analysis (1 LLM Call Per Stock)

Before each call, fetch deep data from Kite: 5-min candles (1 month) for volume profile, 1-min candles (5 days) for microstructure. Compute: Volume Profile (POC, VAH, VAL), VWAP bands (±1σ, ±2σ), Camarilla pivots, ADX/DI+/DI-, Supertrend.

**Input per stock:** All multi-timeframe indicators, Tier 1 factor scores, Tier 2 reasoning, backtest results for all applicable strategies, 5-day price action narrative.

**Output (structured JSON):**

```json
{
  "symbol": "RELIANCE",
  "setups": [
    {
      "strategy": "vwap_mean_reversion",
      "direction": "long",
      "entry_trigger": "price touches VWAP -1σ (2485) with RSI < 35 and volume spike",
      "entry_price": 2485.0,
      "stop_loss": 2468.0,
      "target_1": 2510.0,
      "target_2": 2530.0,
      "position_size_hint": "1x",
      "entry_window": "09:30-11:00",
      "exit_deadline": "15:00",
      "confidence": 0.82,
      "edge_description": "3-day selling exhaustion at VWAP -1σ with sector turning bullish",
      "invalidation": "if price closes 5-min candle below 2460, setup is dead",
      "bear_case": "broader market weakness could drag even strong setups",
      "confluence_count": 4,
      "timeframe_alignment": ["daily: uptrend", "hourly: pullback", "15min: at support"]
    }
  ],
  "no_trade_reason": null
}
```

**Key prompt additions:**

- **Confluence requirement:** "Only propose setups with 3+ independent confirming signals across different timeframes or indicator types."
- **R:R floor:** "Minimum reward:risk of 1.5:1 to target_1. If you can't find that, return no_trade_reason."
- **Level precision:** "Entry, stop, targets must align with actual support/resistance, pivot, or VWAP levels from the data. Do NOT round to convenient numbers."

### Phase 3B: Adversarial Validation (1 LLM Call)

Takes ALL proposed setups and stress-tests as a portfolio.

**Input:** All setups + market regime + sector analysis + correlation data between shortlisted stocks.

**Output (structured JSON):**

```json
{
  "approved": [
    {"symbol": "RELIANCE", "setup_index": 0, "approval": "strong", "adjustment": null},
    {"symbol": "HDFCBANK", "setup_index": 0, "approval": "conditional",
     "adjustment": "reduce size to 0.5x — correlated with ICICIBANK setup"}
  ],
  "rejected": [
    {"symbol": "TATAMOTORS", "setup_index": 0,
     "reason": "stop loss too tight for current ATR, will get stopped out on noise"}
  ],
  "portfolio_risk_assessment": {
    "total_setups": 8,
    "approved": 5,
    "max_correlated_exposure": "28% in banking — acceptable",
    "regime_alignment": "4/5 setups align with bullish regime",
    "worst_case_loss": "₹8,400 (2.1% of capital) if all stops hit simultaneously",
    "recommendation": "execute top 3 by confidence, keep 2 on watchlist"
  }
}
```

**Adversarial prompt:** "You are the risk manager reviewing a junior trader's book. Your job is to find reasons NOT to trade. You get penalized for approving trades that lose, not for rejecting winners. Check correlation, total risk, regime contradictions. No sunk cost — reject freely."

---

## Section 5: Strategy Framework

10 strategies. LLM selects which applies — execution rules are deterministic.

### Strategy 1: Opening Range Breakout (ORB)
- Range: first 15 or 30 min high/low
- Entry: break above/below with volume > 1.5x avg
- Stop: opposite end of range
- Target: 1.5x range width, then trail
- Best in: trending regime, gap days

### Strategy 2: VWAP Mean Reversion
- Entry: price at VWAP ±1σ, RSI diverging, volume declining
- Stop: beyond ±2σ band
- Target: VWAP (conservative), opposite σ band (aggressive)
- Best in: range-bound regime

### Strategy 3: Momentum / Trend Following
- Entry: ADX > 25, price above 9/20 EMA, MACD expanding, volume confirming
- Stop: below 20 EMA or Supertrend
- Target: trail with Supertrend or 9 EMA
- Best in: trending regime

### Strategy 4: Gap & Go
- Entry: gap > 1% on volume > 2x avg, first pullback holds gap level
- Stop: below gap fill level
- Target: measured move (gap size projected)
- Variant — Gap Fill: weak gap, fade it
- Best in: volatile regime, event days

### Strategy 5: Pivot Point Bounce/Break
- Entry: reaction at Standard/Camarilla pivot levels
- Stop: beyond next pivot level
- Target: next pivot in trade direction
- Best in: range-bound or early-trend

### Strategy 6: Relative Strength Pairs
- Entry: strongest stock in strongest sector when sector confirms
- Stop: if stock loses relative strength vs sector
- Target: sector-level target mapped to stock beta
- Best in: sector rotation days, policy events

### Strategy 7: Bollinger Squeeze → Expansion
- Setup: bandwidth at 20-day low
- Entry: first close outside bands with volume surge
- Stop: middle band (20 SMA)
- Target: 2x band width projected
- Best in: low-vol transitioning to trending

### Strategy 8: Supply/Demand Zone Trading
- Entry: price returns to institutional zone, shows rejection
- Stop: beyond the zone
- Target: origin of last move from zone
- Best in: all regimes

### Strategy 9: Volume Profile / POC
- Entry: price at naked POC or VAH/VAL boundary
- Stop: beyond value area
- Target: POC from VA edge, or VA edge from POC
- Best in: range-bound, consolidation

### Strategy 10: Multi-Timeframe Confluence (Meta-Strategy)
- Not standalone — boosts confidence when 3+ timeframes agree
- Daily: trend direction (above/below 50 SMA)
- Hourly: momentum (MACD/RSI alignment)
- 15-min: entry pattern (any of strategies 1-9)
- Minimum confluence of 3 to qualify for high-conviction

### Strategy Selection Logic

```
For each shortlisted stock:
  1. Check regime → filter strategies (no mean reversion in strong trend, etc.)
  2. Check indicators → which strategy conditions are mechanically met
  3. Run backtest for applicable strategies
  4. Pass candidates + backtest evidence to Tier 3 LLM
  5. LLM selects best strategy and designs precise setup
```

Each strategy implements `is_applicable(snapshot, regime) → bool` — mechanical check before LLM analysis.

---

## Section 6: Backtesting Engine

### Walk-Forward Testing

- Split history: 70% training, 30% out-of-sample
- Optimize parameters on training, validate on OOS
- Roll forward: 10 windows across 1 year of daily data
- OOS failure → overfitting, discard strategy for this stock

### Per-Strategy Backtest Output

```json
{
  "strategy": "vwap_mean_reversion",
  "symbol": "RELIANCE",
  "period": "2025-09-27 to 2026-09-27",
  "total_trades": 47,
  "winners": 29,
  "losers": 18,
  "win_rate": 0.617,
  "avg_winner": 4850,
  "avg_loser": -2890,
  "profit_factor": 2.70,
  "expectancy": 1740,
  "expectancy_r": 0.62,
  "sharpe_ratio": 1.85,
  "max_drawdown_pct": 4.2,
  "max_consecutive_losses": 4,
  "avg_hold_time_min": 47,
  "oos_degradation": 0.12,
  "calmar_ratio": 2.1,
  "trade_distribution": {
    "by_hour": {"09": 12, "10": 15, "11": 8, "12": 5, "13": 4, "14": 3},
    "by_weekday": {"mon": 8, "tue": 11, "wed": 10, "thu": 12, "fri": 6}
  }
}
```

### Transaction Cost Modeling (Zerodha)

Every backtest trade deducts actual costs:

- Brokerage: ₹20/order or 0.03% (whichever lower), both legs
- STT: 0.025% on sell side (intraday)
- Exchange charges: 0.00345%
- GST: 18% on brokerage + exchange charges
- SEBI turnover fee: 0.0001%
- Stamp duty: 0.003% on buy side
- Slippage model: 0.02% per leg (conservative for liquid stocks)
- Total round-trip: ~0.08-0.12% per trade

### Monte Carlo Simulation

- Take backtest trade sequence, randomly reshuffle order 10,000 times
- Per shuffle: compute equity curve, max drawdown, final P&L
- Output: probability distribution of outcomes

```json
{
  "monte_carlo": {
    "simulations": 10000,
    "median_return_pct": 18.4,
    "p10_return_pct": 6.2,
    "p90_return_pct": 34.1,
    "median_max_drawdown": 5.8,
    "p95_max_drawdown": 12.4,
    "risk_of_ruin_pct": 0.3,
    "confidence_score": 0.78
  }
}
```

### Quality Gates (Must Pass)

| Metric | Minimum | Why |
|--------|---------|-----|
| Total trades | ≥ 30 | Statistical significance |
| Win rate | ≥ 45% | Below this, need very high R:R |
| Profit factor | ≥ 1.5 | Gross wins must be 1.5x gross losses |
| Expectancy (R) | ≥ 0.3R | Must make 0.3x risk per trade avg |
| OOS degradation | ≤ 0.3 | Not overfit |
| Monte Carlo P10 | > 0% | 90% of random orderings still profitable |
| Risk of ruin | < 5% | Survivability |
| Max consecutive losses | ≤ 8 | Psychological + capital survival |

Strategy-stock combo failing any gate → rejected, regardless of LLM confidence.

### Regime-Conditional Backtesting

Tag each historical day with regime. Report metrics per regime, not just overall. Tier 3 LLM sees regime-specific performance and picks strategy matching today's regime.

---

## Section 7: Persistence & Multi-Run Accumulation

### Analysis Run Model

```python
AnalysisRun:
    run_id: str                    # "run_20260927_093015_abc123"
    timestamp: datetime
    market_regime: MarketRegime
    regime_confidence: float
    sector_analysis: dict
    total_stocks_scanned: int
    tier1_passed: int
    tier2_shortlisted: int
    setups_proposed: int
    setups_approved: int
    llm_calls: int
    llm_cost_usd: float
    duration_seconds: float
```

### Setup Lifecycle

```
proposed → approved/rejected → active → filled/expired → closed
```

Every setup persisted with full lineage — which run produced it, what data it saw, what the LLM said.

### Multi-Run Accumulation Rules

1. **No replacement.** New run creates new setups alongside existing ones. Previous approved setups remain valid until exit_deadline or market close.

2. **Upsert logic for same stock:** Both setups kept. System flags higher-confidence alternative. Conflicting directions flagged as contradiction — recommend neither until resolved.

3. **Cross-run ranking:**

```python
SetupRanking:
    symbol: str
    direction: Direction
    best_setup: Setup              # highest confidence across runs
    all_setups: list[Setup]        # chronological
    consistency: float             # how many runs agree (0-1)
    improving: bool                # confidence trending up
    recommendation: str            # "execute" | "watch" | "conflicting" | "stale"
```

4. **Staleness detection:** Setup older than 2h in volatile regime → stale. Older than 4h in range-bound → stale. Price drift > 1% from entry → "price moved, re-evaluate."

5. **Execution suggestions via DailyPlan:**

```python
DailyPlan:
    date: date
    runs: list[AnalysisRun]
    active_setups: list[Setup]
    ranked_suggestions: list[RankedSuggestion]   # by confidence, consistency, regime alignment
    portfolio_summary: PortfolioSummary           # capital, risk, sector exposure
```

### Storage

- SQLite `analysis_runs` table — one row per run with metadata
- SQLite `setups` table — foreign key to run_id, status tracked
- SQLite `setup_rankings` view — cross-run aggregation
- JSON export of DailyPlan for UI consumption
- Archive after 7 days

### API Surface

- `GET /api/plans/today` → DailyPlan with ranked suggestions
- `GET /api/plans/runs` → all runs today with metadata
- `GET /api/plans/setups?symbol=RELIANCE` → all setups across runs
- `POST /api/analyze` → trigger new run, returns run_id
- `GET /api/plans/runs/{run_id}` → specific run details
- `PATCH /api/setups/{setup_id}` → manually approve/reject/override

---

## Section 8: Kite Execution Integration

### Authentication

Kite OAuth2: user logs in via browser → `request_token` → exchange for `access_token` (valid one trading day). Token stored in memory only (never disk). Daily re-auth required. `POST /api/auth/kite` triggers the flow.

### Order Management

```python
KiteExecutor:
    place_entry(setup) → order_id
        # LIMIT or SL order, MIS product, DAY validity
        # Skip if price drifted > price_drift_pct from LTP

    place_exit(position, reason) → order_id
        # SL order immediately after fill
        # LIMIT for targets, MARKET for emergency/time exits

    modify_order(order_id, new_price) → bool
        # Trailing stop, target adjustment

    cancel_order(order_id) → bool
        # Entry window expired, setup invalidated
```

### Position Monitoring (WebSocket)

```python
PositionMonitor:
    on_tick(symbol, ltp, volume):
        # Real-time P&L update
        # SL/target/invalidation/time checks
        # Events emitted to frontend WebSocket

    partial_profit_booking:
        # target_1: exit 50%, move SL to breakeven
        # target_2: exit remaining 50%
        # Configurable: 50/50 or 40/30/30

    trailing_stop:
        # After target_1: trail SL using Supertrend or ATR/4
        # Modify Kite SL order on each new high/low
```

### Capital Manager

```python
CapitalManager:
    get_available_capital()      # kite.margins() - deployed
    check_margin_for_setup()     # verify margin before order
    daily_pnl()                  # kite.positions() aggregate
```

### Safety Mechanisms

| Mechanism | What It Does |
|-----------|-------------|
| Daily loss limit | Loss > 2% of capital (₹8000) → stop all, square off |
| Per-trade risk cap | Max 1% (₹4000) per trade |
| Max positions | 3-4 simultaneous |
| Square-off deadline | 15:10 (before 15:15 NSE cutoff) |
| Emergency stop | UI button → cancel all + market-sell all |
| Order validation | Price within day range, qty within limits |
| Stale token | 403 from Kite → halt, alert user |
| Network failure | WebSocket disconnect > 30s → protective SL at widened levels |

### Execution Modes

```toml
[execution]
mode = "paper"    # paper | live | shadow

# paper: simulate with Kite LTP, no real orders
# live: real orders with all safety checks
# shadow: real orders at 1/10th qty for validation
```

Shadow mode trades with ₹40K (10% of capital). Proves execution works (slippage, fills, latency) at reduced risk. Graduate to live after 30 profitable shadow sessions.

---

## LLM Cost Estimate

Per analysis run (~15-20 calls):
- 3 Tier 2 calls: ~$0.03
- 10-15 Tier 3 per-stock calls: ~$0.10-0.15
- 1 adversarial validation: ~$0.02
- **Total: ~$0.15-0.20/run**
- Daily (2-3 runs): ~$0.30-0.60
- Monthly: ~$8-15

Negligible relative to 4L capital. One good trade pays for a year of LLM costs.

## Migration from Current System

- Replace `DataFetcher` + `NSE_UNIVERSE` → `KiteDataManager` + `InstrumentCache`
- Replace `Scanner` → `Tier1Screener` + `Tier2Analyzer`
- Replace `PlanGenerator` → `Tier3Analyzer` + `AdversarialValidator`
- Replace `Backtester` → `BacktestEngine` (walk-forward + Monte Carlo)
- Replace `PlanStore` (single JSON) → `AnalysisRunStore` (SQLite multi-run)
- Replace `Executor` → `KiteExecutor` + `PositionMonitor` + `CapitalManager`
- Keep: `RiskManager` (enhance), `indicators.py` (extend), WebSocket event system, frontend pages
