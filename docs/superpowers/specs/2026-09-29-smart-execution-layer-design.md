# Smart Execution Layer Design

**Date:** 2026-09-29
**Status:** Approved
**Branch:** master

## Problem

The current execution layer is a price-alert loop: every 5 seconds it polls LTP via REST, compares against static price levels, and places/cancels orders. It has zero awareness of how price is behaving — no candle data, no momentum sensing, no volume context, no adaptive behavior.

This means:
- Entries fire regardless of adverse momentum (buying into a selloff)
- Stops are static — no trailing based on price structure
- Profitable moves get given back because exits wait for fixed targets or hard stops
- No veto mechanism for obviously bad conditions (volume dried up, sector dumping)
- WebSocket streaming capability exists (`LiveTickManager`) but is completely unused

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Intelligence level | Execution with veto power | Plan recommends, executor has final say. Can skip setups, tighten targets, but doesn't modify entry prices or re-enter after stops. |
| Candle timeframes | 1min + 5min | 1min for precise timing, 5min for noise filtering. 15min context already baked into plan from analysis phase. |
| Decision engine | Algorithmic + LLM escalation | Hard rules handle 80%+ of cases instantly. Claude fires on genuinely ambiguous gray-zone situations (1-3 per session). Falls back to algorithmic if API down. |
| Intelligence as default | Always-on | No `None` fallback. Smart execution is the only code path. Degradation is internal (REST fallback if WebSocket dies), not a separate mode. |

## Architecture

```
KiteTicker (WebSocket)
    │
    ▼
LiveTickManager (existing, wired up)
    │
    ▼
CandleAggregator (NEW)
    ├── 1min candle builder per symbol
    └── 5min candle builder per symbol
    │
    ▼
ExecutionIntelligence (NEW — facade)
    ├── EntryGuard — veto/approve/wait entries based on live conditions
    ├── AdaptiveExitManager — replaces static ExitManager
    ├── MomentumScorer — real-time scores from candle data
    └── LLMEscalator — Claude for ambiguous cases
    │
    ▼
Executor (modified)
    ├── Candle-driven loop: decisions on 1min/5min close events
    └── Heartbeat loop (5s): hard stop enforcement, order polling
```

**Key principle:** Executor owns order lifecycle. ExecutionIntelligence produces signals and verdicts. Clean separation — intelligence never touches orders directly.

## Component Specifications

### 1. CandleAggregator

Builds live OHLCV candles from raw tick stream.

```python
class CandleAggregator:
    def on_tick(self, symbol, price, volume, timestamp):
        # Update current 1min candle OHLCV
        # If 1min boundary crossed → close candle, notify, start new
        # Every 5th 1min close → also close 5min candle, notify

    def get_candles(self, symbol, timeframe) -> list[LiveCandle]:
        # Return completed candles (up to 50)

    def get_current(self, symbol, timeframe) -> LiveCandle:
        # Return in-progress candle

    def last_price(self, symbol) -> float:
        # Latest tick price (replaces REST get_ltp calls)
```

**Data model:**

```python
@dataclass(frozen=True)
class LiveCandle:
    symbol: str
    timeframe: str        # "1min" | "5min"
    timestamp: datetime   # candle open time
    open: float
    high: float
    low: float
    close: float
    volume: int
    is_complete: bool     # False for current in-progress candle
```

**Design details:**
- Wall-clock aligned boundaries. 1min candle for 09:15 covers 09:15:00–09:15:59. 5min for 09:15 covers 09:15:00–09:19:59. Matches exchange convention.
- History depth: 50 candles per timeframe per symbol (~50min of 1min, ~4hrs of 5min). Enough for any intra-session indicator without unbounded memory.
- Callback system: `on_1min_close(symbol, candle)`, `on_5min_close(symbol, candle)`. ExecutionIntelligence subscribes. Primary trigger for re-evaluation.
- Pre-market seeding: On startup, fetch last 50 candles from `KiteClient.get_candles()` (historical API) so indicators have warm-up data.
- Missing ticks: If no tick during a 1min window, close empty candle (O=H=L=C=last_price, V=0). Prevents stale state.
- Thread safety: Ticks arrive on KiteTicker daemon thread. Lock per symbol. Callbacks must be fast (update state only, no I/O).

### 2. MomentumScorer

Computes per-symbol signal scores from live candles. Single source of truth for "what is price doing right now."

