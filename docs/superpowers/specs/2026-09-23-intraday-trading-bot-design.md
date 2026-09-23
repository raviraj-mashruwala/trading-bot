# Intraday Trading Bot — Design Specification

## Overview

Automated intraday equity trading system for Indian markets (NSE). CLI-driven Python monolith with three logically separated agents: Market Scanner, Strategy Engine, and Execution Engine. LLM-powered analysis (Claude via Anthropic API) produces adaptive trade plans; a deterministic executor follows them during market hours.

### Goals

- Scan full NSE universe daily, filter to high-conviction intraday candidates
- Apply adaptive strategy selection — LLM picks optimal strategy per stock based on market conditions
- Execute 1-2 trades/day with predefined entry, stop loss, and targets
- Start with paper trading, graduate to live trading on Zerodha via Kite Connect
- Run on local Mac, analysis decoupled from execution (run analysis night before or morning)

### Non-Goals

- High-frequency trading (sub-second execution)
- Options or derivatives trading
- Overnight/swing positions
- Web UI or mobile app (CLI only)
- Multi-broker support (Zerodha only, initially)

## Architecture

```
tradingbot/
├── core/                    # Shared infrastructure
│   ├── config.py            # Settings, API keys, risk params (TOML + env)
│   ├── kite_client.py       # Zerodha Kite API wrapper
│   ├── database.py          # SQLite — trades, plans, history
│   ├── models.py            # Data classes: Stock, TradeSignal, TradePlan, Position
│   ├── risk_manager.py      # Position sizing, max loss checks, exposure limits
│   └── llm/
│       ├── provider.py      # Abstract LLMProvider interface
│       ├── anthropic.py     # Claude via Anthropic direct API (default)
│       └── ollama.py        # Local fallback
│
├── scanner/                 # Agent 1: Market Scanner
│   ├── data_fetcher.py      # Pull NSE stock universe, sector data, indices
│   ├── filters.py           # Liquidity, price range, volatility filters
│   ├── market_context.py    # FII/DII data, global cues, sector heatmap
│   ├── market_analyzer.py   # LLM-powered intelligent stock selection
│   └── scanner.py           # Orchestrates: fetch → filter → LLM analyze → watchlist
│
├── strategy/                # Agent 2: Strategy Engine
│   ├── indicators.py        # Technical indicators (RSI, VWAP, MAs, MACD, BB, ATR, S/R)
│   ├── backtester.py        # Backtest strategies on recent data
│   ├── strategies/          # Strategy library (pluggable)
│   │   ├── base.py          # Abstract strategy interface
│   │   ├── breakout.py      # Breakout/breakdown strategy
│   │   ├── mean_reversion.py # Mean reversion around VWAP/key levels
│   │   ├── vwap_bounce.py   # VWAP-based entries
│   │   ├── momentum.py      # Momentum/trend following
│   │   └── orb.py           # Opening range breakout
│   ├── strategy_selector.py # LLM picks best strategy per stock + market regime
│   └── plan_generator.py    # Produces final TradePlan JSON with entry/SL/target
│
├── executor/                # Agent 3: Execution Engine (NO LLM)
│   ├── order_manager.py     # Place, modify, cancel orders via Kite
│   ├── position_monitor.py  # Track live P&L, SL hits, target hits
│   ├── exit_manager.py      # Time-based exits, trailing SL, square-off
│   └── executor.py          # Main event loop — deterministic, fast
│
├── paper/                   # Paper trading simulator
│   ├── virtual_broker.py    # Simulates order fills using live/historical prices
│   └── paper_executor.py    # Same interface as real executor
│
├── cli.py                   # Entry point: analyze, execute, backtest, status, history
└── trade_plans/             # Persisted JSON trade plans
    └── YYYY-MM-DD.json
```

### Key Design Decisions

1. **Monolith with logical agents** — single process, agents are modules. No inter-process communication overhead. Simplest to build, debug, deploy on local Mac.

2. **LLM where judgment matters, code where math matters** — Claude does market regime analysis and strategy selection. Indicators, backtesting, position sizing, and execution are pure code.