```python
class MomentumScorer:
    def update(self, symbol, candles_1m, candles_5m) -> SymbolState
    def get_state(self, symbol) -> SymbolState

@dataclass(frozen=True)
class SymbolState:
    symbol: str
    timestamp: datetime

    # Core scores (-100 to +100, negative=bearish, positive=bullish)
    momentum_1m: float
    momentum_5m: float

    # Volume context
    volume_ratio: float     # Current vs avg volume (1.0 = normal)
    volume_trend: str       # "rising" | "falling" | "stable"

    # Price structure
    vwap: float
    vwap_position: float    # Price relative to VWAP (-1 to +1)
    price_vs_open: float    # % change from day open

    # Candle character
    last_pattern_1m: str    # "bullish_engulf" | "bearish_pin" | "doji" | "none"
    last_pattern_5m: str
    body_dominance: float   # Avg body/range ratio last 5 candles (0-1)

    # Derived
    trend_alignment: bool   # 1m and 5m momentum same direction
    strength: str           # "strong" | "moderate" | "weak" | "conflicting"
```

**Scoring logic:**

| Signal | Computation |
|---|---|
| `momentum_Xm` | Weighted sum: candle direction, body size, close position in range. Last candle 3x weight. Range -100 to +100. |
| `volume_ratio` | Current candle volume / SMA(20) volume |
| `vwap` | Cumulative (price × volume) / cumulative volume from day start |
| `vwap_position` | (price - vwap) / ATR, clamped [-1, +1] |
| `last_pattern_Xm` | Reuse existing candlestick pattern engine (8 patterns) on live candles |
| `body_dominance` | avg(abs(close-open) / (high-low)) over last 5 candles |
| `trend_alignment` | sign(momentum_1m) == sign(momentum_5m) |

**Update cadence:** Full recompute on every 1min close. VWAP updates on every tick. 5min scores change only on 5min close.

### 3. EntryGuard

Decides whether to place, hold, or veto a planned entry.

```python
class EntryGuard:
    def evaluate(self, leg: TradeLeg, state: SymbolState) -> EntryVerdict

@dataclass(frozen=True)
class EntryVerdict:
    action: str          # "ENTER" | "WAIT" | "VETO"
    reason: str
    confidence: float    # 0-1, below 0.4 triggers LLM escalation
    reassess_after: int  # Seconds until next check
```

**Decision rules (priority order, first match wins):**

| # | Condition | Verdict |
|---|---|---|
| 1 | Entry window expired | VETO |
| 2 | Price drifted > `max_entry_price_drift_pct` | VETO |
| 3 | LONG + `momentum_5m < -60` | VETO — strong selling |
| 4 | SHORT + `momentum_5m > +60` | VETO — strong buying |
| 5 | `volume_ratio < 0.3` | WAIT — no liquidity |
| 6 | No trend alignment + `body_dominance < 0.3` | WAIT — choppy |
| 7 | LONG + `vwap_position < -0.8` + `momentum_1m < -30` | WAIT — falling below VWAP |
| 8 | Bearish pattern on 5min for LONG (inverse for SHORT) | WAIT |
| 9 | Gray zone (no clear signal) | ENTER with confidence < 0.4 → LLM escalation |
| 10 | Momentum aligned + volume decent | ENTER with confidence > 0.7 |

**WAIT lifecycle:**
- Re-evaluate on every 1min candle close
- Max wait = `leg.max_entry_wait` (existing field)
- Wait expired → auto-VETO
- Conditions clear → ENTER

**Entry price on delayed entry:**
- If price moved favorably (pullback for LONG), use current price
- If price moved adversely but within drift tolerance, use plan's limit price
- Preserves R:R ratio

### 4. AdaptiveExitManager

Replaces static ExitManager. Same interface, candle-aware logic.

```python
class AdaptiveExitManager:
    def decide(self, state: LegState, symbol_state: SymbolState,
               price: float, now: datetime) -> ExitDecision

class ExitDecision(Enum):
    HOLD = "hold"
    BOOK_TARGET_1 = "book_target_1"
    BOOK_TARGET_2 = "book_target_2"
    STOP_HIT = "stop_hit"
    SQUARE_OFF = "square_off"
    TRAIL_STOP = "trail_stop"
    MOMENTUM_EXIT = "momentum_exit"
    PATTERN_EXIT = "pattern_exit"
```

**Exit priority order:**

| Priority | Rule |
|---|---|
| 1 | Square-off time — hard exit, never overridden |
| 2 | Stop loss hit — price ≤ stop (LONG) or ≥ stop (SHORT) |
| 3 | Target 2 hit — book remaining position |
| 4 | Momentum reversal exit — momentum collapsed while profitable |
| 5 | Pattern exit — bearish engulfing on 5min + volume > 1.5x (LONG) |
| 6 | Target 1 hit — book partial (50%) |
| 7 | Trailing stop — ratchet based on candle structure |
| 8 | Hold — default |

**Three-phase trailing stop:**