3. **Decoupled analysis and execution** — analysis writes a JSON trade plan to disk. Executor loads and follows it. Can run analysis night before, execute morning of. No timing dependency.

4. **Provider-agnostic LLM interface** — abstract `LLMProvider` base class. Default: Anthropic direct API (Claude Sonnet 5). Swappable to Ollama or others via config.

5. **Paper trading = same code, different broker** — `VirtualBroker` implements same interface as `KiteClient`. Swap via config flag `MODE=paper|live`.

6. **SQLite for everything** — trade logs, plan history, paper trading results. Zero external dependencies. Sufficient for 1-2 trades/day.

## Data Flow

### Analysis Phase (run on demand — night before or morning)

```
Step 1: Market Scanner
  ├── data_fetcher.py pulls NSE stock universe (~1800 stocks)
  ├── filters.py applies deterministic filters:
  │   ├── Avg daily volume > 5L shares
  │   ├── Price range ₹50-5000
  │   ├── Market cap > ₹5000 Cr
  │   ├── No corporate actions next day
  │   ├── Adequate ATR for intraday movement
  │   └── No circuit limit history
  │   → Result: ~80-100 tradeable stocks
  │
  ├── market_context.py gathers:
  │   ├── Nifty/BankNifty trend (5d, 20d MA positions)
  │   ├── FII/DII net buy/sell (previous day, from NSE API)
  │   ├── Global market summary (US close, Asia futures)
  │   └── Sector heatmap (which sectors leading/lagging)
  │
  └── market_analyzer.py sends to Claude:
      Input: 80 filtered stocks with metrics + market context
      Ask: "Pick 10-15 best intraday candidates for tomorrow with reasoning"
      → Result: 10-15 stocks with rationale and suggested strategy type

Step 2: Strategy Engine
  For each shortlisted stock:
  ├── indicators.py computes on 30-60 days of 5min/15min candles:
  │   RSI(14), MACD(12,26,9), Bollinger Bands(20,2), ATR(14),
  │   SMA(20/50/200), EMA(12/26), VWAP, pivot points, S/R levels
  │
  ├── backtester.py runs each strategy in library against recent data
  │   → Per-stock, per-strategy win rate and avg R:R last 30 days
  │
  └── strategy_selector.py sends to Claude:
      Input: stock technicals + backtest results + market regime
      Ask: "Design optimal intraday trade setup — strategy, direction,
            entry, SL, target1, target2, entry window, confidence"
      → Result: structured trade setup JSON

Step 3: Plan Generation
  ├── risk_manager.py validates:
  │   ├── Position size ≤ max per trade
  │   ├── Total exposure ≤ 50% of capital
  │   └── Risk per trade = 1% of capital
  ├── Rank setups by confidence score
  ├── Pick top 1-2 trades
  └── Write trade_plans/YYYY-MM-DD.json
```

### Trade Plan Format

```json
{
  "date": "2026-09-24",
  "generated_at": "2026-09-23T22:30:00+05:30",
  "market_context": {
    "nifty_trend": "bullish",
    "nifty_level": 25400,
    "fii_net": "+2300 Cr",
    "dii_net": "-800 Cr",
    "global_cues": "US flat, Asia positive",
    "vix": 12.5,
    "regime": "trending"
  },
  "capital": 400000,
  "max_risk_per_trade_pct": 0.01,
  "max_daily_loss_pct": 0.02,
  "trades": [
    {
      "stock": "RELIANCE",
      "exchange": "NSE",
      "strategy": "breakout",
      "direction": "long",
      "entry_price": 2855.0,
      "entry_type": "limit",
      "stop_loss": 2830.0,
      "target_1": 2890.0,
      "target_2": 2920.0,
      "quantity": 16,
      "risk_amount": 4000,
      "entry_window_start": "09:30",
      "entry_window_end": "10:30",
      "max_entry_wait": "11:00",
      "exit_before": "15:10",
      "confidence": 0.72,
      "reasoning": "Breaking out of 3-day consolidation above 2850 resistance. RSI 58 with room to run. Volume picking up. Backtest: breakout strategy 62% win rate last 30d on this stock."
    }
  ]
}
```

### Execution Phase (market hours, 9:15-15:30)

```
09:00  Executor starts → loads latest trade plan
       ├── Validates plan isn't stale (< 14 hours old)
       ├── Verifies capital available in Kite account (or virtual)
       ├── Checks stocks aren't halted/suspended
       └── Re-checks current price vs plan entry (skip if moved > 2%)

09:15  Market opens → executor watches prices via WebSocket

09:30  Entry window opens for trade:
       ├── Places limit order at entry price
       ├── Simultaneously places stop loss order
       └── Logs order IDs

       IF filled:
         ├── Confirm SL order active (bracket order or manual SL)
         ├── Monitor position via WebSocket
         ├── On target_1 hit: book 50%, trail SL to entry (breakeven)
         ├── On target_2 hit: book remaining 50%
         └── On SL hit: full exit, log loss

       IF not filled by max_entry_wait:
         └── Cancel order, no trade today

15:10  HARD SQUARE-OFF: exit all open positions at market price
15:15  Log results to database, generate daily report
```

## LLM Integration

### Provider Interface

```python
from abc import ABC, abstractmethod
from typing import Any

class LLMProvider(ABC):
    @abstractmethod
    async def analyze(self, system_prompt: str, user_prompt: str, 
                      response_schema: dict) -> dict:
        """Send prompt, get structured JSON response."""
        ...
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Verify API connectivity."""
        ...
```

### Default: Anthropic Direct API

- Model: `claude-sonnet-5`
- SDK: `anthropic` Python package
- Auth: `ANTHROPIC_API_KEY` in `.env`
- Structured output via tool_use for reliable JSON responses
- Cost: ~₹500/month (~$6) at 2-3 calls/day

### LLM Call 1: Market Scanner Analysis

```
System: You are an expert Indian equity market analyst specializing in 
intraday trading on NSE. You identify stocks with the highest probability 
of significant intraday movement based on technical setups, market context, 
and institutional activity.

User: [market context data] + [80 filtered stocks with metrics table]

Ask: Select 10-15 stocks most suitable for intraday trading tomorrow.
For each stock, provide:
- symbol: NSE trading symbol
- reasoning: why this stock (2-3 sentences)
- suggested_strategy: breakout | mean_reversion | momentum | vwap_bounce | orb
- direction_bias: long | short | neutral
- key_levels: important price levels to watch

Response: structured JSON via tool_use
```

### LLM Call 2: Strategy Selection & Trade Setup

One batched call with all 10-15 shortlisted stocks. Each stock's data is included as a separate section in the prompt. Claude returns a setup for each stock in a single response. This keeps costs at 2 total LLM calls per analysis run.

```
System: You are an expert intraday trading strategist. You design precise 
trade setups with exact entry, stop loss, and target levels based on 
technical analysis, recent backtest performance, and current market regime.
Do NOT guess or fabricate numbers. Use only the data provided.

User: [all shortlisted stocks, each with:]
- 30-day price action summary with key candle patterns
- Current indicator values: RSI, MACD, BB position, ATR, VWAP distance
- Support/resistance levels (computed via DBSCAN clustering)
- Mini-backtest results: win rate per strategy last 30 days
- Market regime: trending | ranging | volatile | low_vol

Ask: For each stock, design the optimal intraday trade setup.
Return per stock: strategy, direction, entry_price, stop_loss, target_1, 
target_2, entry_type (limit/stop), entry_window, confidence (0-1), reasoning

Response: structured JSON array via tool_use
```

### Fallback Behavior

- If Anthropic API is down during analysis → analysis fails, no plan generated, no trading that day
- Executor NEVER calls LLM — if plan exists, it trades; if not, it stays idle
- LLM calls have 60-second timeout with 1 retry
- All prompts and responses logged to `logs/llm/` for debugging and audit

## Risk Management

### Layer 1: Analysis-Time (Strategy Module)