| Phase | Trigger | Trail logic |
|---|---|---|
| Pre-target-1 | Position open, T1 not hit | Stop stays at plan's stop_loss. No trail. |
| Phase 2 | T1 booked, riding to T2 | Trail to lowest low of last 3 candles (5min, LONG). Never widen. Floor = breakeven. |
| Phase 3 | Price within 0.3% of T2 | Tighten to last 2 candles (1min). Aggressive profit lock. |

**Momentum reversal exit (all conditions required for LONG, inverse for SHORT):**
- Position is profitable (price > entry)
- `momentum_5m` was > +40 at some point since entry
- `momentum_5m` now < -20
- `momentum_1m` < -40
- `volume_ratio` > 1.0

Fires while profitable — captures "the move is over" before trailing stop gets hit.

**Invariants:**
- Square-off time is sacred — never overridden
- Stop loss only tightens, never widens
- Target booking percentages unchanged (50% at T1)
- All P&L recording and database writes unchanged

### 5. LLMEscalator

Handles ambiguous cases where scores land in gray zone.

```python
class LLMEscalator:
    async def evaluate_entry(self, leg, state, candles_1m, candles_5m) -> EscalationResult
    async def evaluate_exit(self, leg_state, state, candles_1m, candles_5m) -> EscalationResult

@dataclass(frozen=True)
class EscalationResult:
    action: str           # "ENTER" | "WAIT" | "VETO" | "EXIT" | "HOLD"
    reasoning: str
    confidence: float
    fallback_used: bool   # True if API failed
```

**Triggers:**

| Source | Trigger |
|---|---|
| EntryGuard | `confidence < 0.4` |
| AdaptiveExitManager | Borderline momentum reversal |
| AdaptiveExitManager | Conflicting signals (pattern vs momentum) |

**Prompt structure:**

```
You are an execution intelligence for an intraday trading system.
Make a decision based on live market data. Be decisive — ENTER/WAIT/VETO
or EXIT/HOLD. No hedging.

TRADE CONTEXT:
  Symbol, Direction, Plan entry/stop/targets, Strategy, Plan reasoning

LIVE CONDITIONS:
  Current price, VWAP, Momentum 1m/5m, Volume ratio/trend
  Last 10 candles (1min), Last 5 candles (5min)

QUESTION: {specific question from escalation trigger}

Respond JSON: {"action": "...", "confidence": 0.0-1.0, "reasoning": "one sentence"}
```

**Guardrails:**
- 10s timeout → fallback to conservative algorithmic default (WAIT for entries, HOLD for exits)
- API failure → same fallback, `fallback_used = True`
- Max 5 escalations per session (prevents runaway costs)
- Hard rules (square-off, hard stop, target hit) never escalate
- Structured JSON output, strict parsing, malformed → fallback
- Cost: ~500 tokens/call, ~3 calls/session ≈ $0.01/day

**Logging:** Every escalation persisted with timestamp, symbol, question, candle snapshot, Claude response, final action, and post-trade outcome.

### 6. ExecutionIntelligence Facade

Single entry point bundling all smart components.

```python
class ExecutionIntelligence:
    def __init__(self, ticker: LiveTickManager, config: ExecutionConfig):
        self.aggregator = CandleAggregator()
        self.scorer = MomentumScorer()
        self.entry_guard = EntryGuard(self.scorer)
        self.adaptive_exit = AdaptiveExitManager(self.scorer)
        self.escalator = LLMEscalator()
        self.ticker_health = TickerHealth()

    def start(self, symbols: list[str]):
        # Subscribe to tick stream, seed candles, wire callbacks

    def stop(self):
        # Unsubscribe, cleanup
```

### 7. Executor Modifications

**Dual loop design:**

| Loop | Trigger | Responsibility |
|---|---|---|
| Candle-driven | 1min/5min close events | Smart decisions: entry guard, momentum exit, trail stop, pattern exit |
| Heartbeat (5s) | Timer | Safety: hard stop enforcement, square-off, order status polling |

**New entry flow:**
```
For each leg:
  verdict = entry_guard.evaluate(leg, state)
  ENTER  → submit_entry(leg)
  VETO   → mark skipped(reason), log
  WAIT   → queue, re-evaluate on next candle close
  confidence < 0.4 → await llm_escalator.evaluate_entry()
```

**LTP source change:**
- Current: `broker.get_ltp(symbol)` → REST API call
- New: `aggregator.last_price(symbol)` → in-memory from tick stream (zero latency)
- REST `get_ltp()` used only during WebSocket degradation

**Constructor change:**
```python
# intelligence is always provided, no Optional
def __init__(self, broker, plan, risk_manager, database, config,
             intelligence: ExecutionIntelligence):
```

## WebSocket Resilience

Since intelligence is always-on, WebSocket health is critical.

**Disconnect handling:**
1. Auto-reconnect with exponential backoff: 1s, 2s, 4s, 8s, max 30s
2. During gap: CandleAggregator marks candles as "gap", heartbeat switches to REST LTP, entry/exit smart decisions pause
3. On reconnect: re-subscribe, fetch missed candles via historical API, resume
4. Extended outage (>2min): positions managed by hard stops only, status marked "degraded"

**What never stops regardless of WebSocket state:**
- Hard stop loss enforcement (REST fallback)
- Square-off time exit
- Daily loss limit kill switch
- Order status polling

**Health monitoring:**
```python
class TickerHealth:
    last_tick_at: datetime
    reconnect_count: int
    gap_seconds_today: int
    status: str             # "healthy" | "reconnecting" | "degraded"
```

**Pre-market validation:** Verify WebSocket connects and receives at least one tick per symbol within 10s. Invalid instrument token → skip leg, don't block others.

## Frontend Integration

**API extensions to `GET /execute/status`:**
- `ticker_health` object (status, last tick, reconnect count)
- Per-leg: `momentum` scores, `trail_phase`, `last_decision` with reason
- `decision_log`: last 20 decisions with timestamps and reasons
- `escalations`: LLM calls made today with questions and responses

**WebSocket push extensions:**
- Decision events in real-time
- Ticker health changes
- Escalation results

**Trading page UI additions:**
- Connection health indicator (green/yellow/red)
- Per-leg momentum badge (+52↑ / -31↓)
- Decision timeline feed
- Trail stop visual (original dotted vs current solid)
- Veto/wait indicators with reasons
- Escalation badge on LLM-assisted decisions

## Database

New `execution_decisions` table:
```
id, trade_date, timestamp, symbol, decision_type,
reason, momentum_snapshot (JSON), candle_snapshot (JSON),
escalated (bool), llm_response (JSON nullable),
outcome (filled post-trade)
```

## Testing Strategy

**Unit tests:**
- CandleAggregator: tick→candle building, boundary alignment, empty candle, 5min rollup
- MomentumScorer: score computation from known sequences, edge cases
- EntryGuard: each rule fires correctly, priority order, confidence thresholds
- AdaptiveExitManager: each exit type, trail phases, never-widen invariant
- LLMEscalator: prompt construction, JSON parsing, timeout fallback

**Integration tests (VirtualBroker):**
- Clean entry, veto entry, wait→enter, wait→timeout
- Trailing stop phases, momentum exit, pattern exit
- WebSocket disconnect → hard stop enforced via REST
- LLM escalation fires and applies, LLM timeout → fallback

**Replay testing:**
```python
class TickReplayer:
    def __init__(self, tick_file: str):
        # Load recorded tick data
    def replay(self, aggregator: CandleAggregator, speed: float = 1.0):
        # Feed ticks at original or accelerated timestamps
```

Record live session tick data → replay through intelligence → verify decisions. Catches regressions when tuning thresholds.

## Files Modified/Created

**New files:**
- `tradingbot/executor/candle_aggregator.py` — CandleAggregator + LiveCandle
- `tradingbot/executor/momentum_scorer.py` — MomentumScorer + SymbolState
- `tradingbot/executor/entry_guard.py` — EntryGuard + EntryVerdict
- `tradingbot/executor/adaptive_exit_manager.py` — AdaptiveExitManager (replaces exit_manager.py)
- `tradingbot/executor/llm_escalator.py` — LLMEscalator + EscalationResult
- `tradingbot/executor/execution_intelligence.py` — ExecutionIntelligence facade + TickerHealth
- `tradingbot/executor/tick_replayer.py` — TickReplayer for testing
- `tests/executor/test_candle_aggregator.py`
- `tests/executor/test_momentum_scorer.py`
- `tests/executor/test_entry_guard.py`
- `tests/executor/test_adaptive_exit_manager.py`
- `tests/executor/test_llm_escalator.py`
- `tests/executor/test_execution_intelligence.py`

**Modified files:**
- `tradingbot/executor/executor.py` — dual loop, intelligence integration
- `tradingbot/data/kite_ticker.py` — wire into executor startup
- `tradingbot/cli.py` — build ExecutionIntelligence, pass to Executor
- `tradingbot/api/execution_routes.py` — build intelligence, extended status response
- `tradingbot/core/models.py` — LiveCandle, SymbolState, EntryVerdict, EscalationResult dataclasses
- `tradingbot/api/schemas.py` — API response schemas for new fields
- `tradingbot/core/config.py` — no new config flags needed (intelligence is always-on)

**Deprecated:**
- `tradingbot/executor/exit_manager.py` — ExitManager class removed; ExitDecision enum moves to adaptive_exit_manager.py (extended with new variants). Old imports updated.