| Rule | Value | Rationale |
|------|-------|-----------|
| Max risk per trade | 1% of capital (₹4,000 on ₹4L) | Standard risk management |
| Position size formula | `risk_amount / (entry - SL)` | Risk-based sizing |
| Max concurrent positions | 2 | Focus, capital efficiency |
| Max capital deployed | 50% (₹2L) | Reserve for exits, margin |
| Min confidence score | 0.5 | Skip low-conviction setups |
| Min reward:risk ratio | 1.5:1 | Positive expectancy requirement |

### Layer 2: Pre-Execution (Executor Startup)

| Check | Action on Fail |
|-------|---------------|
| Plan staleness > 14 hours | Skip trading, warn |
| Insufficient capital in account | Skip trading, warn |
| Stock halted/suspended | Skip that stock |
| Current price moved > 2% from plan entry | Skip that stock |
| Total exposure would exceed limits | Reduce position or skip |

### Layer 3: Live Execution

| Rule | Mechanism |
|------|-----------|
| Stop loss | Pre-placed SL order (bracket/cover order via Kite, exchange-level) |
| Max daily loss: 2% (₹8,000) | Kill switch — cancel all pending, square off all positions |
| Hard square-off time: 15:10 | Market orders to close everything, no exceptions |
| Connection drop > 30s | On reconnect: check positions, re-place SL if needed |
| Heartbeat logging | Every 60s to `logs/` — verifiable liveness |

### Crash Recovery

On executor restart during market hours:
1. Query Kite for open positions
2. If positions found without active SL → place SL immediately
3. If past 15:10 → square off immediately
4. Resume normal monitoring

## Paper Trading

### Virtual Broker

`VirtualBroker` implements same interface as `KiteClient`:
- `place_order(stock, qty, price, order_type)` → simulated order ID
- `cancel_order(order_id)` → cancel simulated order
- `get_positions()` → current virtual positions
- `get_pnl()` → virtual P&L

### Fill Simulation

Two modes:
1. **Live simulation** (requires Kite Connect subscription) — uses real-time prices from Kite WebSocket for realistic paper trading
2. **Historical replay** (no subscription needed) — replays past candle data from yfinance for development and initial testing

In both modes:
- Limit orders fill when price crosses order price
- Slippage simulation: +0.05% on buys, -0.05% on sells
- Respects exchange hours — no fills outside 9:15-15:30
- Virtual capital tracked in SQLite

### Graduation Criteria (manual decision)

| Metric | Minimum |
|--------|---------|
| Paper trading days | 30 |
| Win rate | > 50% |
| Average reward:risk | > 1.5 |
| Max drawdown | < 5% of capital |
| Consecutive loss streak | < 5 |

No auto-graduation. User reviews metrics and manually switches `MODE=live` in config.

## CLI Interface

```bash
# Analysis (run anytime — night before or morning)
python -m tradingbot analyze
  → Runs scanner + strategy → saves trade plan
  → Prints plan summary to terminal

# Execution
python -m tradingbot execute              # live mode
python -m tradingbot execute --paper      # paper mode

# Utilities
python -m tradingbot status               # open positions, today's P&L
python -m tradingbot history              # 30-day trade history, stats
python -m tradingbot history --detailed   # individual trade breakdown
python -m tradingbot plan show            # today's trade plan
python -m tradingbot plan show --date 2026-09-20

# Backtesting
python -m tradingbot backtest --strategy breakout --days 90
python -m tradingbot backtest --strategy all --days 30

# Setup
python -m tradingbot setup               # interactive first-time config
python -m tradingbot auth                 # Kite Connect OAuth flow
```

## Tech Stack

| Component | Choice | Version |
|-----------|--------|---------|
| Language | Python | 3.12+ |
| Broker SDK | kiteconnect | Latest |
| LLM SDK | anthropic | Latest |
| Data processing | pandas, numpy | Latest |
| Technical indicators | Custom (pandas-based) + ta-lib optional | — |
| Database | SQLite (stdlib sqlite3) | — |
| WebSocket | kiteticker (part of kiteconnect) | — |
| CLI framework | click | Latest |
| Config | tomli (TOML parsing) + python-dotenv | — |
| HTTP client | httpx | Latest (for NSE API, market data) |
| Scheduling | None — manual CLI invocation | — |
| Testing | pytest + pytest-asyncio | Latest |

### No Heavy Frameworks

No Django, FastAPI, CrewAI, LangChain, or agent frameworks. Plain Python modules with clean interfaces. Less magic, fewer dependencies, easier to debug.

## Reference Code Sources

Extracted from open-source repos during research (to adapt, not copy directly):

| Our Module | Reference Source | What to Adapt |
|-----------|-----------------|---------------|
| `core/kite_client.py` | india-trade-cli `brokers/zerodha.py` | Kite wrapper pattern, token management, order placement |
| `core/risk_manager.py` | nse-navigators `position_manager.py` + india-trade-cli `risk_gate.py` | Position sizing formula, kill switch, exposure limits |
| `scanner/market_context.py` | StockResearchAgenticAI `tools/institutional.py` | NSE session cookie trick, FII/DII API endpoint |
| `strategy/indicators.py` | nse-navigators `technical_tools.py` + StockResearchAgenticAI `tools/analysis.py` | Indicator computation, DBSCAN S/R clustering |
| `scanner/market_analyzer.py` | agentic-stock-research `prompts.py` | Prompt engineering patterns for stock selection |
| `paper/virtual_broker.py` | india-trade-cli `engine/paper.py` | Paper trading interface pattern |
| `executor/exit_manager.py` | nse-navigators `stop_loss_manager.py` | Trailing stop ratchet algorithm |

## Configuration

### config.toml

```toml
[general]
mode = "paper"  # "paper" or "live"
capital = 400000
log_level = "INFO"

[scanner]
min_volume = 500000
min_price = 50
max_price = 5000
min_market_cap_cr = 5000
min_atr_pct = 0.5
max_stocks_to_llm = 100
llm_pick_count = 15

[strategy]
backtest_days = 30
candle_interval = "15minute"
min_confidence = 0.5
min_reward_risk = 1.5
max_trades_per_day = 2

[risk]
max_risk_per_trade_pct = 0.01
max_daily_loss_pct = 0.02
max_capital_deployed_pct = 0.50
max_concurrent_positions = 2

[execution]
entry_slippage_pct = 0.05
square_off_time = "15:10"
connection_timeout_sec = 30
heartbeat_interval_sec = 60
plan_max_age_hours = 14

[llm]
provider = "anthropic"  # "anthropic" or "ollama"
model = "claude-sonnet-5"
timeout_sec = 60
max_retries = 1

[paper]
slippage_pct = 0.05
initial_capital = 400000
```

### .env (never committed)

```
ANTHROPIC_API_KEY=sk-ant-...
KITE_API_KEY=...
KITE_API_SECRET=...
```

## Logging & Observability

- All LLM prompts + responses: `logs/llm/YYYY-MM-DD.jsonl`
- All orders + fills: `logs/orders/YYYY-MM-DD.jsonl`
- Executor heartbeat: `logs/heartbeat/YYYY-MM-DD.log`
- Daily summary: `logs/daily/YYYY-MM-DD.json`
- Structured JSON logs for programmatic analysis

## Regulatory Note

SEBI introduced static IP requirements for API-based trading (effective April 2026). This may require running the executor from a cloud VPS with a static IP in the future. Current local Mac deployment works but should be monitored for compliance changes. The architecture supports migration to cloud deployment without code changes.

## Open Questions

1. **Kite Connect subscription timing** — need active subscription before development of execution layer. Paper trading with historical data can start without it.
2. **NSE data source for scanner** — yfinance (free, 15min delayed) vs Kite historical data API (real-time, needs subscription) vs direct NSE website scraping. For analysis phase, 15min delay is acceptable since we run it night before.
3. **Strategy library expansion** — start with 5 strategies, expand based on paper trading results. Each strategy is a pluggable module.
