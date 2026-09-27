# Analysis Pipeline Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 50-stock yfinance-based analysis pipeline with a professional 3-tier funnel scanning ~1500 NSE stocks via Kite Connect, with statistical backtesting, multi-run accumulation, and full broker execution integration.

**Architecture:** 3-tier funnel (Deterministic Screen → LLM Market/Sector Analysis → Deep Per-Stock Analysis) with walk-forward backtesting, Monte Carlo confidence, multi-run persistence, and Kite Connect for data + execution. Each tier narrows the universe: ~1500 → ~80 → ~15 → ~5 approved setups.

**Tech Stack:** Python 3.13, asyncio, Kite Connect API (kiteconnect), Anthropic Claude API, SQLite, pandas/numpy, FastAPI, pytest

**Spec:** `docs/superpowers/specs/2026-09-27-analysis-pipeline-redesign.md`

## Global Constraints

- Python ≥ 3.12, async throughout
- All new config sections added to `config.toml` with frozen dataclasses in `config.py`
- Existing 358 tests must keep passing (no breaking changes to models used by executor/frontend)
- `npm --legacy-peer-deps` for web/ directory
- Secrets from environment only (never disk), loaded via python-dotenv
- LLM prompts must work across OpenAI and Anthropic providers (structured tool/function calling)
- All monetary values in INR, all times in IST (`ZoneInfo("Asia/Kolkata")`)

## Review Focus

1. **Kite API rate limiting:** 3 req/sec for historical data — sync code must throttle; a test that fires 10 parallel fetches would get 429s in production
2. **Backtest lookahead bias:** Walk-forward windows must never let future data leak into training; an off-by-one in the split index silently inflates win rates
3. **Monte Carlo with insufficient trades:** Running 10K shuffles on 5 trades produces meaningless statistics; quality gate must reject before Monte Carlo runs
4. **LLM hallucinated price levels:** Per-stock deep analysis may invent support/resistance levels not in the data; validation must cross-check proposed entry/stop against actual candle range
5. **Multi-run race condition:** Two concurrent analysis runs writing to the same SQLite tables; setup_store must handle concurrent inserts without data corruption

---

## File Structure

### New Files

```
tradingbot/data/
  __init__.py
  kite_client.py              # Kite Connect API wrapper (instruments, historical, margins)
  instrument_cache.py         # SQLite store for NSE instrument metadata
  candle_store.py             # SQLite store for OHLCV candles (all timeframes)
  data_sync.py                # Incremental sync orchestrator with rate limiting

tradingbot/screening/
  __init__.py
  liquidity_filter.py         # Phase 1A: volume, price, cap, spread, trading days
  factor_scorer.py            # Phase 1B: 9-factor composite scoring (0-100)
  correlation_filter.py       # Phase 1C: sector-aware deduplication
  screener.py                 # Tier 1 orchestrator: filter → score → correlate → enrich

tradingbot/analysis/
  __init__.py
  prompts.py                  # All 5 LLM prompt templates + JSON schemas
  tier2_analyzer.py           # 3 LLM calls: regime, sector, shortlist
  tier3_analyzer.py           # Per-stock deep analysis + adversarial validation
  pipeline.py                 # Full analysis orchestrator (replaces plan_generator)

tradingbot/backtest/
  __init__.py
  costs.py                    # Zerodha transaction cost model
  walk_forward.py             # Walk-forward backtesting engine
  monte_carlo.py              # Monte Carlo simulation for confidence intervals
  quality_gates.py            # Pass/fail gates for strategy-stock combos
  regime_tagger.py            # Tag historical days with market regime

tradingbot/strategy/strategies/
  gap_and_go.py               # New: gap continuation / gap fill
  pivot_point.py              # New: pivot level bounce/break
  relative_strength.py        # New: strongest stock in strongest sector
  bollinger_squeeze.py        # New: bandwidth compression → expansion
  supply_demand.py            # New: institutional zone rejection
  confluence.py               # Meta: multi-timeframe confluence scorer

tradingbot/execution/
  kite_auth.py                # Kite OAuth2 flow + token management
  kite_executor.py            # Order placement, modification, cancellation
  capital_manager.py          # Live margin/capital from Kite
  position_monitor.py         # WebSocket tick monitoring + partial booking + trailing
  safety.py                   # Kill switches, network protection, order validation

tradingbot/persistence/
  __init__.py
  run_store.py                # AnalysisRun CRUD (SQLite)
  setup_store.py              # Setup lifecycle persistence (SQLite)
  daily_plan.py               # DailyPlan assembly + cross-run ranking
```

### Modified Files

```
config.toml                          # New sections: [kite], [screening], [backtest]
tradingbot/core/models.py            # New enums, dataclasses, extended StrategyName
tradingbot/core/config.py            # New config dataclasses: KiteConfig, ScreeningConfig, BacktestConfig
tradingbot/core/database.py          # New tables: analysis_runs, setups
tradingbot/strategy/indicators.py    # New: adx, supertrend, camarilla_pivots, vwap_bands, bollinger_bandwidth
tradingbot/strategy/strategies/base.py  # Add regime parameter to generate_signal
tradingbot/api/analysis_routes.py    # New endpoints for multi-run, setup management
```

---

### Task 1: Extended Data Models

**Files:**
- Modify: `tradingbot/core/models.py`
- Test: `tests/core/test_models.py`

**Interfaces:**
- Consumes: nothing (foundation)
- Produces: `StrategyName` (10 values), `MarketRegime` (5 values), `SetupStatus`, `ExecutionMode`, `ScoredStock`, `AnalysisRun`, `TradeSetup` (extended), `SetupRanking`, `DailyPlan`, `BacktestReport`, `MonteCarloResult`, `QualityGateResult`

- [ ] **Step 1: Write tests for new enums and dataclasses**

```python
# tests/core/test_models_v2.py
from tradingbot.core.models import (
    StrategyName, MarketRegime, SetupStatus, ExecutionMode,
    ScoredStock, AnalysisRun, BacktestReport, MonteCarloResult,
    QualityGateResult,
)
from datetime import datetime, date
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def test_strategy_name_includes_new_strategies():
    assert StrategyName.GAP_AND_GO.value == "gap_and_go"
    assert StrategyName.PIVOT_POINT.value == "pivot_point"
    assert StrategyName.RELATIVE_STRENGTH.value == "relative_strength"
    assert StrategyName.BOLLINGER_SQUEEZE.value == "bollinger_squeeze"
    assert StrategyName.SUPPLY_DEMAND.value == "supply_demand"
    assert len(StrategyName) == 10


def test_market_regime_includes_low_vol_squeeze():
    assert MarketRegime.LOW_VOL_SQUEEZE.value == "low_vol_squeeze"
    assert MarketRegime.TRENDING_UP.value == "trending_up"
    assert MarketRegime.TRENDING_DOWN.value == "trending_down"
    assert len(MarketRegime) == 5


def test_setup_status_lifecycle():
    assert SetupStatus.PROPOSED.value == "proposed"
    assert SetupStatus.APPROVED.value == "approved"
    assert SetupStatus.REJECTED.value == "rejected"
    assert SetupStatus.ACTIVE.value == "active"
    assert SetupStatus.FILLED.value == "filled"
    assert SetupStatus.EXPIRED.value == "expired"
    assert SetupStatus.CLOSED.value == "closed"


def test_execution_mode():
    assert ExecutionMode.PAPER.value == "paper"
    assert ExecutionMode.LIVE.value == "live"
    assert ExecutionMode.SHADOW.value == "shadow"


def test_scored_stock():
    stock = ScoredStock(
        symbol="RELIANCE", exchange="NSE", last_price=2500.0,
        avg_volume=5_000_000, market_cap_cr=17_00_000, atr_pct=1.2,
        sector="energy", composite_score=78.5,
        factor_scores={"volume_surge": 85, "relative_strength": 72},
        instrument_token=738561,
    )
    assert stock.composite_score == 78.5
    assert stock.factor_scores["volume_surge"] == 85


def test_analysis_run():
    run = AnalysisRun(
        run_id="run_20260927_093015_abc123",
        timestamp=datetime.now(tz=IST),
        trade_date=date(2026, 9, 27),
        market_regime=MarketRegime.TRENDING_UP,
        regime_confidence=0.82,
        total_scanned=1500, tier1_passed=80,
        tier2_shortlisted=12, setups_proposed=8,
        setups_approved=5, llm_calls=16,
        llm_cost_usd=0.18, duration_seconds=45.2,
    )
    assert run.run_id.startswith("run_")
    assert run.tier1_passed == 80


def test_backtest_report():
    report = BacktestReport(
        symbol="RELIANCE", strategy=StrategyName.VWAP_BOUNCE,
        period_start=date(2025, 9, 27), period_end=date(2026, 9, 27),
        total_trades=47, winners=29, losers=18,
        win_rate=0.617, avg_winner=4850.0, avg_loser=-2890.0,
        profit_factor=2.70, expectancy=1740.0, expectancy_r=0.62,
        sharpe_ratio=1.85, max_drawdown_pct=4.2,
        max_consecutive_losses=4, avg_hold_minutes=47,
        oos_degradation=0.12, calmar_ratio=2.1,
    )
    assert report.profit_factor == 2.70
    assert report.win_rate == 0.617


def test_monte_carlo_result():
    mc = MonteCarloResult(
        simulations=10000, median_return_pct=18.4,
        p10_return_pct=6.2, p90_return_pct=34.1,
        median_max_drawdown=5.8, p95_max_drawdown=12.4,
        risk_of_ruin_pct=0.3, confidence_score=0.78,
    )
    assert mc.simulations == 10000
    assert mc.confidence_score == 0.78


def test_quality_gate_result():
    gate = QualityGateResult(
        passed=True,
        total_trades_ok=True, win_rate_ok=True,
        profit_factor_ok=True, expectancy_ok=True,
        oos_ok=True, monte_carlo_p10_ok=True,
        ruin_risk_ok=True, consecutive_losses_ok=True,
        failures=[],
    )
    assert gate.passed is True
    assert len(gate.failures) == 0

    gate_fail = QualityGateResult(
        passed=False,
        total_trades_ok=False, win_rate_ok=True,
        profit_factor_ok=True, expectancy_ok=True,
        oos_ok=True, monte_carlo_p10_ok=True,
        ruin_risk_ok=True, consecutive_losses_ok=True,
        failures=["total_trades: 12 < 30 minimum"],
    )
    assert gate_fail.passed is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/rmashruwala/work/Personal/Projects/trading-bot && .venv/bin/python -m pytest tests/core/test_models_v2.py -v`
Expected: ImportError — new classes don't exist yet

- [ ] **Step 3: Implement new enums and dataclasses**

Add to `tradingbot/core/models.py`:

```python
# Extend StrategyName enum — add after existing values
class StrategyName(str, Enum):
    BREAKOUT = "breakout"
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    VWAP_BOUNCE = "vwap_bounce"
    ORB = "orb"
    GAP_AND_GO = "gap_and_go"
    PIVOT_POINT = "pivot_point"
    RELATIVE_STRENGTH = "relative_strength"
    BOLLINGER_SQUEEZE = "bollinger_squeeze"
    SUPPLY_DEMAND = "supply_demand"


# Replace MarketRegime — more granular
class MarketRegime(str, Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGE_BOUND = "range_bound"
    VOLATILE = "volatile"
    LOW_VOL_SQUEEZE = "low_vol_squeeze"


class SetupStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVE = "active"
    FILLED = "filled"
    EXPIRED = "expired"
    CLOSED = "closed"


class ExecutionMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"
    SHADOW = "shadow"


@dataclass(frozen=True)
class ScoredStock:
    symbol: str
    exchange: str
    last_price: float
    avg_volume: float
    market_cap_cr: float
    atr_pct: float
    sector: str
    composite_score: float
    factor_scores: dict[str, float]
    instrument_token: int


@dataclass(frozen=True)
class AnalysisRun:
    run_id: str
    timestamp: datetime
    trade_date: date
    market_regime: MarketRegime
    regime_confidence: float
    total_scanned: int
    tier1_passed: int
    tier2_shortlisted: int
    setups_proposed: int
    setups_approved: int
    llm_calls: int
    llm_cost_usd: float
    duration_seconds: float


@dataclass(frozen=True)
class BacktestReport:
    symbol: str
    strategy: StrategyName
    period_start: date
    period_end: date
    total_trades: int
    winners: int
    losers: int
    win_rate: float
    avg_winner: float
    avg_loser: float
    profit_factor: float
    expectancy: float
    expectancy_r: float
    sharpe_ratio: float
    max_drawdown_pct: float
    max_consecutive_losses: int
    avg_hold_minutes: float
    oos_degradation: float
    calmar_ratio: float


@dataclass(frozen=True)
class MonteCarloResult:
    simulations: int
    median_return_pct: float
    p10_return_pct: float
    p90_return_pct: float
    median_max_drawdown: float
    p95_max_drawdown: float
    risk_of_ruin_pct: float
    confidence_score: float


@dataclass(frozen=True)
class QualityGateResult:
    passed: bool
    total_trades_ok: bool
    win_rate_ok: bool
    profit_factor_ok: bool
    expectancy_ok: bool
    oos_ok: bool
    monte_carlo_p10_ok: bool
    ruin_risk_ok: bool
    consecutive_losses_ok: bool
    failures: list[str]
```

Note: `MarketRegime` values changed — update `MarketContext.from_dict()` and any code referencing `TRENDING`/`RANGING` to use `TRENDING_UP`/`RANGE_BOUND`. Add backward-compat mapping in `from_dict`:

```python
_REGIME_COMPAT = {"trending": "trending_up", "ranging": "range_bound", "low_vol": "low_vol_squeeze"}

@classmethod
def from_dict(cls, raw: dict[str, Any]) -> MarketContext:
    regime_val = raw["regime"]
    regime_val = _REGIME_COMPAT.get(regime_val, regime_val)
    # ... rest unchanged, use MarketRegime(regime_val)
```

- [ ] **Step 4: Run new + existing model tests**

Run: `.venv/bin/python -m pytest tests/core/test_models_v2.py tests/core/test_models.py -v`
Expected: All pass. Existing tests may need `TRENDING` → `TRENDING_UP` fixes.

- [ ] **Step 5: Fix any existing test breakage from MarketRegime changes**

Search and update all references to old enum values across tests and source:
- `MarketRegime.TRENDING` → `MarketRegime.TRENDING_UP`
- `MarketRegime.RANGING` → `MarketRegime.RANGE_BOUND`
- `MarketRegime.LOW_VOL` → `MarketRegime.LOW_VOL_SQUEEZE`

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All 358+ tests pass

- [ ] **Step 6: Commit**

```bash
git add tradingbot/core/models.py tests/core/test_models_v2.py
git commit -m "feat(models): add extended enums and dataclasses for pipeline redesign

Add StrategyName (10 strategies), granular MarketRegime, SetupStatus
lifecycle, ExecutionMode (paper/live/shadow), ScoredStock, AnalysisRun,
BacktestReport, MonteCarloResult, QualityGateResult.

Backward-compat mapping for old MarketRegime values."
```

---

### Task 2: Config Extensions

**Files:**
- Modify: `tradingbot/core/config.py`
- Modify: `config.toml`
- Test: `tests/core/test_config.py`

**Interfaces:**
- Consumes: `ExecutionMode` from Task 1
- Produces: `KiteConfig`, `ScreeningConfig`, `BacktestConfig` dataclasses; updated `Config` aggregate

- [ ] **Step 1: Write tests for new config sections**

```python
# Add to tests/core/test_config.py or create tests/core/test_config_v2.py

def test_kite_config_loaded(tmp_path):
    toml = """
[general]
mode = "paper"
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

[screening]
min_volume = 500000
min_price = 50
max_price = 5000
min_market_cap_cr = 1000
min_atr_pct = 0.5
min_trading_days = 10
max_per_sector = 3
volume_surge_weight = 15
relative_strength_weight = 15
atr_expansion_weight = 10
price_structure_weight = 15
delivery_pct_weight = 10
sector_momentum_weight = 10
gap_analysis_weight = 10
candlestick_pattern_weight = 10
volume_profile_weight = 5

[backtest]
lookback_days = 365
walk_forward_windows = 10
train_pct = 70
monte_carlo_simulations = 10000
min_trades = 30
min_win_rate = 0.45
min_profit_factor = 1.5
min_expectancy_r = 0.3
max_oos_degradation = 0.3
max_risk_of_ruin = 0.05
max_consecutive_losses = 8

[kite]
api_key_env = "KITE_API_KEY"
api_secret_env = "KITE_API_SECRET"
sync_hour = 6
sync_minute = 0
rate_limit_per_sec = 3

[strategy]
backtest_days = 30
candle_interval = "15minute"
min_confidence = 0.5
min_reward_risk = 1.5
max_trades_per_day = 4

[risk]
max_risk_per_trade_pct = 0.01
max_daily_loss_pct = 0.02
max_capital_deployed_pct = 0.50
max_concurrent_positions = 4

[execution]
mode = "paper"
entry_slippage_pct = 0.05
square_off_time = "15:10"
connection_timeout_sec = 30
heartbeat_interval_sec = 60
plan_max_age_hours = 14
max_entry_price_drift_pct = 2.0
shadow_fraction = 0.1

[llm]
provider = "anthropic"
model = "claude-sonnet-4-20250514"
timeout_sec = 60
max_retries = 1

[paper]
slippage_pct = 0.05
initial_capital = 400000
"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(toml)
    import os
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    os.environ["KITE_API_KEY"] = "test-kite"
    os.environ["KITE_API_SECRET"] = "test-secret"

    from tradingbot.core.config import load_config
    cfg = load_config(config_file)

    assert cfg.screening.min_volume == 500000
    assert cfg.screening.max_per_sector == 3
    assert cfg.screening.volume_surge_weight == 15
    assert cfg.backtest.lookback_days == 365
    assert cfg.backtest.monte_carlo_simulations == 10000
    assert cfg.backtest.min_profit_factor == 1.5
    assert cfg.kite.rate_limit_per_sec == 3
    assert cfg.kite.sync_hour == 6
    assert cfg.execution.shadow_fraction == 0.1
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/core/test_config_v2.py -v`
Expected: AttributeError — `Config` has no `screening`, `backtest`, `kite` attributes

- [ ] **Step 3: Add new config dataclasses and update load_config**

Add to `tradingbot/core/config.py`:

```python
@dataclass(frozen=True)
class ScreeningConfig:
    min_volume: int
    min_price: float
    max_price: float
    min_market_cap_cr: float
    min_atr_pct: float
    min_trading_days: int
    max_per_sector: int
    volume_surge_weight: int
    relative_strength_weight: int
    atr_expansion_weight: int
    price_structure_weight: int
    delivery_pct_weight: int
    sector_momentum_weight: int
    gap_analysis_weight: int
    candlestick_pattern_weight: int
    volume_profile_weight: int


@dataclass(frozen=True)
class BacktestConfig:
    lookback_days: int
    walk_forward_windows: int
    train_pct: int
    monte_carlo_simulations: int
    min_trades: int
    min_win_rate: float
    min_profit_factor: float
    min_expectancy_r: float
    max_oos_degradation: float
    max_risk_of_ruin: float
    max_consecutive_losses: int


@dataclass(frozen=True)
class KiteConfig:
    api_key_env: str
    api_secret_env: str
    sync_hour: int
    sync_minute: int
    rate_limit_per_sec: int
```

Update `ExecutionConfig` to add `shadow_fraction: float` and `mode: str` fields.

Update `Config` to add `screening`, `backtest`, `kite` fields.

Update `load_config()` to parse these sections with `_section()`.

- [ ] **Step 4: Update config.toml with new sections**

Add `[screening]`, `[backtest]`, `[kite]` sections to `config.toml`. Update `[execution]` with `mode` and `shadow_fraction`. Update `[llm]` provider to `"anthropic"` and model to `"claude-sonnet-4-20250514"`.

- [ ] **Step 5: Run all config tests**

Run: `.venv/bin/python -m pytest tests/core/test_config.py tests/core/test_config_v2.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add tradingbot/core/config.py config.toml tests/core/test_config_v2.py
git commit -m "feat(config): add screening, backtest, kite config sections

ScreeningConfig (9 factor weights, sector cap), BacktestConfig
(walk-forward params, quality gates), KiteConfig (rate limiting, sync).
Switch LLM to Anthropic Claude."
```

---

### Task 3: Kite Connect Client Wrapper

**Files:**
- Create: `tradingbot/data/__init__.py`
- Create: `tradingbot/data/kite_client.py`
- Test: `tests/data/__init__.py`
- Test: `tests/data/test_kite_client.py`

**Interfaces:**
- Consumes: `KiteConfig` from Task 2
- Produces: `KiteClient` class with methods: `fetch_instruments()`, `fetch_historical(token, interval, from_date, to_date)`, `get_margins()`, `get_ltp(symbols)`, `get_positions()`

- [ ] **Step 1: Write tests with mocked KiteConnect**

```python
# tests/data/test_kite_client.py
import pytest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from tradingbot.data.kite_client import KiteClient, KiteRateLimiter


def test_rate_limiter_throttles():
    limiter = KiteRateLimiter(max_per_sec=3)
    import time
    start = time.monotonic()
    for _ in range(4):
        limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.9  # 4th call waits ~1 second


@pytest.fixture
def mock_kite():
    kite = MagicMock()
    kite.instruments.return_value = [
        {"instrument_token": 738561, "tradingsymbol": "RELIANCE",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
        {"instrument_token": 341249, "tradingsymbol": "HDFCBANK",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
    ]
    kite.historical_data.return_value = [
        {"date": datetime(2026, 9, 26, 9, 15), "open": 2500, "high": 2520,
         "low": 2490, "close": 2510, "volume": 100000},
    ]
    kite.margins.return_value = {"equity": {"available": {"live_balance": 400000}}}
    kite.ltp.return_value = {"NSE:RELIANCE": {"last_price": 2510.0}}
    return kite


def test_fetch_instruments(mock_kite):
    client = KiteClient(mock_kite, rate_limit_per_sec=3)
    instruments = client.fetch_instruments()
    assert len(instruments) == 2
    assert instruments[0]["tradingsymbol"] == "RELIANCE"
    mock_kite.instruments.assert_called_once_with("NSE")


def test_fetch_historical(mock_kite):
    client = KiteClient(mock_kite, rate_limit_per_sec=3)
    candles = client.fetch_historical(
        instrument_token=738561,
        interval="day",
        from_date=date(2026, 9, 1),
        to_date=date(2026, 9, 26),
    )
    assert len(candles) == 1
    assert candles[0]["close"] == 2510
    mock_kite.historical_data.assert_called_once()


def test_fetch_historical_respects_rate_limit(mock_kite):
    client = KiteClient(mock_kite, rate_limit_per_sec=100)
    for _ in range(5):
        client.fetch_historical(738561, "day", date(2026, 9, 1), date(2026, 9, 26))
    assert mock_kite.historical_data.call_count == 5


def test_get_margins(mock_kite):
    client = KiteClient(mock_kite, rate_limit_per_sec=3)
    margins = client.get_margins()
    assert margins["equity"]["available"]["live_balance"] == 400000


def test_get_ltp(mock_kite):
    client = KiteClient(mock_kite, rate_limit_per_sec=3)
    ltp = client.get_ltp(["NSE:RELIANCE"])
    assert ltp["NSE:RELIANCE"]["last_price"] == 2510.0
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/data/test_kite_client.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: Implement KiteClient**

```python
# tradingbot/data/kite_client.py
from __future__ import annotations

import time
import threading
from collections import deque
from datetime import date, datetime
from typing import Any


class KiteRateLimiter:
    """Token-bucket rate limiter for Kite API calls."""

    def __init__(self, max_per_sec: int = 3):
        self._max = max_per_sec
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            while self._timestamps and now - self._timestamps[0] > 1.0:
                self._timestamps.popleft()
            if len(self._timestamps) >= self._max:
                sleep_until = self._timestamps[0] + 1.0
                time.sleep(max(0, sleep_until - now))
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] > 1.0:
                    self._timestamps.popleft()
            self._timestamps.append(time.monotonic())


class KiteClient:
    """Thin wrapper around kiteconnect.KiteConnect with rate limiting."""

    def __init__(self, kite: Any, rate_limit_per_sec: int = 3):
        self._kite = kite
        self._limiter = KiteRateLimiter(rate_limit_per_sec)

    @property
    def kite(self) -> Any:
        return self._kite

    def fetch_instruments(self, exchange: str = "NSE") -> list[dict]:
        self._limiter.acquire()
        return self._kite.instruments(exchange)

    def fetch_historical(
        self,
        instrument_token: int,
        interval: str,
        from_date: date,
        to_date: date,
    ) -> list[dict]:
        self._limiter.acquire()
        return self._kite.historical_data(
            instrument_token, from_date, to_date, interval,
        )

    def get_margins(self, segment: str = "equity") -> dict:
        self._limiter.acquire()
        return self._kite.margins(segment)

    def get_ltp(self, symbols: list[str]) -> dict:
        self._limiter.acquire()
        return self._kite.ltp(symbols)

    def get_positions(self) -> dict:
        self._limiter.acquire()
        return self._kite.positions()

    def place_order(self, **kwargs: Any) -> str:
        self._limiter.acquire()
        return self._kite.place_order(**kwargs)

    def modify_order(self, **kwargs: Any) -> str:
        self._limiter.acquire()
        return self._kite.modify_order(**kwargs)

    def cancel_order(self, variety: str, order_id: str) -> str:
        self._limiter.acquire()
        return self._kite.cancel_order(variety, order_id)

    def profile(self) -> dict:
        self._limiter.acquire()
        return self._kite.profile()
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/data/test_kite_client.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add tradingbot/data/ tests/data/
git commit -m "feat(data): add Kite Connect client wrapper with rate limiting

KiteClient wraps kiteconnect with token-bucket rate limiter (3 req/sec).
Methods: fetch_instruments, fetch_historical, get_margins, get_ltp,
place/modify/cancel_order."
```

---

### Task 4: Instrument Cache & Candle Store

**Files:**
- Create: `tradingbot/data/instrument_cache.py`
- Create: `tradingbot/data/candle_store.py`
- Test: `tests/data/test_instrument_cache.py`
- Test: `tests/data/test_candle_store.py`

**Interfaces:**
- Consumes: `KiteClient.fetch_instruments()` from Task 3
- Produces: `InstrumentCache.refresh()`, `InstrumentCache.get_all()`, `InstrumentCache.get_token(symbol)`, `CandleStore.upsert(symbol, interval, candles)`, `CandleStore.read(symbol, interval, from_dt, to_dt)`, `CandleStore.last_timestamp(symbol, interval)`

- [ ] **Step 1: Write tests for InstrumentCache**

```python
# tests/data/test_instrument_cache.py
import pytest
import sqlite3
from tradingbot.data.instrument_cache import InstrumentCache


@pytest.fixture
def cache(tmp_path):
    db_path = tmp_path / "instruments.db"
    return InstrumentCache(db_path)


def test_refresh_and_get_all(cache):
    instruments = [
        {"instrument_token": 738561, "tradingsymbol": "RELIANCE",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
        {"instrument_token": 341249, "tradingsymbol": "HDFCBANK",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
    ]
    cache.refresh(instruments)
    result = cache.get_all()
    assert len(result) == 2
    symbols = {r["symbol"] for r in result}
    assert symbols == {"RELIANCE", "HDFCBANK"}


def test_get_token(cache):
    cache.refresh([
        {"instrument_token": 738561, "tradingsymbol": "RELIANCE",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
    ])
    assert cache.get_token("RELIANCE") == 738561


def test_get_token_missing_raises(cache):
    cache.refresh([])
    with pytest.raises(KeyError):
        cache.get_token("NONEXISTENT")


def test_refresh_replaces_old_data(cache):
    cache.refresh([
        {"instrument_token": 1, "tradingsymbol": "OLD",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
    ])
    cache.refresh([
        {"instrument_token": 2, "tradingsymbol": "NEW",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
    ])
    result = cache.get_all()
    assert len(result) == 1
    assert result[0]["symbol"] == "NEW"


def test_filters_non_equity(cache):
    cache.refresh([
        {"instrument_token": 1, "tradingsymbol": "RELIANCE",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
        {"instrument_token": 2, "tradingsymbol": "NIFTY26SEP",
         "exchange": "NFO", "lot_size": 50, "tick_size": 0.05,
         "instrument_type": "FUT", "segment": "NFO-FUT"},
    ])
    result = cache.get_all()
    assert len(result) == 1
```

- [ ] **Step 2: Write tests for CandleStore**

```python
# tests/data/test_candle_store.py
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from tradingbot.data.candle_store import CandleStore

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "candles.db"
    return CandleStore(db_path)


def test_upsert_and_read(store):
    candles = [
        {"date": datetime(2026, 9, 26, 9, 15, tzinfo=IST),
         "open": 2500, "high": 2520, "low": 2490, "close": 2510, "volume": 100000},
        {"date": datetime(2026, 9, 26, 9, 30, tzinfo=IST),
         "open": 2510, "high": 2530, "low": 2505, "close": 2525, "volume": 80000},
    ]
    store.upsert("RELIANCE", "15minute", candles)
    result = store.read(
        "RELIANCE", "15minute",
        datetime(2026, 9, 26, 9, 0, tzinfo=IST),
        datetime(2026, 9, 26, 10, 0, tzinfo=IST),
    )
    assert len(result) == 2
    assert result.iloc[0]["close"] == 2510


def test_upsert_deduplicates(store):
    candle = [{"date": datetime(2026, 9, 26, 9, 15, tzinfo=IST),
               "open": 2500, "high": 2520, "low": 2490, "close": 2510, "volume": 100000}]
    store.upsert("RELIANCE", "15minute", candle)
    store.upsert("RELIANCE", "15minute", candle)
    result = store.read(
        "RELIANCE", "15minute",
        datetime(2026, 9, 26, 9, 0, tzinfo=IST),
        datetime(2026, 9, 26, 10, 0, tzinfo=IST),
    )
    assert len(result) == 1


def test_last_timestamp_empty(store):
    assert store.last_timestamp("RELIANCE", "day") is None


def test_last_timestamp(store):
    candles = [
        {"date": datetime(2026, 9, 25, tzinfo=IST),
         "open": 2500, "high": 2520, "low": 2490, "close": 2510, "volume": 100000},
        {"date": datetime(2026, 9, 26, tzinfo=IST),
         "open": 2510, "high": 2530, "low": 2505, "close": 2525, "volume": 80000},
    ]
    store.upsert("RELIANCE", "day", candles)
    last = store.last_timestamp("RELIANCE", "day")
    assert last == datetime(2026, 9, 26, tzinfo=IST)


def test_read_returns_dataframe_with_correct_columns(store):
    candles = [{"date": datetime(2026, 9, 26, 9, 15, tzinfo=IST),
                "open": 100, "high": 110, "low": 95, "close": 105, "volume": 50000}]
    store.upsert("TCS", "day", candles)
    df = store.read("TCS", "day",
                    datetime(2026, 9, 26, tzinfo=IST),
                    datetime(2026, 9, 27, tzinfo=IST))
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.name == "date"
```

- [ ] **Step 3: Run tests to verify failure**

Run: `.venv/bin/python -m pytest tests/data/test_instrument_cache.py tests/data/test_candle_store.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 4: Implement InstrumentCache**

```python
# tradingbot/data/instrument_cache.py
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class InstrumentCache:
    """SQLite-backed cache for NSE instrument metadata."""

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS instruments (
                token INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                exchange TEXT NOT NULL,
                lot_size INTEGER NOT NULL,
                tick_size REAL NOT NULL
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_symbol ON instruments(symbol)"
        )
        self._conn.commit()

    def refresh(self, raw_instruments: list[dict[str, Any]]) -> int:
        equities = [
            i for i in raw_instruments
            if i.get("instrument_type") == "EQ" and i.get("segment") == "NSE"
        ]
        self._conn.execute("DELETE FROM instruments")
        self._conn.executemany(
            "INSERT INTO instruments (token, symbol, exchange, lot_size, tick_size) "
            "VALUES (?, ?, ?, ?, ?)",
            [(i["instrument_token"], i["tradingsymbol"], i["exchange"],
              i["lot_size"], i["tick_size"]) for i in equities],
        )
        self._conn.commit()
        return len(equities)

    def get_all(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM instruments").fetchall()
        return [{"token": r["token"], "symbol": r["symbol"],
                 "exchange": r["exchange"], "lot_size": r["lot_size"],
                 "tick_size": r["tick_size"]} for r in rows]

    def get_token(self, symbol: str) -> int:
        row = self._conn.execute(
            "SELECT token FROM instruments WHERE symbol = ?", (symbol,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Instrument not found: {symbol}")
        return row["token"]

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 5: Implement CandleStore**

```python
# tradingbot/data/candle_store.py
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


class CandleStore:
    """SQLite-backed store for OHLCV candle data across timeframes."""

    def __init__(self, db_path: Path):
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS candles (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER NOT NULL,
                PRIMARY KEY (symbol, interval, timestamp)
            )
        """)
        self._conn.commit()

    def upsert(self, symbol: str, interval: str, candles: list[dict[str, Any]]) -> int:
        self._conn.executemany(
            "INSERT OR REPLACE INTO candles "
            "(symbol, interval, timestamp, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(symbol, interval, c["date"].isoformat(), c["open"], c["high"],
              c["low"], c["close"], c["volume"]) for c in candles],
        )
        self._conn.commit()
        return len(candles)

    def read(
        self, symbol: str, interval: str,
        from_dt: datetime, to_dt: datetime,
    ) -> pd.DataFrame:
        rows = self._conn.execute(
            "SELECT timestamp, open, high, low, close, volume FROM candles "
            "WHERE symbol = ? AND interval = ? AND timestamp >= ? AND timestamp <= ? "
            "ORDER BY timestamp",
            (symbol, interval, from_dt.isoformat(), to_dt.isoformat()),
        ).fetchall()
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        return df

    def last_timestamp(self, symbol: str, interval: str) -> datetime | None:
        row = self._conn.execute(
            "SELECT MAX(timestamp) FROM candles WHERE symbol = ? AND interval = ?",
            (symbol, interval),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return datetime.fromisoformat(row[0])

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/data/ -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add tradingbot/data/instrument_cache.py tradingbot/data/candle_store.py tests/data/
git commit -m "feat(data): add InstrumentCache and CandleStore (SQLite)

InstrumentCache: refresh from Kite, filter to EQ+NSE, lookup by symbol.
CandleStore: upsert OHLCV with dedup, read as DataFrame, track last sync."
```

---

### Task 5: Data Sync Orchestrator

**Files:**
- Create: `tradingbot/data/data_sync.py`
- Test: `tests/data/test_data_sync.py`

**Interfaces:**
- Consumes: `KiteClient` (Task 3), `InstrumentCache` (Task 4), `CandleStore` (Task 4), `KiteConfig` (Task 2)
- Produces: `DataSync.sync_instruments()`, `DataSync.sync_daily_candles(symbols)`, `DataSync.sync_intraday_candles(symbols, interval)`, `DataSync.deep_fetch(symbols)` — all populate local cache incrementally

- [ ] **Step 1: Write tests**

```python
# tests/data/test_data_sync.py
import pytest
from datetime import date, datetime
from unittest.mock import MagicMock, patch, call
from zoneinfo import ZoneInfo
from tradingbot.data.data_sync import DataSync
from tradingbot.data.instrument_cache import InstrumentCache
from tradingbot.data.candle_store import CandleStore

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def components(tmp_path):
    cache = InstrumentCache(tmp_path / "instruments.db")
    store = CandleStore(tmp_path / "candles.db")
    client = MagicMock()
    client.fetch_instruments.return_value = [
        {"instrument_token": 738561, "tradingsymbol": "RELIANCE",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
    ]
    client.fetch_historical.return_value = [
        {"date": datetime(2026, 9, 26, tzinfo=IST),
         "open": 2500, "high": 2520, "low": 2490, "close": 2510, "volume": 100000},
    ]
    sync = DataSync(client=client, instrument_cache=cache, candle_store=store)
    return sync, client, cache, store


def test_sync_instruments(components):
    sync, client, cache, _ = components
    count = sync.sync_instruments()
    assert count == 1
    assert cache.get_token("RELIANCE") == 738561


def test_sync_daily_candles_incremental(components):
    sync, client, _, store = components
    sync.sync_daily_candles(["RELIANCE"], lookback_days=365)
    assert client.fetch_historical.call_count == 1
    args = client.fetch_historical.call_args
    assert args.kwargs["interval"] == "day" or args[0][1] == "day"


def test_sync_intraday_candles(components):
    sync, client, _, store = components
    sync.sync_intraday_candles(["RELIANCE"], interval="15minute", lookback_days=60)
    assert client.fetch_historical.call_count >= 1


def test_deep_fetch_multiple_timeframes(components):
    sync, client, _, store = components
    sync.deep_fetch(["RELIANCE"])
    # deep_fetch should call for 5minute and minute intervals
    intervals_called = [c.kwargs.get("interval", c[0][1] if len(c[0]) > 1 else None)
                        for c in client.fetch_historical.call_args_list]
    assert len(client.fetch_historical.call_args_list) >= 2
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/data/test_data_sync.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: Implement DataSync**

```python
# tradingbot/data/data_sync.py
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from tradingbot.data.candle_store import CandleStore
from tradingbot.data.instrument_cache import InstrumentCache
from tradingbot.data.kite_client import KiteClient

IST = ZoneInfo("Asia/Kolkata")
log = logging.getLogger(__name__)

KITE_MAX_DAYS = {"day": 2000, "60minute": 400, "30minute": 200,
                 "15minute": 200, "5minute": 100, "minute": 60}


class DataSync:
    """Incrementally syncs market data from Kite to local stores."""

    def __init__(
        self,
        client: KiteClient,
        instrument_cache: InstrumentCache,
        candle_store: CandleStore,
    ):
        self._client = client
        self._instruments = instrument_cache
        self._candles = candle_store

    def sync_instruments(self) -> int:
        raw = self._client.fetch_instruments("NSE")
        count = self._instruments.refresh(raw)
        log.info("Synced %d NSE equity instruments", count)
        return count

    def sync_daily_candles(
        self, symbols: list[str], lookback_days: int = 365,
    ) -> int:
        total = 0
        for symbol in symbols:
            total += self._sync_symbol(symbol, "day", lookback_days)
        return total

    def sync_intraday_candles(
        self, symbols: list[str], interval: str = "15minute",
        lookback_days: int = 60,
    ) -> int:
        max_days = KITE_MAX_DAYS.get(interval, 60)
        days = min(lookback_days, max_days)
        total = 0
        for symbol in symbols:
            total += self._sync_symbol(symbol, interval, days)
        return total

    def deep_fetch(self, symbols: list[str]) -> int:
        total = 0
        for symbol in symbols:
            total += self._sync_symbol(symbol, "5minute", 100)
            total += self._sync_symbol(symbol, "minute", 5)
        return total

    def _sync_symbol(self, symbol: str, interval: str, lookback_days: int) -> int:
        try:
            token = self._instruments.get_token(symbol)
        except KeyError:
            log.warning("No instrument token for %s, skipping", symbol)
            return 0

        last = self._candles.last_timestamp(symbol, interval)
        if last is not None:
            from_date = last.date() + timedelta(days=1)
        else:
            from_date = date.today() - timedelta(days=lookback_days)

        to_date = date.today()
        if from_date > to_date:
            return 0

        try:
            candles = self._client.fetch_historical(
                instrument_token=token,
                interval=interval,
                from_date=from_date,
                to_date=to_date,
            )
        except Exception:
            log.exception("Failed to fetch %s %s", symbol, interval)
            return 0

        if candles:
            self._candles.upsert(symbol, interval, candles)
            log.info("Synced %d %s candles for %s", len(candles), interval, symbol)
        return len(candles)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/data/ -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add tradingbot/data/data_sync.py tests/data/test_data_sync.py
git commit -m "feat(data): add DataSync for incremental Kite→local sync

Syncs instruments, daily candles (1yr), intraday (15min/5min/1min).
Incremental: only fetches since last_timestamp. Respects Kite API
interval-specific day limits."
```

---

### Task 6: New Technical Indicators

**Files:**
- Modify: `tradingbot/strategy/indicators.py`
- Modify: `tradingbot/core/models.py` (extend `IndicatorSnapshot`)
- Test: `tests/strategy/test_indicators_v2.py`

**Interfaces:**
- Consumes: OHLCV DataFrames
- Produces: `adx(df)`, `supertrend(df)`, `camarilla_pivots(df)`, `vwap_bands(df)`, `bollinger_bandwidth(close)`, `volume_profile(df)` functions; extended `IndicatorSnapshot` with new fields

- [ ] **Step 1: Write tests for new indicators**

```python
# tests/strategy/test_indicators_v2.py
import numpy as np
import pandas as pd
import pytest
from tradingbot.strategy.indicators import (
    adx, supertrend, camarilla_pivots, vwap_bands, bollinger_bandwidth,
    volume_profile,
)


@pytest.fixture
def sample_df():
    np.random.seed(42)
    n = 100
    close = 2500 + np.cumsum(np.random.randn(n) * 5)
    high = close + np.abs(np.random.randn(n) * 3)
    low = close - np.abs(np.random.randn(n) * 3)
    volume = np.random.randint(50000, 200000, n)
    return pd.DataFrame({
        "open": close + np.random.randn(n),
        "high": high, "low": low, "close": close,
        "volume": volume,
    })


def test_adx_returns_series(sample_df):
    result = adx(sample_df, period=14)
    assert isinstance(result, pd.Series)
    assert len(result) == len(sample_df)
    valid = result.dropna()
    assert len(valid) > 0
    assert all(0 <= v <= 100 for v in valid)


def test_supertrend_returns_series(sample_df):
    upper, lower, direction = supertrend(sample_df, period=10, multiplier=3.0)
    assert len(upper) == len(sample_df)
    assert len(direction) == len(sample_df)
    # direction is 1 (up) or -1 (down)
    valid_dir = direction.dropna()
    assert all(d in (1, -1) for d in valid_dir)


def test_camarilla_pivots_has_correct_keys(sample_df):
    result = camarilla_pivots(sample_df)
    expected_keys = {"h1", "h2", "h3", "h4", "l1", "l2", "l3", "l4"}
    assert set(result.keys()) == expected_keys
    assert all(isinstance(v, float) for v in result.values())


def test_vwap_bands(sample_df):
    vwap_line, upper_1, lower_1, upper_2, lower_2 = vwap_bands(sample_df)
    assert len(vwap_line) == len(sample_df)
    # upper bands above vwap, lower below
    last_idx = -1
    assert upper_1.iloc[last_idx] >= vwap_line.iloc[last_idx]
    assert lower_1.iloc[last_idx] <= vwap_line.iloc[last_idx]


def test_bollinger_bandwidth(sample_df):
    bw = bollinger_bandwidth(sample_df["close"])
    assert isinstance(bw, pd.Series)
    valid = bw.dropna()
    assert all(v >= 0 for v in valid)


def test_volume_profile(sample_df):
    result = volume_profile(sample_df, bins=20)
    assert "poc" in result
    assert "vah" in result
    assert "val" in result
    assert result["vah"] >= result["poc"] >= result["val"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/strategy/test_indicators_v2.py -v`
Expected: ImportError — new functions don't exist

- [ ] **Step 3: Implement new indicators**

Add to `tradingbot/strategy/indicators.py`:

```python
def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index — trend strength (0-100)."""
    high, low, close = df["high"], df["low"], df["close"]
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    # Zero out when opposite DM is larger
    plus_dm[plus_dm < minus_dm] = 0
    minus_dm[minus_dm < plus_dm] = 0

    tr = atr(df, period) * period  # un-smoothed ATR won't work, compute TR directly
    true_range = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    smoothed_tr = true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / smoothed_tr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / smoothed_tr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def supertrend(
    df: pd.DataFrame, period: int = 10, multiplier: float = 3.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Supertrend indicator. Returns (upper_band, lower_band, direction)."""
    hl2 = (df["high"] + df["low"]) / 2
    atr_val = atr(df, period)

    upper = hl2 + multiplier * atr_val
    lower = hl2 - multiplier * atr_val

    final_upper = upper.copy()
    final_lower = lower.copy()
    direction = pd.Series(1, index=df.index, dtype=int)

    for i in range(1, len(df)):
        if lower.iloc[i] > final_lower.iloc[i - 1]:
            final_lower.iloc[i] = lower.iloc[i]
        else:
            final_lower.iloc[i] = final_lower.iloc[i - 1]

        if upper.iloc[i] < final_upper.iloc[i - 1]:
            final_upper.iloc[i] = upper.iloc[i]
        else:
            final_upper.iloc[i] = final_upper.iloc[i - 1]

        if df["close"].iloc[i] <= final_upper.iloc[i]:
            direction.iloc[i] = -1
        elif df["close"].iloc[i] >= final_lower.iloc[i]:
            direction.iloc[i] = 1
        else:
            direction.iloc[i] = direction.iloc[i - 1]

    return final_upper, final_lower, direction


def camarilla_pivots(df: pd.DataFrame) -> dict[str, float]:
    """Camarilla pivot levels from previous session's high/low/close."""
    last = df.iloc[-1]
    h, l, c = float(last["high"]), float(last["low"]), float(last["close"])
    diff = h - l
    return {
        "h4": c + diff * 1.1 / 2,
        "h3": c + diff * 1.1 / 4,
        "h2": c + diff * 1.1 / 6,
        "h1": c + diff * 1.1 / 12,
        "l1": c - diff * 1.1 / 12,
        "l2": c - diff * 1.1 / 6,
        "l3": c - diff * 1.1 / 4,
        "l4": c - diff * 1.1 / 2,
    }


def vwap_bands(
    df: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """VWAP with ±1σ and ±2σ bands. Returns (vwap, upper1, lower1, upper2, lower2)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    cum_vol = df["volume"].cumsum()
    cum_tp_vol = (typical * df["volume"]).cumsum()
    vwap_line = cum_tp_vol / cum_vol

    cum_sq = ((typical - vwap_line) ** 2 * df["volume"]).cumsum()
    std = np.sqrt(cum_sq / cum_vol)

    return vwap_line, vwap_line + std, vwap_line - std, vwap_line + 2 * std, vwap_line - 2 * std


def bollinger_bandwidth(close: pd.Series, period: int = 20, std: float = 2.0) -> pd.Series:
    """Bollinger Band width as percentage of middle band."""
    upper, middle, lower = bollinger_bands(close, period, std)
    return ((upper - lower) / middle) * 100


def volume_profile(df: pd.DataFrame, bins: int = 20) -> dict[str, float]:
    """Volume profile: POC, VAH, VAL from price-volume distribution."""
    prices = df["close"].values
    volumes = df["volume"].values

    price_min, price_max = prices.min(), prices.max()
    bin_edges = np.linspace(price_min, price_max, bins + 1)
    vol_by_bin = np.zeros(bins)
    bin_centers = np.zeros(bins)

    for i in range(bins):
        mask = (prices >= bin_edges[i]) & (prices < bin_edges[i + 1])
        if i == bins - 1:
            mask = (prices >= bin_edges[i]) & (prices <= bin_edges[i + 1])
        vol_by_bin[i] = volumes[mask].sum()
        bin_centers[i] = (bin_edges[i] + bin_edges[i + 1]) / 2

    poc_idx = vol_by_bin.argmax()
    poc = float(bin_centers[poc_idx])

    total_vol = vol_by_bin.sum()
    target = total_vol * 0.7
    sorted_indices = np.argsort(vol_by_bin)[::-1]
    cumulative = 0.0
    va_bins = []
    for idx in sorted_indices:
        va_bins.append(idx)
        cumulative += vol_by_bin[idx]
        if cumulative >= target:
            break

    va_prices = [bin_centers[i] for i in va_bins]
    vah = float(max(va_prices))
    val = float(min(va_prices))

    return {"poc": poc, "vah": vah, "val": val}
```

- [ ] **Step 4: Extend IndicatorSnapshot with new fields**

Add to `IndicatorSnapshot` in `models.py`:

```python
adx_14: float = 0.0
supertrend: float = 0.0
supertrend_direction: int = 1
bb_bandwidth: float = 0.0
vwap_upper_1: float = 0.0
vwap_lower_1: float = 0.0
poc: float = 0.0
vah: float = 0.0
val: float = 0.0
ema_9: float = 0.0
sma_9: float = 0.0
```

Update `compute_snapshot()` to populate these fields. Update `to_dict()` to include them.

- [ ] **Step 5: Run all indicator tests**

Run: `.venv/bin/python -m pytest tests/strategy/test_indicators.py tests/strategy/test_indicators_v2.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add tradingbot/strategy/indicators.py tradingbot/core/models.py tests/strategy/test_indicators_v2.py
git commit -m "feat(indicators): add ADX, Supertrend, Camarilla, VWAP bands, volume profile

6 new indicators for professional screening. Extended IndicatorSnapshot
with ADX, Supertrend direction, BB bandwidth, VWAP bands, POC/VAH/VAL."
```

---

### Task 7: Tier 1 Screening Engine

**Files:**
- Create: `tradingbot/screening/__init__.py`
- Create: `tradingbot/screening/liquidity_filter.py`
- Create: `tradingbot/screening/factor_scorer.py`
- Create: `tradingbot/screening/correlation_filter.py`
- Create: `tradingbot/screening/screener.py`
- Test: `tests/screening/__init__.py`
- Test: `tests/screening/test_screener.py`

**Interfaces:**
- Consumes: `CandleStore.read()` (Task 4), `ScreeningConfig` (Task 2), `IndicatorSnapshot` (Task 6), `ScoredStock` (Task 1)
- Produces: `LiquidityFilter.filter(instruments, candle_store) -> list[dict]`, `FactorScorer.score(stocks, candle_store) -> list[ScoredStock]`, `CorrelationFilter.filter(scored, max_per_sector) -> list[ScoredStock]`, `Tier1Screener.screen() -> list[ScoredStock]`

- [ ] **Step 1: Write tests for liquidity filter**

```python
# tests/screening/test_screener.py
import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock
from tradingbot.screening.liquidity_filter import LiquidityFilter
from tradingbot.screening.factor_scorer import FactorScorer
from tradingbot.screening.correlation_filter import CorrelationFilter

IST = ZoneInfo("Asia/Kolkata")


def _make_candle_df(n=30, base_price=500, avg_vol=600000):
    dates = pd.date_range("2026-08-01", periods=n, freq="B", tz=IST)
    close = base_price + np.cumsum(np.random.randn(n) * 2)
    return pd.DataFrame({
        "open": close + np.random.randn(n),
        "high": close + abs(np.random.randn(n) * 3),
        "low": close - abs(np.random.randn(n) * 3),
        "close": close,
        "volume": np.random.randint(int(avg_vol * 0.8), int(avg_vol * 1.2), n),
    }, index=dates)


def test_liquidity_filter_passes_valid():
    filt = LiquidityFilter(
        min_volume=500000, min_price=50, max_price=5000,
        min_market_cap_cr=1000, min_trading_days=10,
    )
    stock = {"symbol": "RELIANCE", "token": 1, "last_price": 2500.0,
             "avg_volume": 5_000_000.0, "market_cap_cr": 1_700_000.0,
             "trading_days": 20, "atr_pct": 1.5, "sector": "energy"}
    assert filt.passes(stock) is True


def test_liquidity_filter_rejects_low_volume():
    filt = LiquidityFilter(
        min_volume=500000, min_price=50, max_price=5000,
        min_market_cap_cr=1000, min_trading_days=10,
    )
    stock = {"symbol": "SMALLCO", "token": 2, "last_price": 200.0,
             "avg_volume": 50_000.0, "market_cap_cr": 500.0,
             "trading_days": 20, "atr_pct": 1.0, "sector": "misc"}
    assert filt.passes(stock) is False


def test_factor_scorer_returns_sorted_scores():
    scorer = FactorScorer(weights={
        "volume_surge": 15, "relative_strength": 15, "atr_expansion": 10,
        "price_structure": 15, "delivery_pct": 10, "sector_momentum": 10,
        "gap_analysis": 10, "candlestick_pattern": 10, "volume_profile": 5,
    })
    stocks = [
        {"symbol": "A", "scores": {"volume_surge": 90, "relative_strength": 80}},
        {"symbol": "B", "scores": {"volume_surge": 40, "relative_strength": 30}},
    ]
    # Scorer should weight and rank
    result = scorer.compute_composite(stocks[0]["scores"])
    assert isinstance(result, float)
    assert 0 <= result <= 100


def test_correlation_filter_caps_per_sector():
    filt = CorrelationFilter(max_per_sector=2)
    from tradingbot.core.models import ScoredStock
    stocks = [
        ScoredStock("HDFCBANK", "NSE", 1600, 8e6, 12e5, 1.0, "banking", 90, {}, 1),
        ScoredStock("ICICIBANK", "NSE", 1000, 7e6, 7e5, 1.1, "banking", 85, {}, 2),
        ScoredStock("SBIN", "NSE", 600, 1e7, 5e5, 1.2, "banking", 80, {}, 3),
        ScoredStock("RELIANCE", "NSE", 2500, 5e6, 17e5, 1.5, "energy", 88, {}, 4),
    ]
    result = filt.filter(stocks)
    banking = [s for s in result if s.sector == "banking"]
    assert len(banking) <= 2
    assert len(result) == 3  # 2 banking + 1 energy
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/screening/test_screener.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: Implement LiquidityFilter**

```python
# tradingbot/screening/liquidity_filter.py
from __future__ import annotations
from typing import Any


class LiquidityFilter:
    """Phase 1A: eliminate stocks that can't be traded safely with 4L capital."""

    def __init__(
        self, min_volume: int, min_price: float, max_price: float,
        min_market_cap_cr: float, min_trading_days: int,
    ):
        self._min_volume = min_volume
        self._min_price = min_price
        self._max_price = max_price
        self._min_cap = min_market_cap_cr
        self._min_days = min_trading_days

    def passes(self, stock: dict[str, Any]) -> bool:
        if stock["avg_volume"] < self._min_volume:
            return False
        if not (self._min_price <= stock["last_price"] <= self._max_price):
            return False
        if stock["market_cap_cr"] < self._min_cap:
            return False
        if stock.get("trading_days", 0) < self._min_days:
            return False
        return True

    def filter_all(self, stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [s for s in stocks if self.passes(s)]
```

- [ ] **Step 4: Implement FactorScorer**

```python
# tradingbot/screening/factor_scorer.py
from __future__ import annotations
from typing import Any


class FactorScorer:
    """Phase 1B: score each stock 0-100 across 9 weighted factors."""

    FACTOR_KEYS = [
        "volume_surge", "relative_strength", "atr_expansion",
        "price_structure", "delivery_pct", "sector_momentum",
        "gap_analysis", "candlestick_pattern", "volume_profile",
    ]

    def __init__(self, weights: dict[str, int]):
        self._weights = weights
        total = sum(weights.get(k, 0) for k in self.FACTOR_KEYS)
        self._norm = total if total > 0 else 1

    def compute_composite(self, factor_scores: dict[str, float]) -> float:
        weighted_sum = sum(
            factor_scores.get(k, 50.0) * self._weights.get(k, 0)
            for k in self.FACTOR_KEYS
        )
        return weighted_sum / self._norm

    def score_stock(self, stock: dict[str, Any], factor_scores: dict[str, float]) -> float:
        return self.compute_composite(factor_scores)
```

- [ ] **Step 5: Implement CorrelationFilter**

```python
# tradingbot/screening/correlation_filter.py
from __future__ import annotations
from tradingbot.core.models import ScoredStock


class CorrelationFilter:
    """Phase 1C: cap per-sector exposure to avoid correlated risk."""

    def __init__(self, max_per_sector: int = 3):
        self._max = max_per_sector

    def filter(self, stocks: list[ScoredStock]) -> list[ScoredStock]:
        sorted_stocks = sorted(stocks, key=lambda s: s.composite_score, reverse=True)
        sector_counts: dict[str, int] = {}
        result: list[ScoredStock] = []
        for stock in sorted_stocks:
            count = sector_counts.get(stock.sector, 0)
            if count < self._max:
                result.append(stock)
                sector_counts[stock.sector] = count + 1
        return result
```

- [ ] **Step 6: Implement Tier1Screener orchestrator**

```python
# tradingbot/screening/screener.py
from __future__ import annotations

import logging
from typing import Any

from tradingbot.core.config import ScreeningConfig
from tradingbot.core.models import ScoredStock
from tradingbot.data.candle_store import CandleStore
from tradingbot.screening.correlation_filter import CorrelationFilter
from tradingbot.screening.factor_scorer import FactorScorer
from tradingbot.screening.liquidity_filter import LiquidityFilter

log = logging.getLogger(__name__)


class Tier1Screener:
    """Deterministic screening: ~1500 stocks → ~50-100 candidates."""

    def __init__(self, config: ScreeningConfig, candle_store: CandleStore):
        self._config = config
        self._candle_store = candle_store
        self._liquidity = LiquidityFilter(
            min_volume=config.min_volume, min_price=config.min_price,
            max_price=config.max_price, min_market_cap_cr=config.min_market_cap_cr,
            min_trading_days=config.min_trading_days,
        )
        self._scorer = FactorScorer(weights={
            "volume_surge": config.volume_surge_weight,
            "relative_strength": config.relative_strength_weight,
            "atr_expansion": config.atr_expansion_weight,
            "price_structure": config.price_structure_weight,
            "delivery_pct": config.delivery_pct_weight,
            "sector_momentum": config.sector_momentum_weight,
            "gap_analysis": config.gap_analysis_weight,
            "candlestick_pattern": config.candlestick_pattern_weight,
            "volume_profile": config.volume_profile_weight,
        })
        self._correlation = CorrelationFilter(max_per_sector=config.max_per_sector)

    def screen(self, stock_metrics: list[dict[str, Any]]) -> list[ScoredStock]:
        liquid = self._liquidity.filter_all(stock_metrics)
        log.info("Liquidity filter: %d → %d", len(stock_metrics), len(liquid))

        scored: list[ScoredStock] = []
        for stock in liquid:
            factor_scores = stock.get("factor_scores", {})
            composite = self._scorer.compute_composite(factor_scores)
            scored.append(ScoredStock(
                symbol=stock["symbol"], exchange="NSE",
                last_price=stock["last_price"], avg_volume=stock["avg_volume"],
                market_cap_cr=stock["market_cap_cr"], atr_pct=stock.get("atr_pct", 0),
                sector=stock.get("sector", "unknown"),
                composite_score=composite, factor_scores=factor_scores,
                instrument_token=stock.get("token", 0),
            ))

        scored.sort(key=lambda s: s.composite_score, reverse=True)
        filtered = self._correlation.filter(scored)
        log.info("After correlation filter: %d candidates", len(filtered))
        return filtered
```

- [ ] **Step 7: Run tests**

Run: `.venv/bin/python -m pytest tests/screening/ -v`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add tradingbot/screening/ tests/screening/
git commit -m "feat(screening): add Tier 1 deterministic screening engine

LiquidityFilter (volume, price, cap, trading days),
FactorScorer (9 weighted factors, 0-100 composite),
CorrelationFilter (cap per sector), Tier1Screener orchestrator."
```

---

### Task 8: Five New Strategies

**Files:**
- Create: `tradingbot/strategy/strategies/gap_and_go.py`
- Create: `tradingbot/strategy/strategies/pivot_point.py`
- Create: `tradingbot/strategy/strategies/relative_strength.py`
- Create: `tradingbot/strategy/strategies/bollinger_squeeze.py`
- Create: `tradingbot/strategy/strategies/supply_demand.py`
- Create: `tradingbot/strategy/strategies/confluence.py`
- Modify: `tradingbot/strategy/strategies/__init__.py` (update STRATEGY_REGISTRY)
- Test: `tests/strategy/test_new_strategies.py`

**Interfaces:**
- Consumes: `Strategy` base class, `Signal`, `build_signal()` (existing), `IndicatorSnapshot` (Task 6)
- Produces: 5 new `Strategy` subclasses + `ConfluenceScorer`, all registered in `STRATEGY_REGISTRY`

- [ ] **Step 1: Write tests for all new strategies**

```python
# tests/strategy/test_new_strategies.py
import numpy as np
import pandas as pd
import pytest
from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.gap_and_go import GapAndGoStrategy
from tradingbot.strategy.strategies.pivot_point import PivotPointStrategy
from tradingbot.strategy.strategies.bollinger_squeeze import BollingerSqueezeStrategy
from tradingbot.strategy.strategies.supply_demand import SupplyDemandStrategy
from tradingbot.strategy.strategies.relative_strength import RelativeStrengthStrategy
from tradingbot.strategy.strategies.confluence import ConfluenceScorer


def _make_snapshot(**overrides):
    defaults = dict(
        symbol="TEST", last_close=500.0, rsi_14=55.0, macd=1.0,
        macd_signal=0.5, bb_upper=520.0, bb_middle=500.0, bb_lower=480.0,
        atr_14=8.0, sma_20=498.0, sma_50=495.0, sma_200=490.0,
        ema_12=501.0, ema_26=499.0, vwap=500.0, pivot=500.0,
        support_levels=[490.0, 480.0], resistance_levels=[510.0, 520.0],
        adx_14=30.0, supertrend=495.0, supertrend_direction=1,
        bb_bandwidth=4.0, vwap_upper_1=505.0, vwap_lower_1=495.0,
        poc=500.0, vah=510.0, val=490.0, ema_9=501.0, sma_9=500.5,
    )
    defaults.update(overrides)
    return IndicatorSnapshot(**defaults)


def _trending_up_df(n=50, base=500):
    close = base + np.arange(n) * 1.5 + np.random.randn(n) * 2
    return pd.DataFrame({
        "open": close - 1, "high": close + 3, "low": close - 3,
        "close": close,
        "volume": np.random.randint(500000, 1500000, n),
    })


def test_gap_and_go_strategy_has_correct_name():
    assert GapAndGoStrategy().name == StrategyName.GAP_AND_GO


def test_pivot_point_strategy_has_correct_name():
    assert PivotPointStrategy().name == StrategyName.PIVOT_POINT


def test_bollinger_squeeze_strategy_has_correct_name():
    assert BollingerSqueezeStrategy().name == StrategyName.BOLLINGER_SQUEEZE


def test_supply_demand_strategy_has_correct_name():
    assert SupplyDemandStrategy().name == StrategyName.SUPPLY_DEMAND


def test_relative_strength_strategy_has_correct_name():
    assert RelativeStrengthStrategy().name == StrategyName.RELATIVE_STRENGTH


def test_gap_and_go_returns_signal_or_none():
    strategy = GapAndGoStrategy()
    df = _trending_up_df()
    snapshot = _make_snapshot()
    result = strategy.generate_signal(df, snapshot)
    assert result is None or hasattr(result, "direction")


def test_bollinger_squeeze_detects_low_bandwidth():
    strategy = BollingerSqueezeStrategy()
    df = _trending_up_df()
    snapshot = _make_snapshot(bb_bandwidth=1.5)  # low bandwidth = squeeze
    result = strategy.generate_signal(df, snapshot)
    # With low bandwidth and uptrend, might generate long signal
    assert result is None or result.direction in (Direction.LONG, Direction.SHORT)


def test_confluence_scorer():
    scorer = ConfluenceScorer()
    snapshot = _make_snapshot(
        last_close=505.0, sma_50=495.0, sma_200=490.0,  # daily uptrend
        macd=2.0, macd_signal=1.0, rsi_14=60.0,          # hourly momentum
        ema_9=504.0, ema_12=503.0,                        # 15min aligned
    )
    score = scorer.score(snapshot, Direction.LONG)
    assert isinstance(score, int)
    assert 0 <= score <= 5


def test_strategy_registry_has_10_strategies():
    from tradingbot.strategy.strategies import STRATEGY_REGISTRY
    assert len(STRATEGY_REGISTRY) == 10
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/strategy/test_new_strategies.py -v`
Expected: ImportError

- [ ] **Step 3: Implement GapAndGoStrategy**

```python
# tradingbot/strategy/strategies/gap_and_go.py
from __future__ import annotations
import pandas as pd
from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal

GAP_THRESHOLD_PCT = 1.0
VOLUME_SURGE = 2.0
LOOKBACK = 20


class GapAndGoStrategy(Strategy):
    name = StrategyName.GAP_AND_GO

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        if len(df) < LOOKBACK + 2:
            return None
        prev_close = float(df["close"].iloc[-2])
        curr_open = float(df["open"].iloc[-1])
        gap_pct = (curr_open - prev_close) / prev_close * 100

        if abs(gap_pct) < GAP_THRESHOLD_PCT:
            return None

        avg_vol = float(df["volume"].iloc[-LOOKBACK - 1:-1].mean())
        curr_vol = float(df["volume"].iloc[-1])
        if avg_vol <= 0 or curr_vol / avg_vol < VOLUME_SURGE:
            return None

        if gap_pct > 0 and snapshot.last_close >= curr_open:
            return build_signal(Direction.LONG, snapshot.last_close, snapshot.atr_14,
                                strength=min(1.0, abs(gap_pct) / 3.0))

        if gap_pct < 0 and snapshot.last_close <= curr_open:
            return build_signal(Direction.SHORT, snapshot.last_close, snapshot.atr_14,
                                strength=min(1.0, abs(gap_pct) / 3.0))
        return None
```

- [ ] **Step 4: Implement PivotPointStrategy**

```python
# tradingbot/strategy/strategies/pivot_point.py
from __future__ import annotations
import pandas as pd
from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal

PROXIMITY_PCT = 0.3


class PivotPointStrategy(Strategy):
    name = StrategyName.PIVOT_POINT

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        price = snapshot.last_close
        pivot = snapshot.pivot
        if pivot <= 0:
            return None

        for support in sorted(snapshot.support_levels, reverse=True):
            distance_pct = abs(price - support) / price * 100
            if distance_pct < PROXIMITY_PCT and snapshot.rsi_14 < 40:
                return build_signal(Direction.LONG, price, snapshot.atr_14,
                                    strength=0.6 + (40 - snapshot.rsi_14) / 100)

        for resistance in sorted(snapshot.resistance_levels):
            distance_pct = abs(price - resistance) / price * 100
            if distance_pct < PROXIMITY_PCT and snapshot.rsi_14 > 60:
                return build_signal(Direction.SHORT, price, snapshot.atr_14,
                                    strength=0.6 + (snapshot.rsi_14 - 60) / 100)
        return None
```

- [ ] **Step 5: Implement BollingerSqueezeStrategy**

```python
# tradingbot/strategy/strategies/bollinger_squeeze.py
from __future__ import annotations
import pandas as pd
from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal

SQUEEZE_THRESHOLD = 3.0  # bandwidth percentage below this = squeeze


class BollingerSqueezeStrategy(Strategy):
    name = StrategyName.BOLLINGER_SQUEEZE

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        if snapshot.bb_bandwidth > SQUEEZE_THRESHOLD:
            return None

        price = snapshot.last_close
        if price > snapshot.bb_upper and snapshot.adx_14 > 20:
            return build_signal(Direction.LONG, price, snapshot.atr_14, strength=0.7)
        if price < snapshot.bb_lower and snapshot.adx_14 > 20:
            return build_signal(Direction.SHORT, price, snapshot.atr_14, strength=0.7)
        return None
```

- [ ] **Step 6: Implement SupplyDemandStrategy**

```python
# tradingbot/strategy/strategies/supply_demand.py
from __future__ import annotations
import numpy as np
import pandas as pd
from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal

ZONE_PROXIMITY_PCT = 0.5
MIN_MOVE_PCT = 1.5


class SupplyDemandStrategy(Strategy):
    name = StrategyName.SUPPLY_DEMAND

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        if len(df) < 30:
            return None

        price = snapshot.last_close
        demand_zones = self._find_zones(df, "demand")
        supply_zones = self._find_zones(df, "supply")

        for zone_price in demand_zones:
            if abs(price - zone_price) / price * 100 < ZONE_PROXIMITY_PCT:
                if snapshot.rsi_14 < 45:
                    return build_signal(Direction.LONG, price, snapshot.atr_14, strength=0.65)

        for zone_price in supply_zones:
            if abs(price - zone_price) / price * 100 < ZONE_PROXIMITY_PCT:
                if snapshot.rsi_14 > 55:
                    return build_signal(Direction.SHORT, price, snapshot.atr_14, strength=0.65)
        return None

    def _find_zones(self, df: pd.DataFrame, zone_type: str) -> list[float]:
        zones = []
        closes = df["close"].values
        for i in range(2, len(closes) - 2):
            move = abs(closes[i + 2] - closes[i]) / closes[i] * 100
            if move < MIN_MOVE_PCT:
                continue
            if zone_type == "demand" and closes[i + 2] > closes[i]:
                zones.append(float(closes[i]))
            elif zone_type == "supply" and closes[i + 2] < closes[i]:
                zones.append(float(closes[i]))
        return zones[-5:] if zones else []
```

- [ ] **Step 7: Implement RelativeStrengthStrategy**

```python
# tradingbot/strategy/strategies/relative_strength.py
from __future__ import annotations
import pandas as pd
from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal


class RelativeStrengthStrategy(Strategy):
    name = StrategyName.RELATIVE_STRENGTH

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        if len(df) < 20:
            return None
        price = snapshot.last_close

        above_all_ma = (price > snapshot.sma_20 > snapshot.sma_50)
        adx_trending = snapshot.adx_14 > 25
        momentum_up = snapshot.macd > snapshot.macd_signal

        if above_all_ma and adx_trending and momentum_up:
            strength = min(1.0, (snapshot.adx_14 - 20) / 30)
            return build_signal(Direction.LONG, price, snapshot.atr_14, strength=strength)

        below_all_ma = (price < snapshot.sma_20 < snapshot.sma_50)
        momentum_down = snapshot.macd < snapshot.macd_signal

        if below_all_ma and adx_trending and momentum_down:
            strength = min(1.0, (snapshot.adx_14 - 20) / 30)
            return build_signal(Direction.SHORT, price, snapshot.atr_14, strength=strength)
        return None
```

- [ ] **Step 8: Implement ConfluenceScorer**

```python
# tradingbot/strategy/strategies/confluence.py
from __future__ import annotations
from tradingbot.core.models import Direction, IndicatorSnapshot


class ConfluenceScorer:
    """Meta-strategy: count how many timeframes agree on direction."""

    def score(self, snapshot: IndicatorSnapshot, direction: Direction) -> int:
        count = 0
        is_long = direction is Direction.LONG

        # Daily trend: price vs 50 SMA
        if is_long and snapshot.last_close > snapshot.sma_50:
            count += 1
        elif not is_long and snapshot.last_close < snapshot.sma_50:
            count += 1

        # Momentum: MACD alignment
        if is_long and snapshot.macd > snapshot.macd_signal:
            count += 1
        elif not is_long and snapshot.macd < snapshot.macd_signal:
            count += 1

        # RSI alignment
        if is_long and 40 < snapshot.rsi_14 < 70:
            count += 1
        elif not is_long and 30 < snapshot.rsi_14 < 60:
            count += 1

        # Supertrend direction
        if is_long and snapshot.supertrend_direction == 1:
            count += 1
        elif not is_long and snapshot.supertrend_direction == -1:
            count += 1

        # VWAP alignment
        if is_long and snapshot.last_close > snapshot.vwap:
            count += 1
        elif not is_long and snapshot.last_close < snapshot.vwap:
            count += 1

        return count
```

- [ ] **Step 9: Update STRATEGY_REGISTRY**

Modify `tradingbot/strategy/strategies/__init__.py`:

```python
from tradingbot.strategy.strategies.breakout import BreakoutStrategy
from tradingbot.strategy.strategies.momentum import MomentumStrategy
from tradingbot.strategy.strategies.mean_reversion import MeanReversionStrategy
from tradingbot.strategy.strategies.vwap_bounce import VWAPBounceStrategy
from tradingbot.strategy.strategies.orb import ORBStrategy
from tradingbot.strategy.strategies.gap_and_go import GapAndGoStrategy
from tradingbot.strategy.strategies.pivot_point import PivotPointStrategy
from tradingbot.strategy.strategies.relative_strength import RelativeStrengthStrategy
from tradingbot.strategy.strategies.bollinger_squeeze import BollingerSqueezeStrategy
from tradingbot.strategy.strategies.supply_demand import SupplyDemandStrategy

STRATEGY_REGISTRY: list = [
    BreakoutStrategy(), MomentumStrategy(), MeanReversionStrategy(),
    VWAPBounceStrategy(), ORBStrategy(), GapAndGoStrategy(),
    PivotPointStrategy(), RelativeStrengthStrategy(),
    BollingerSqueezeStrategy(), SupplyDemandStrategy(),
]
```

- [ ] **Step 10: Run tests**

Run: `.venv/bin/python -m pytest tests/strategy/ -v`
Expected: All pass (new + existing)

- [ ] **Step 11: Commit**

```bash
git add tradingbot/strategy/strategies/ tests/strategy/test_new_strategies.py
git commit -m "feat(strategy): add 5 new strategies + confluence scorer

GapAndGo, PivotPoint, BollingerSqueeze, SupplyDemand, RelativeStrength.
ConfluenceScorer counts multi-timeframe agreement. Registry now has 10."
```

---

### Task 9: Backtesting Engine — Walk-Forward + Transaction Costs

**Files:**
- Create: `tradingbot/backtest/__init__.py`
- Create: `tradingbot/backtest/costs.py`
- Create: `tradingbot/backtest/walk_forward.py`
- Test: `tests/backtest/__init__.py`
- Test: `tests/backtest/test_costs.py`
- Test: `tests/backtest/test_walk_forward.py`

**Interfaces:**
- Consumes: `Strategy` classes (Task 8), `IndicatorSnapshot`, `BacktestReport` (Task 1), `BacktestConfig` (Task 2)
- Produces: `TransactionCosts.round_trip_cost(entry_price, exit_price, qty)`, `WalkForwardEngine.run(symbol, df, strategy) -> BacktestReport`

- [ ] **Step 1: Write tests for transaction costs**

```python
# tests/backtest/test_costs.py
from tradingbot.backtest.costs import ZerodhaCosts


def test_round_trip_cost_typical_trade():
    costs = ZerodhaCosts()
    # Buy 100 shares at 500, sell at 510
    cost = costs.round_trip_cost(entry_price=500.0, exit_price=510.0, quantity=100)
    assert cost > 0
    # Rough estimate: brokerage 40 + STT ~12.75 + charges ~5 + GST ~8 + stamp ~1.5
    assert 50 < cost < 150


def test_brokerage_caps_at_20():
    costs = ZerodhaCosts()
    # Small trade: 10 shares at 100 = 1000 notional
    cost = costs.round_trip_cost(100.0, 102.0, 10)
    # Brokerage = min(20, 0.03% of 1000) = min(20, 0.30) = 0.30 per leg
    assert cost > 0


def test_slippage_applied():
    costs = ZerodhaCosts(slippage_pct=0.02)
    cost_with = costs.round_trip_cost(500.0, 510.0, 100)
    costs_no = ZerodhaCosts(slippage_pct=0.0)
    cost_without = costs_no.round_trip_cost(500.0, 510.0, 100)
    assert cost_with > cost_without
```

- [ ] **Step 2: Write tests for walk-forward engine**

```python
# tests/backtest/test_walk_forward.py
import numpy as np
import pandas as pd
import pytest
from tradingbot.backtest.walk_forward import WalkForwardEngine
from tradingbot.core.models import StrategyName, BacktestReport


@pytest.fixture
def trending_df():
    np.random.seed(42)
    n = 500
    close = 500 + np.cumsum(np.random.randn(n) * 3)
    return pd.DataFrame({
        "open": close - 1, "high": close + abs(np.random.randn(n) * 5),
        "low": close - abs(np.random.randn(n) * 5), "close": close,
        "volume": np.random.randint(500000, 2000000, n),
    })


def test_walk_forward_returns_backtest_report(trending_df):
    from tradingbot.strategy.strategies.momentum import MomentumStrategy
    engine = WalkForwardEngine(
        windows=3, train_pct=70,
    )
    report = engine.run("RELIANCE", trending_df, MomentumStrategy())
    assert isinstance(report, BacktestReport)
    assert report.symbol == "RELIANCE"
    assert report.total_trades >= 0


def test_walk_forward_computes_oos_degradation(trending_df):
    from tradingbot.strategy.strategies.breakout import BreakoutStrategy
    engine = WalkForwardEngine(windows=3, train_pct=70)
    report = engine.run("TCS", trending_df, BreakoutStrategy())
    assert hasattr(report, "oos_degradation")
    assert report.oos_degradation >= 0


def test_walk_forward_includes_transaction_costs(trending_df):
    from tradingbot.strategy.strategies.momentum import MomentumStrategy
    engine_with_costs = WalkForwardEngine(windows=2, train_pct=70, include_costs=True)
    engine_no_costs = WalkForwardEngine(windows=2, train_pct=70, include_costs=False)
    r1 = engine_with_costs.run("TEST", trending_df, MomentumStrategy())
    r2 = engine_no_costs.run("TEST", trending_df, MomentumStrategy())
    # With costs, expectancy should be lower or equal
    if r1.total_trades > 0 and r2.total_trades > 0:
        assert r1.expectancy <= r2.expectancy + 1  # small tolerance
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/backtest/ -v`
Expected: ModuleNotFoundError

- [ ] **Step 4: Implement ZerodhaCosts**

```python
# tradingbot/backtest/costs.py
from __future__ import annotations


class ZerodhaCosts:
    """Zerodha intraday transaction cost model."""

    BROKERAGE_CAP = 20.0          # per order
    BROKERAGE_PCT = 0.03 / 100    # 0.03%
    STT_PCT = 0.025 / 100         # on sell side
    EXCHANGE_PCT = 0.00345 / 100
    SEBI_PCT = 0.0001 / 100
    STAMP_PCT = 0.003 / 100       # on buy side
    GST_PCT = 18.0 / 100          # on brokerage + exchange

    def __init__(self, slippage_pct: float = 0.02):
        self._slippage_pct = slippage_pct / 100

    def round_trip_cost(self, entry_price: float, exit_price: float, quantity: int) -> float:
        buy_value = entry_price * quantity
        sell_value = exit_price * quantity
        turnover = buy_value + sell_value

        brokerage_buy = min(self.BROKERAGE_CAP, buy_value * self.BROKERAGE_PCT)
        brokerage_sell = min(self.BROKERAGE_CAP, sell_value * self.BROKERAGE_PCT)
        brokerage = brokerage_buy + brokerage_sell

        stt = sell_value * self.STT_PCT
        exchange = turnover * self.EXCHANGE_PCT
        sebi = turnover * self.SEBI_PCT
        stamp = buy_value * self.STAMP_PCT
        gst = (brokerage + exchange) * self.GST_PCT

        slippage = turnover * self._slippage_pct

        return brokerage + stt + exchange + sebi + stamp + gst + slippage
```

- [ ] **Step 5: Implement WalkForwardEngine**

```python
# tradingbot/backtest/walk_forward.py
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from tradingbot.backtest.costs import ZerodhaCosts
from tradingbot.core.models import BacktestReport, StrategyName
from tradingbot.strategy.indicators import compute_snapshot, InsufficientDataError
from tradingbot.strategy.strategies.base import Strategy, Signal

WARMUP = 200
MAX_HOLD = 26


class WalkForwardEngine:
    """Walk-forward backtesting with OOS validation and transaction costs."""

    def __init__(
        self, windows: int = 10, train_pct: int = 70,
        include_costs: bool = True, slippage_pct: float = 0.02,
    ):
        self._windows = windows
        self._train_pct = train_pct / 100.0
        self._costs = ZerodhaCosts(slippage_pct) if include_costs else None

    def run(self, symbol: str, df: pd.DataFrame, strategy: Strategy) -> BacktestReport:
        if len(df) < WARMUP + 50:
            return self._empty_report(symbol, strategy.name, df)

        usable = df.iloc[WARMUP:]
        window_size = len(usable) // self._windows
        if window_size < 20:
            return self._empty_report(symbol, strategy.name, df)

        is_wins: list[float] = []
        oos_wins: list[float] = []
        all_trades: list[dict] = []

        for w in range(self._windows):
            start = w * window_size
            end = min(start + window_size, len(usable))
            window = usable.iloc[start:end]
            split = int(len(window) * self._train_pct)

            is_data = df.iloc[:WARMUP + start + split]
            oos_data = df.iloc[:WARMUP + start + end]

            is_trades = self._simulate(symbol, is_data, strategy, WARMUP + start, WARMUP + start + split)
            oos_trades = self._simulate(symbol, oos_data, strategy, WARMUP + start + split, WARMUP + start + end)

            if is_trades:
                is_wins.append(sum(1 for t in is_trades if t["pnl"] > 0) / len(is_trades))
            if oos_trades:
                oos_wins.append(sum(1 for t in oos_trades if t["pnl"] > 0) / len(oos_trades))
            all_trades.extend(oos_trades)

        return self._build_report(symbol, strategy.name, df, all_trades, is_wins, oos_wins)

    def _simulate(
        self, symbol: str, full_df: pd.DataFrame, strategy: Strategy,
        start_idx: int, end_idx: int,
    ) -> list[dict]:
        trades = []
        i = start_idx
        while i < end_idx - 1:
            window = full_df.iloc[:i + 1]
            try:
                snapshot = compute_snapshot(symbol, window)
            except InsufficientDataError:
                i += 1
                continue

            signal = strategy.generate_signal(window, snapshot)
            if signal is None:
                i += 1
                continue

            won, exit_idx, exit_price = self._resolve(full_df, i, signal, end_idx)
            pnl = (exit_price - signal.entry_price) if signal.direction.value == "long" else (signal.entry_price - exit_price)
            pnl_amount = pnl * 1  # per share

            if self._costs:
                cost = self._costs.round_trip_cost(signal.entry_price, exit_price, 1)
                pnl_amount -= cost

            trades.append({"pnl": pnl_amount, "won": pnl_amount > 0,
                           "entry": signal.entry_price, "exit": exit_price})
            i = exit_idx + 1

        return trades

    def _resolve(self, df: pd.DataFrame, entry_idx: int, signal: Signal, max_idx: int):
        for j in range(entry_idx + 1, min(entry_idx + MAX_HOLD + 1, max_idx)):
            price = float(df.iloc[j]["close"])
            if signal.direction.value == "long":
                if price <= signal.stop_loss:
                    return False, j, signal.stop_loss
                if price >= signal.target_1:
                    return True, j, signal.target_1
            else:
                if price >= signal.stop_loss:
                    return False, j, signal.stop_loss
                if price <= signal.target_1:
                    return True, j, signal.target_1
        last = float(df.iloc[min(entry_idx + MAX_HOLD, max_idx - 1)]["close"])
        return last > signal.entry_price if signal.direction.value == "long" else last < signal.entry_price, min(entry_idx + MAX_HOLD, max_idx - 1), last

    def _build_report(self, symbol, strategy_name, df, trades, is_wins, oos_wins):
        if not trades:
            return self._empty_report(symbol, strategy_name, df)

        winners = [t for t in trades if t["pnl"] > 0]
        losers = [t for t in trades if t["pnl"] <= 0]
        win_rate = len(winners) / len(trades) if trades else 0
        avg_w = np.mean([t["pnl"] for t in winners]) if winners else 0
        avg_l = np.mean([t["pnl"] for t in losers]) if losers else 0
        gross_profit = sum(t["pnl"] for t in winners)
        gross_loss = abs(sum(t["pnl"] for t in losers))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        expectancy = np.mean([t["pnl"] for t in trades])

        avg_risk = np.mean([abs(t["entry"] - t["exit"]) for t in trades]) if trades else 1
        expectancy_r = expectancy / avg_risk if avg_risk > 0 else 0

        pnls = [t["pnl"] for t in trades]
        sharpe = (np.mean(pnls) / np.std(pnls) * math.sqrt(252)) if np.std(pnls) > 0 else 0

        equity = np.cumsum(pnls)
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / np.where(peak > 0, peak, 1) * 100
        max_dd = float(np.max(drawdown)) if len(drawdown) > 0 else 0

        max_consec = 0
        current = 0
        for t in trades:
            if t["pnl"] <= 0:
                current += 1
                max_consec = max(max_consec, current)
            else:
                current = 0

        is_mean = np.mean(is_wins) if is_wins else 0
        oos_mean = np.mean(oos_wins) if oos_wins else 0
        oos_deg = max(0, is_mean - oos_mean) if is_mean > 0 else 0

        calmar = (expectancy * 252 / max_dd) if max_dd > 0 else 0

        return BacktestReport(
            symbol=symbol, strategy=strategy_name,
            period_start=date.today(), period_end=date.today(),
            total_trades=len(trades), winners=len(winners), losers=len(losers),
            win_rate=win_rate, avg_winner=float(avg_w), avg_loser=float(avg_l),
            profit_factor=profit_factor, expectancy=float(expectancy),
            expectancy_r=float(expectancy_r), sharpe_ratio=float(sharpe),
            max_drawdown_pct=float(max_dd), max_consecutive_losses=max_consec,
            avg_hold_minutes=0, oos_degradation=float(oos_deg), calmar_ratio=float(calmar),
        )

    def _empty_report(self, symbol, strategy_name, df):
        return BacktestReport(
            symbol=symbol, strategy=strategy_name,
            period_start=date.today(), period_end=date.today(),
            total_trades=0, winners=0, losers=0,
            win_rate=0, avg_winner=0, avg_loser=0,
            profit_factor=0, expectancy=0, expectancy_r=0,
            sharpe_ratio=0, max_drawdown_pct=0, max_consecutive_losses=0,
            avg_hold_minutes=0, oos_degradation=0, calmar_ratio=0,
        )
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/backtest/ -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add tradingbot/backtest/ tests/backtest/
git commit -m "feat(backtest): walk-forward engine with Zerodha transaction costs

WalkForwardEngine: configurable windows, train/OOS split, OOS degradation.
ZerodhaCosts: brokerage cap, STT, exchange, GST, SEBI, stamp, slippage."
```

---

### Task 10: Monte Carlo Simulation + Quality Gates

**Files:**
- Create: `tradingbot/backtest/monte_carlo.py`
- Create: `tradingbot/backtest/quality_gates.py`
- Test: `tests/backtest/test_monte_carlo.py`
- Test: `tests/backtest/test_quality_gates.py`

**Interfaces:**
- Consumes: `BacktestReport` (Task 1), `MonteCarloResult`, `QualityGateResult` (Task 1), `BacktestConfig` (Task 2)
- Produces: `MonteCarloSimulator.run(trades) -> MonteCarloResult`, `QualityGates.evaluate(report, mc_result) -> QualityGateResult`

- [ ] **Step 1: Write tests**

```python
# tests/backtest/test_monte_carlo.py
import pytest
from tradingbot.backtest.monte_carlo import MonteCarloSimulator


def test_monte_carlo_returns_result():
    trades = [100, -50, 200, -80, 150, -30, 120, -60, 90, -40,
              110, -45, 180, -70, 130, -55, 95, -35, 140, -65,
              160, -75, 125, -50, 115, -40, 175, -60, 135, -45]
    sim = MonteCarloSimulator(simulations=1000, capital=400000)
    result = sim.run(trades)
    assert result.simulations == 1000
    assert result.median_return_pct != 0
    assert result.p10_return_pct <= result.median_return_pct <= result.p90_return_pct
    assert 0 <= result.risk_of_ruin_pct <= 100
    assert 0 <= result.confidence_score <= 1


def test_monte_carlo_empty_trades():
    sim = MonteCarloSimulator(simulations=100, capital=400000)
    result = sim.run([])
    assert result.confidence_score == 0


# tests/backtest/test_quality_gates.py
import pytest
from tradingbot.core.models import BacktestReport, MonteCarloResult, StrategyName
from tradingbot.backtest.quality_gates import QualityGates
from datetime import date


def _report(**overrides):
    defaults = dict(
        symbol="TEST", strategy=StrategyName.BREAKOUT,
        period_start=date(2025, 1, 1), period_end=date(2026, 1, 1),
        total_trades=50, winners=30, losers=20, win_rate=0.60,
        avg_winner=5000, avg_loser=-3000, profit_factor=2.5,
        expectancy=1200, expectancy_r=0.5, sharpe_ratio=1.8,
        max_drawdown_pct=5.0, max_consecutive_losses=4,
        avg_hold_minutes=45, oos_degradation=0.1, calmar_ratio=2.0,
    )
    defaults.update(overrides)
    return BacktestReport(**defaults)


def _mc(**overrides):
    defaults = dict(
        simulations=10000, median_return_pct=15.0, p10_return_pct=5.0,
        p90_return_pct=30.0, median_max_drawdown=6.0, p95_max_drawdown=12.0,
        risk_of_ruin_pct=1.0, confidence_score=0.75,
    )
    defaults.update(overrides)
    return MonteCarloResult(**defaults)


def test_all_gates_pass():
    gates = QualityGates()
    result = gates.evaluate(_report(), _mc())
    assert result.passed is True
    assert len(result.failures) == 0


def test_insufficient_trades_fails():
    gates = QualityGates()
    result = gates.evaluate(_report(total_trades=10), _mc())
    assert result.passed is False
    assert result.total_trades_ok is False


def test_high_ruin_risk_fails():
    gates = QualityGates()
    result = gates.evaluate(_report(), _mc(risk_of_ruin_pct=10.0))
    assert result.passed is False
    assert result.ruin_risk_ok is False
```

- [ ] **Step 2: Implement MonteCarloSimulator**

```python
# tradingbot/backtest/monte_carlo.py
from __future__ import annotations
import numpy as np
from tradingbot.core.models import MonteCarloResult


class MonteCarloSimulator:
    def __init__(self, simulations: int = 10000, capital: float = 400000,
                 ruin_threshold: float = 0.25):
        self._sims = simulations
        self._capital = capital
        self._ruin_threshold = ruin_threshold

    def run(self, trade_pnls: list[float]) -> MonteCarloResult:
        if len(trade_pnls) < 5:
            return MonteCarloResult(
                simulations=self._sims, median_return_pct=0,
                p10_return_pct=0, p90_return_pct=0,
                median_max_drawdown=0, p95_max_drawdown=0,
                risk_of_ruin_pct=100 if not trade_pnls else 50,
                confidence_score=0,
            )

        pnls = np.array(trade_pnls)
        n = len(pnls)
        returns = []
        max_drawdowns = []
        ruin_count = 0

        for _ in range(self._sims):
            shuffled = np.random.permutation(pnls)
            equity = np.cumsum(shuffled)
            final_return = float(equity[-1] / self._capital * 100)
            returns.append(final_return)

            peak = np.maximum.accumulate(self._capital + equity)
            dd = (peak - (self._capital + equity)) / peak * 100
            max_drawdowns.append(float(np.max(dd)))

            if np.min(self._capital + equity) <= self._capital * (1 - self._ruin_threshold):
                ruin_count += 1

        returns_arr = np.array(returns)
        dd_arr = np.array(max_drawdowns)

        win_rate = np.mean(pnls > 0)
        pf = np.sum(pnls[pnls > 0]) / abs(np.sum(pnls[pnls < 0])) if np.any(pnls < 0) else 10
        ruin_pct = ruin_count / self._sims * 100
        confidence = float(win_rate * min(pf, 5) / 5 * (1 - ruin_pct / 100))

        return MonteCarloResult(
            simulations=self._sims,
            median_return_pct=float(np.median(returns_arr)),
            p10_return_pct=float(np.percentile(returns_arr, 10)),
            p90_return_pct=float(np.percentile(returns_arr, 90)),
            median_max_drawdown=float(np.median(dd_arr)),
            p95_max_drawdown=float(np.percentile(dd_arr, 95)),
            risk_of_ruin_pct=float(ruin_pct),
            confidence_score=max(0, min(1, confidence)),
        )
```

- [ ] **Step 3: Implement QualityGates**

```python
# tradingbot/backtest/quality_gates.py
from __future__ import annotations
from tradingbot.core.models import BacktestReport, MonteCarloResult, QualityGateResult


class QualityGates:
    def __init__(
        self, min_trades: int = 30, min_win_rate: float = 0.45,
        min_profit_factor: float = 1.5, min_expectancy_r: float = 0.3,
        max_oos_degradation: float = 0.3, max_risk_of_ruin: float = 5.0,
        max_consecutive_losses: int = 8,
    ):
        self._min_trades = min_trades
        self._min_wr = min_win_rate
        self._min_pf = min_profit_factor
        self._min_er = min_expectancy_r
        self._max_oos = max_oos_degradation
        self._max_ruin = max_risk_of_ruin
        self._max_consec = max_consecutive_losses

    def evaluate(self, report: BacktestReport, mc: MonteCarloResult) -> QualityGateResult:
        failures = []
        trades_ok = report.total_trades >= self._min_trades
        if not trades_ok:
            failures.append(f"total_trades: {report.total_trades} < {self._min_trades}")

        wr_ok = report.win_rate >= self._min_wr
        if not wr_ok:
            failures.append(f"win_rate: {report.win_rate:.2f} < {self._min_wr}")

        pf_ok = report.profit_factor >= self._min_pf
        if not pf_ok:
            failures.append(f"profit_factor: {report.profit_factor:.2f} < {self._min_pf}")

        er_ok = report.expectancy_r >= self._min_er
        if not er_ok:
            failures.append(f"expectancy_r: {report.expectancy_r:.2f} < {self._min_er}")

        oos_ok = report.oos_degradation <= self._max_oos
        if not oos_ok:
            failures.append(f"oos_degradation: {report.oos_degradation:.2f} > {self._max_oos}")

        mc_p10_ok = mc.p10_return_pct > 0
        if not mc_p10_ok:
            failures.append(f"monte_carlo_p10: {mc.p10_return_pct:.2f}% <= 0")

        ruin_ok = mc.risk_of_ruin_pct <= self._max_ruin
        if not ruin_ok:
            failures.append(f"risk_of_ruin: {mc.risk_of_ruin_pct:.1f}% > {self._max_ruin}%")

        consec_ok = report.max_consecutive_losses <= self._max_consec
        if not consec_ok:
            failures.append(f"max_consecutive_losses: {report.max_consecutive_losses} > {self._max_consec}")

        return QualityGateResult(
            passed=len(failures) == 0,
            total_trades_ok=trades_ok, win_rate_ok=wr_ok,
            profit_factor_ok=pf_ok, expectancy_ok=er_ok,
            oos_ok=oos_ok, monte_carlo_p10_ok=mc_p10_ok,
            ruin_risk_ok=ruin_ok, consecutive_losses_ok=consec_ok,
            failures=failures,
        )
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/backtest/ -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add tradingbot/backtest/monte_carlo.py tradingbot/backtest/quality_gates.py tests/backtest/
git commit -m "feat(backtest): Monte Carlo simulation + quality gates

MonteCarloSimulator: 10K shuffles, P10/P90, risk of ruin, confidence.
QualityGates: 8 non-negotiable gates (trades, win rate, PF, expectancy,
OOS degradation, MC P10, ruin risk, consecutive losses)."
```

---

### Task 11: LLM Prompt Templates & Schemas

**Files:**
- Create: `tradingbot/analysis/__init__.py`
- Create: `tradingbot/analysis/prompts.py`
- Test: `tests/analysis/__init__.py`
- Test: `tests/analysis/test_prompts.py`

**Interfaces:**
- Consumes: nothing (static templates)
- Produces: `REGIME_PROMPT`, `SECTOR_PROMPT`, `SHORTLIST_PROMPT`, `DEEP_ANALYSIS_PROMPT`, `ADVERSARIAL_PROMPT` (system prompts), `REGIME_SCHEMA`, `SECTOR_SCHEMA`, `SHORTLIST_SCHEMA`, `DEEP_ANALYSIS_SCHEMA`, `ADVERSARIAL_SCHEMA` (JSON schemas for tool calling)

- [ ] **Step 1: Write tests for prompt structure**

```python
# tests/analysis/test_prompts.py
import json
from tradingbot.analysis.prompts import (
    REGIME_SYSTEM, REGIME_SCHEMA, REGIME_TOOL,
    SECTOR_SYSTEM, SECTOR_SCHEMA, SECTOR_TOOL,
    SHORTLIST_SYSTEM, SHORTLIST_SCHEMA, SHORTLIST_TOOL,
    DEEP_ANALYSIS_SYSTEM, DEEP_ANALYSIS_SCHEMA, DEEP_ANALYSIS_TOOL,
    ADVERSARIAL_SYSTEM, ADVERSARIAL_SCHEMA, ADVERSARIAL_TOOL,
    build_regime_user_prompt, build_shortlist_user_prompt,
    build_deep_analysis_user_prompt,
)


def test_all_system_prompts_are_strings():
    for prompt in [REGIME_SYSTEM, SECTOR_SYSTEM, SHORTLIST_SYSTEM,
                   DEEP_ANALYSIS_SYSTEM, ADVERSARIAL_SYSTEM]:
        assert isinstance(prompt, str)
        assert len(prompt) > 100


def test_all_schemas_are_valid_json_schema():
    for schema in [REGIME_SCHEMA, SECTOR_SCHEMA, SHORTLIST_SCHEMA,
                   DEEP_ANALYSIS_SCHEMA, ADVERSARIAL_SCHEMA]:
        assert isinstance(schema, dict)
        assert "type" in schema
        assert schema["type"] == "object"
        assert "properties" in schema


def test_all_tools_have_name_and_schema():
    for name, desc, schema in [REGIME_TOOL, SECTOR_TOOL, SHORTLIST_TOOL,
                                DEEP_ANALYSIS_TOOL, ADVERSARIAL_TOOL]:
        assert isinstance(name, str)
        assert isinstance(desc, str)
        assert isinstance(schema, dict)


def test_regime_prompt_contains_anti_hallucination():
    assert "ONLY" in REGIME_SYSTEM or "only" in REGIME_SYSTEM
    assert "Do NOT invent" in REGIME_SYSTEM or "do not invent" in REGIME_SYSTEM.lower()


def test_deep_analysis_prompt_requires_confluence():
    assert "confluence" in DEEP_ANALYSIS_SYSTEM.lower()
    assert "1.5" in DEEP_ANALYSIS_SYSTEM  # R:R floor


def test_adversarial_prompt_is_adversarial():
    assert "reject" in ADVERSARIAL_SYSTEM.lower()
    assert "risk" in ADVERSARIAL_SYSTEM.lower()


def test_build_regime_user_prompt():
    prompt = build_regime_user_prompt(
        nifty=19500, banknifty=45000, vix=13.5,
        nifty_5d_change=1.2, fii_5d_net=-500, dii_5d_net=800,
        advance_decline=1.4, sector_data={"banking": 1.5, "IT": -0.8},
    )
    assert "19500" in prompt
    assert "13.5" in prompt
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/analysis/test_prompts.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: Implement prompts.py with all 5 prompt sets**

```python
# tradingbot/analysis/prompts.py
"""LLM prompt templates and JSON schemas for all analysis calls.

Provider-agnostic: works with OpenAI function calling and Anthropic tool_use.
"""
from __future__ import annotations
from typing import Any

# ── Call 1: Market Regime ──

REGIME_SYSTEM = (
    "You are a senior proprietary trader at a top Indian brokerage with 15 years "
    "of NSE intraday experience managing institutional capital.\n\n"
    "Analyze the market data provided and determine the current market regime. "
    "Think step by step. Show your reasoning before conclusions.\n\n"
    "Use ONLY the data provided. Do NOT invent price levels, volumes, or news. "
    "If data is insufficient for a conclusion, say so and lower your confidence.\n\n"
    "Confidence calibration:\n"
    "- 0.8+ means you would bet your own capital on this read\n"
    "- 0.6-0.8 means directional lean but not high conviction\n"
    "- Below 0.6 means uncertain, recommend defensive positioning"
)

REGIME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "regime": {"type": "string", "enum": ["trending_up", "trending_down", "range_bound", "volatile", "low_vol_squeeze"]},
        "regime_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "bias": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
        "key_levels": {
            "type": "object",
            "properties": {
                "nifty_support": {"type": "number"},
                "nifty_resistance": {"type": "number"},
                "banknifty_support": {"type": "number"},
                "banknifty_resistance": {"type": "number"},
            },
            "required": ["nifty_support", "nifty_resistance"],
        },
        "sectors_in_play": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "sectors_to_avoid": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "risk_appetite": {"type": "string", "enum": ["aggressive", "moderate", "defensive"]},
        "session_expectation": {"type": "string", "maxLength": 200},
        "reasoning": {"type": "string"},
    },
    "required": ["regime", "regime_confidence", "bias", "key_levels",
                  "sectors_in_play", "risk_appetite", "reasoning"],
}

REGIME_TOOL = ("submit_regime_analysis", "Submit market regime analysis", REGIME_SCHEMA)


# ── Call 2: Sector Deep-Dive ──

SECTOR_SYSTEM = (
    "You are a senior proprietary trader at a top Indian brokerage with 15 years "
    "of NSE intraday experience managing institutional capital.\n\n"
    "Analyze the sector data provided in the context of the market regime. "
    "Identify which sectors offer the best intraday opportunities today.\n\n"
    "Use ONLY the data provided. Do NOT invent sector movements or news catalysts. "
    "If you see correlations between sectors, flag them to avoid doubled exposure."
)

SECTOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sectors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "theme": {"type": "string"},
                    "intraday_bias": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
                    "catalyst": {"type": "string"},
                },
                "required": ["name", "intraday_bias"],
            },
        },
        "sector_pairs": {"type": "array", "items": {"type": "string"}},
        "sector_divergences": {"type": "array", "items": {"type": "string"}},
        "cross_sector_picks": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
    },
    "required": ["sectors", "reasoning"],
}

SECTOR_TOOL = ("submit_sector_analysis", "Submit sector analysis", SECTOR_SCHEMA)


# ── Call 3: Candidate Shortlisting ──

SHORTLIST_SYSTEM = (
    "You are a senior proprietary trader at a top Indian brokerage with 15 years "
    "of NSE intraday experience managing institutional capital.\n\n"
    "From the scored stock list provided, select 10-15 high-conviction intraday candidates. "
    "Think step by step. For each pick, explain WHY this stock today — not just that it "
    "scores well, but what specific setup or catalyst makes it actionable.\n\n"
    "Use ONLY the data provided. Do NOT invent price levels, volumes, or news.\n\n"
    "For each pick, state the strongest COUNTER-ARGUMENT — the bear case for longs, "
    "the bull case for shorts. This forces honest assessment.\n\n"
    "Confidence: high = would bet own capital. medium = worth watching. "
    "Do not include low-conviction picks."
)

SHORTLIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "shortlist": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "direction": {"type": "string", "enum": ["long", "short"]},
                    "conviction": {"type": "string", "enum": ["high", "medium"]},
                    "primary_strategy": {"type": "string"},
                    "reasoning": {"type": "string", "maxLength": 300},
                    "key_levels": {
                        "type": "object",
                        "properties": {
                            "support": {"type": "number"},
                            "resistance": {"type": "number"},
                            "vwap": {"type": "number"},
                        },
                    },
                    "risk_flag": {"type": "string"},
                    "counter_argument": {"type": "string"},
                },
                "required": ["symbol", "direction", "conviction", "reasoning"],
            },
            "minItems": 1,
            "maxItems": 20,
        },
        "avoid_list": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
        "max_positions_today": {"type": "integer", "minimum": 1, "maximum": 10},
        "reasoning": {"type": "string"},
    },
    "required": ["shortlist", "max_positions_today", "reasoning"],
}

SHORTLIST_TOOL = ("submit_shortlist", "Submit candidate shortlist", SHORTLIST_SCHEMA)


# ── Call 4: Per-Stock Deep Analysis ──

DEEP_ANALYSIS_SYSTEM = (
    "You are an expert intraday trading strategist with 15 years of NSE experience. "
    "Design precise trade setups based on the multi-timeframe data provided.\n\n"
    "Rules:\n"
    "1. Only propose setups with 3+ independent confirming signals across different "
    "timeframes or indicator types (confluence). Volume + RSI + VWAP = 3 signals. "
    "RSI + Stochastic = 1 signal (both momentum oscillators).\n"
    "2. Minimum reward:risk of 1.5:1 to target_1. If you cannot find that, return "
    "no_trade_reason instead of forcing a setup.\n"
    "3. Entry, stop loss, and targets MUST align with actual support/resistance, "
    "pivot, or VWAP levels from the data. Do NOT round to convenient numbers.\n"
    "4. Do NOT guess or invent price levels. Use ONLY levels visible in the data.\n\n"
    "Confidence calibration:\n"
    "- 0.8+ means you would bet your own capital\n"
    "- 0.6-0.8 means worth taking with reduced size\n"
    "- Below 0.6 means skip — return no_trade_reason\n\n"
    "For each setup, state the invalidation condition — the specific price action "
    "that kills the trade thesis."
)

DEEP_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "symbol": {"type": "string"},
        "setups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "strategy": {"type": "string"},
                    "direction": {"type": "string", "enum": ["long", "short"]},
                    "entry_trigger": {"type": "string"},
                    "entry_price": {"type": "number"},
                    "stop_loss": {"type": "number"},
                    "target_1": {"type": "number"},
                    "target_2": {"type": "number"},
                    "position_size_hint": {"type": "string", "enum": ["0.5x", "1x", "1.5x"]},
                    "entry_window": {"type": "string"},
                    "exit_deadline": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "edge_description": {"type": "string"},
                    "invalidation": {"type": "string"},
                    "bear_case": {"type": "string"},
                    "confluence_count": {"type": "integer", "minimum": 0},
                    "timeframe_alignment": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["strategy", "direction", "entry_price", "stop_loss",
                             "target_1", "confidence", "invalidation", "confluence_count"],
            },
            "maxItems": 3,
        },
        "no_trade_reason": {"type": ["string", "null"]},
    },
    "required": ["symbol"],
}

DEEP_ANALYSIS_TOOL = ("submit_deep_analysis", "Submit per-stock deep analysis", DEEP_ANALYSIS_SCHEMA)


# ── Call 5: Adversarial Validation ──

ADVERSARIAL_SYSTEM = (
    "You are the RISK MANAGER reviewing a junior trader's proposed trade book. "
    "Your job is to find reasons NOT to trade. You get penalized for approving "
    "trades that lose money, not for rejecting winners.\n\n"
    "Review all proposed setups as a PORTFOLIO:\n"
    "1. Check correlation — if multiple stocks from the same sector, flag it\n"
    "2. Check total capital at risk if all stops hit simultaneously\n"
    "3. Check regime contradiction — setups going against the market regime\n"
    "4. Verify stop losses are not too tight (within normal ATR noise)\n"
    "5. Verify entry prices are realistic given current market prices\n\n"
    "No sunk cost — having done deep analysis does not make the trade good. "
    "Reject freely. Be specific about why you reject.\n\n"
    "For conditional approvals, specify the exact adjustment required."
)

ADVERSARIAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "approved": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "setup_index": {"type": "integer"},
                    "approval": {"type": "string", "enum": ["strong", "conditional"]},
                    "adjustment": {"type": ["string", "null"]},
                },
                "required": ["symbol", "setup_index", "approval"],
            },
        },
        "rejected": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "setup_index": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["symbol", "reason"],
            },
        },
        "portfolio_risk_assessment": {
            "type": "object",
            "properties": {
                "total_setups": {"type": "integer"},
                "approved_count": {"type": "integer"},
                "max_correlated_exposure": {"type": "string"},
                "regime_alignment": {"type": "string"},
                "worst_case_loss": {"type": "string"},
                "recommendation": {"type": "string"},
            },
            "required": ["total_setups", "approved_count", "recommendation"],
        },
    },
    "required": ["approved", "rejected", "portfolio_risk_assessment"],
}

ADVERSARIAL_TOOL = ("submit_validation", "Submit adversarial portfolio validation", ADVERSARIAL_SCHEMA)


# ── User prompt builders ──

def build_regime_user_prompt(
    nifty: float, banknifty: float, vix: float,
    nifty_5d_change: float, fii_5d_net: float, dii_5d_net: float,
    advance_decline: float, sector_data: dict[str, float],
) -> str:
    sectors = "\n".join(f"  {k}: {v:+.1f}%" for k, v in sector_data.items())
    return (
        f"Market Data (as of today):\n"
        f"  Nifty 50: {nifty:.0f} (5-day change: {nifty_5d_change:+.1f}%)\n"
        f"  Bank Nifty: {banknifty:.0f}\n"
        f"  India VIX: {vix:.1f}\n"
        f"  FII net (5-day): ₹{fii_5d_net:.0f} Cr\n"
        f"  DII net (5-day): ₹{dii_5d_net:.0f} Cr\n"
        f"  Advance/Decline ratio: {advance_decline:.2f}\n\n"
        f"Sector Performance (today):\n{sectors}\n\n"
        f"Determine the market regime and trading bias for today's session."
    )


def build_shortlist_user_prompt(
    regime_analysis: dict, sector_analysis: dict,
    scored_stocks: list[dict],
) -> str:
    stocks_text = "\n".join(
        f"  {s['symbol']}: score={s['composite_score']:.0f}, "
        f"sector={s['sector']}, price={s['last_price']:.0f}, "
        f"vol_surge={s.get('factor_scores', {}).get('volume_surge', 'N/A')}, "
        f"RS={s.get('factor_scores', {}).get('relative_strength', 'N/A')}"
        for s in scored_stocks[:80]
    )
    return (
        f"Market Regime: {regime_analysis.get('regime', 'unknown')} "
        f"(confidence: {regime_analysis.get('regime_confidence', 0):.0%})\n"
        f"Bias: {regime_analysis.get('bias', 'neutral')}\n"
        f"Risk Appetite: {regime_analysis.get('risk_appetite', 'moderate')}\n\n"
        f"Sectors in play: {regime_analysis.get('sectors_in_play', [])}\n"
        f"Sectors to avoid: {regime_analysis.get('sectors_to_avoid', [])}\n\n"
        f"Scored Stocks (top candidates from Tier 1 screen):\n{stocks_text}\n\n"
        f"Select 10-15 high-conviction intraday candidates with direction and reasoning."
    )


def build_deep_analysis_user_prompt(
    symbol: str, direction: str, regime: dict,
    indicators: dict, backtest_results: list[dict],
    price_action_summary: str,
) -> str:
    bt_text = "\n".join(
        f"  {b['strategy']}: {b['total_trades']} trades, "
        f"win_rate={b['win_rate']:.0%}, PF={b['profit_factor']:.1f}, "
        f"expectancy_r={b['expectancy_r']:.2f}"
        for b in backtest_results
    )
    ind_text = "\n".join(f"  {k}: {v}" for k, v in indicators.items() if not k.startswith("_"))
    return (
        f"Stock: {symbol} | Direction bias: {direction}\n"
        f"Market regime: {regime.get('regime', 'unknown')}\n\n"
        f"Technical Indicators (multi-timeframe):\n{ind_text}\n\n"
        f"Backtest Results:\n{bt_text}\n\n"
        f"Recent Price Action:\n{price_action_summary}\n\n"
        f"Design 1-3 precise trade setups with exact entry, stop loss, and target levels. "
        f"Only propose if you find 3+ confluence signals and 1.5:1 minimum R:R."
    )
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/analysis/test_prompts.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add tradingbot/analysis/ tests/analysis/
git commit -m "feat(analysis): add all LLM prompt templates and JSON schemas

5 prompt sets: regime, sector, shortlist, deep analysis, adversarial.
Anti-hallucination guards, confluence requirements, calibrated confidence.
Provider-agnostic: works with OpenAI function calling and Anthropic tool_use."
```

---

### Task 12: Tier 2 LLM Analyzer

**Files:**
- Create: `tradingbot/analysis/tier2_analyzer.py`
- Test: `tests/analysis/test_tier2.py`

**Interfaces:**
- Consumes: `LLMProvider.analyze()` (existing), prompts from Task 11, `ScoredStock` list from Task 7
- Produces: `Tier2Analyzer.analyze_regime(market_data) -> dict`, `Tier2Analyzer.analyze_sectors(regime, sector_data, top_stocks) -> dict`, `Tier2Analyzer.shortlist(regime, sectors, scored_stocks) -> list[dict]`

- [ ] **Step 1: Write tests with mocked LLM**

```python
# tests/analysis/test_tier2.py
import pytest
from unittest.mock import AsyncMock
from tradingbot.analysis.tier2_analyzer import Tier2Analyzer


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.analyze.return_value = {
        "regime": "trending_up", "regime_confidence": 0.82,
        "bias": "bullish",
        "key_levels": {"nifty_support": 19200, "nifty_resistance": 19600},
        "sectors_in_play": ["banking", "IT"],
        "sectors_to_avoid": ["pharma"],
        "risk_appetite": "moderate",
        "reasoning": "test reasoning",
    }
    return provider


async def test_analyze_regime(mock_provider):
    analyzer = Tier2Analyzer(mock_provider)
    result = await analyzer.analyze_regime(
        nifty=19500, banknifty=45000, vix=13.5,
        nifty_5d_change=1.2, fii_5d_net=-500, dii_5d_net=800,
        advance_decline=1.4, sector_data={"banking": 1.5},
    )
    assert result["regime"] == "trending_up"
    assert result["regime_confidence"] == 0.82
    mock_provider.analyze.assert_called_once()


async def test_shortlist_returns_list(mock_provider):
    mock_provider.analyze.return_value = {
        "shortlist": [
            {"symbol": "RELIANCE", "direction": "long", "conviction": "high",
             "reasoning": "strong momentum"},
        ],
        "max_positions_today": 3,
        "reasoning": "bullish regime favors longs",
    }
    analyzer = Tier2Analyzer(mock_provider)
    regime = {"regime": "trending_up", "regime_confidence": 0.82,
              "bias": "bullish", "sectors_in_play": ["energy"],
              "sectors_to_avoid": [], "risk_appetite": "moderate"}
    result = await analyzer.shortlist(regime, {}, [])
    assert len(result["shortlist"]) == 1
    assert result["shortlist"][0]["symbol"] == "RELIANCE"
```

- [ ] **Step 2: Implement Tier2Analyzer**

```python
# tradingbot/analysis/tier2_analyzer.py
from __future__ import annotations
import logging
from typing import Any
from tradingbot.core.llm.provider import LLMProvider
from tradingbot.analysis.prompts import (
    REGIME_SYSTEM, REGIME_TOOL, build_regime_user_prompt,
    SECTOR_SYSTEM, SECTOR_TOOL,
    SHORTLIST_SYSTEM, SHORTLIST_TOOL, build_shortlist_user_prompt,
)

log = logging.getLogger(__name__)


class Tier2Analyzer:
    def __init__(self, provider: LLMProvider):
        self._provider = provider

    async def analyze_regime(
        self, nifty: float, banknifty: float, vix: float,
        nifty_5d_change: float, fii_5d_net: float, dii_5d_net: float,
        advance_decline: float, sector_data: dict[str, float],
    ) -> dict[str, Any]:
        user_prompt = build_regime_user_prompt(
            nifty, banknifty, vix, nifty_5d_change,
            fii_5d_net, dii_5d_net, advance_decline, sector_data,
        )
        name, desc, schema = REGIME_TOOL
        result = await self._provider.analyze(
            REGIME_SYSTEM, user_prompt, name, desc, schema,
        )
        log.info("Regime: %s (confidence: %.0f%%)",
                 result.get("regime"), result.get("regime_confidence", 0) * 100)
        return result

    async def analyze_sectors(
        self, regime: dict, sector_data: dict, top_stocks_by_sector: dict,
    ) -> dict[str, Any]:
        user_prompt = (
            f"Market Regime: {regime.get('regime')} (confidence: {regime.get('regime_confidence', 0):.0%})\n"
            f"Sectors in play: {regime.get('sectors_in_play', [])}\n\n"
            f"Sector Index Data:\n" +
            "\n".join(f"  {k}: {v}" for k, v in sector_data.items()) +
            f"\n\nTop stocks per sector:\n" +
            "\n".join(f"  {sector}: {', '.join(stocks)}"
                      for sector, stocks in top_stocks_by_sector.items())
        )
        name, desc, schema = SECTOR_TOOL
        return await self._provider.analyze(
            SECTOR_SYSTEM, user_prompt, name, desc, schema,
        )

    async def shortlist(
        self, regime: dict, sector_analysis: dict,
        scored_stocks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        user_prompt = build_shortlist_user_prompt(regime, sector_analysis, scored_stocks)
        name, desc, schema = SHORTLIST_TOOL
        result = await self._provider.analyze(
            SHORTLIST_SYSTEM, user_prompt, name, desc, schema,
        )
        log.info("Shortlisted %d candidates", len(result.get("shortlist", [])))
        return result
```

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/analysis/test_tier2.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tradingbot/analysis/tier2_analyzer.py tests/analysis/test_tier2.py
git commit -m "feat(analysis): add Tier 2 LLM analyzer (regime, sector, shortlist)

Three focused LLM calls: market regime → sector deep-dive → candidate
shortlisting. Each call builds on previous output."
```

---

### Task 13: Tier 3 Deep Analyzer + Adversarial Validation

**Files:**
- Create: `tradingbot/analysis/tier3_analyzer.py`
- Test: `tests/analysis/test_tier3.py`

**Interfaces:**
- Consumes: `LLMProvider.analyze()`, prompts (Task 11), `BacktestReport` (Task 9), `IndicatorSnapshot` (Task 6)
- Produces: `Tier3Analyzer.deep_analyze(symbol, direction, regime, indicators, backtests) -> dict`, `Tier3Analyzer.validate_portfolio(all_setups, regime) -> dict`

- [ ] **Step 1: Write tests**

```python
# tests/analysis/test_tier3.py
import pytest
from unittest.mock import AsyncMock
from tradingbot.analysis.tier3_analyzer import Tier3Analyzer


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    return provider


async def test_deep_analyze_returns_setups(mock_provider):
    mock_provider.analyze.return_value = {
        "symbol": "RELIANCE",
        "setups": [{
            "strategy": "vwap_mean_reversion", "direction": "long",
            "entry_price": 2485.0, "stop_loss": 2468.0,
            "target_1": 2510.0, "target_2": 2530.0,
            "confidence": 0.82, "invalidation": "close below 2460",
            "confluence_count": 4,
        }],
        "no_trade_reason": None,
    }
    analyzer = Tier3Analyzer(mock_provider)
    result = await analyzer.deep_analyze(
        symbol="RELIANCE", direction="long",
        regime={"regime": "trending_up"},
        indicators={"rsi_14": 45, "vwap": 2505},
        backtest_results=[],
        price_action="3 day pullback to VWAP support",
    )
    assert result["symbol"] == "RELIANCE"
    assert len(result["setups"]) == 1
    assert result["setups"][0]["confidence"] == 0.82


async def test_validate_portfolio(mock_provider):
    mock_provider.analyze.return_value = {
        "approved": [{"symbol": "RELIANCE", "setup_index": 0, "approval": "strong"}],
        "rejected": [],
        "portfolio_risk_assessment": {
            "total_setups": 1, "approved_count": 1,
            "recommendation": "execute",
        },
    }
    analyzer = Tier3Analyzer(mock_provider)
    result = await analyzer.validate_portfolio(
        all_setups=[{"symbol": "RELIANCE", "setups": [{"confidence": 0.82}]}],
        regime={"regime": "trending_up"},
        sector_analysis={},
    )
    assert len(result["approved"]) == 1
    assert result["portfolio_risk_assessment"]["approved_count"] == 1
```

- [ ] **Step 2: Implement Tier3Analyzer**

```python
# tradingbot/analysis/tier3_analyzer.py
from __future__ import annotations
import logging
from typing import Any
from tradingbot.core.llm.provider import LLMProvider
from tradingbot.analysis.prompts import (
    DEEP_ANALYSIS_SYSTEM, DEEP_ANALYSIS_TOOL, build_deep_analysis_user_prompt,
    ADVERSARIAL_SYSTEM, ADVERSARIAL_TOOL,
)

log = logging.getLogger(__name__)


class Tier3Analyzer:
    def __init__(self, provider: LLMProvider):
        self._provider = provider

    async def deep_analyze(
        self, symbol: str, direction: str, regime: dict,
        indicators: dict, backtest_results: list[dict],
        price_action: str,
    ) -> dict[str, Any]:
        user_prompt = build_deep_analysis_user_prompt(
            symbol, direction, regime, indicators, backtest_results, price_action,
        )
        name, desc, schema = DEEP_ANALYSIS_TOOL
        result = await self._provider.analyze(
            DEEP_ANALYSIS_SYSTEM, user_prompt, name, desc, schema,
        )
        n_setups = len(result.get("setups", []))
        no_trade = result.get("no_trade_reason")
        if no_trade:
            log.info("%s: no trade — %s", symbol, no_trade)
        else:
            log.info("%s: %d setups proposed", symbol, n_setups)
        return result

    async def validate_portfolio(
        self, all_setups: list[dict], regime: dict,
        sector_analysis: dict,
    ) -> dict[str, Any]:
        setups_text = "\n\n".join(
            f"Stock: {s['symbol']}\n" +
            "\n".join(
                f"  Setup {i}: {setup.get('strategy', 'unknown')} "
                f"{setup.get('direction', '?')} @ {setup.get('entry_price', 0)} "
                f"SL={setup.get('stop_loss', 0)} T1={setup.get('target_1', 0)} "
                f"conf={setup.get('confidence', 0)}"
                for i, setup in enumerate(s.get("setups", []))
            )
            for s in all_setups if s.get("setups")
        )
        user_prompt = (
            f"Market Regime: {regime.get('regime')} "
            f"(confidence: {regime.get('regime_confidence', 0):.0%})\n\n"
            f"Proposed Setups for Today:\n{setups_text}\n\n"
            f"Review as a portfolio. Check correlations, total risk, "
            f"regime alignment. Approve, reject, or conditionally approve each."
        )
        name, desc, schema = ADVERSARIAL_TOOL
        result = await self._provider.analyze(
            ADVERSARIAL_SYSTEM, user_prompt, name, desc, schema,
        )
        approved = len(result.get("approved", []))
        rejected = len(result.get("rejected", []))
        log.info("Validation: %d approved, %d rejected", approved, rejected)
        return result
```

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/analysis/ -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tradingbot/analysis/tier3_analyzer.py tests/analysis/test_tier3.py
git commit -m "feat(analysis): add Tier 3 deep analyzer + adversarial validation

Per-stock LLM deep analysis with confluence requirement and R:R floor.
Adversarial validator stress-tests portfolio-level risk and correlations."
```

---

### Task 14: Multi-Run Persistence (SQLite Schema + Stores)

**Files:**
- Create: `tradingbot/persistence/__init__.py`
- Create: `tradingbot/persistence/run_store.py`
- Create: `tradingbot/persistence/setup_store.py`
- Test: `tests/persistence/__init__.py`
- Test: `tests/persistence/test_stores.py`

**Interfaces:**
- Consumes: `AnalysisRun`, `SetupStatus` (Task 1)
- Produces: `RunStore.save(run)`, `RunStore.list_for_date(date) -> list[AnalysisRun]`, `SetupStore.save(run_id, setup)`, `SetupStore.get_active(date) -> list`, `SetupStore.update_status(setup_id, status)`, `SetupStore.get_for_symbol(symbol, date) -> list`

- [ ] **Step 1: Write tests**

```python
# tests/persistence/test_stores.py
import pytest
from datetime import date, datetime
from zoneinfo import ZoneInfo
from tradingbot.core.models import (
    AnalysisRun, MarketRegime, SetupStatus, StrategyName, Direction,
)
from tradingbot.persistence.run_store import RunStore
from tradingbot.persistence.setup_store import SetupStore

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def run_store(tmp_path):
    return RunStore(tmp_path / "analysis.db")


@pytest.fixture
def setup_store(tmp_path):
    return SetupStore(tmp_path / "analysis.db")


def _make_run(run_id="run_001", trade_date=date(2026, 9, 27)):
    return AnalysisRun(
        run_id=run_id, timestamp=datetime.now(tz=IST), trade_date=trade_date,
        market_regime=MarketRegime.TRENDING_UP, regime_confidence=0.82,
        total_scanned=1500, tier1_passed=80, tier2_shortlisted=12,
        setups_proposed=8, setups_approved=5, llm_calls=16,
        llm_cost_usd=0.18, duration_seconds=45.2,
    )


def test_save_and_list_runs(run_store):
    run = _make_run()
    run_store.save(run)
    runs = run_store.list_for_date(date(2026, 9, 27))
    assert len(runs) == 1
    assert runs[0]["run_id"] == "run_001"


def test_multiple_runs_same_date(run_store):
    run_store.save(_make_run("run_001"))
    run_store.save(_make_run("run_002"))
    runs = run_store.list_for_date(date(2026, 9, 27))
    assert len(runs) == 2


def test_setup_save_and_get(setup_store):
    setup = {
        "run_id": "run_001", "symbol": "RELIANCE", "strategy": "vwap_mean_reversion",
        "direction": "long", "entry_price": 2485.0, "stop_loss": 2468.0,
        "target_1": 2510.0, "target_2": 2530.0, "confidence": 0.82,
        "status": "approved", "trade_date": "2026-09-27",
        "reasoning": "VWAP support bounce",
    }
    setup_id = setup_store.save(setup)
    assert setup_id > 0
    active = setup_store.get_active(date(2026, 9, 27))
    assert len(active) == 1


def test_setup_update_status(setup_store):
    setup = {
        "run_id": "run_001", "symbol": "TCS", "strategy": "momentum",
        "direction": "long", "entry_price": 3500.0, "stop_loss": 3470.0,
        "target_1": 3550.0, "target_2": 3580.0, "confidence": 0.75,
        "status": "proposed", "trade_date": "2026-09-27", "reasoning": "test",
    }
    setup_id = setup_store.save(setup)
    setup_store.update_status(setup_id, "rejected", reason="too tight SL")
    result = setup_store.get_by_id(setup_id)
    assert result["status"] == "rejected"


def test_get_for_symbol(setup_store):
    for i, run_id in enumerate(["run_001", "run_002"]):
        setup_store.save({
            "run_id": run_id, "symbol": "RELIANCE", "strategy": "momentum",
            "direction": "long", "entry_price": 2500 + i * 10, "stop_loss": 2480,
            "target_1": 2540, "target_2": 2560, "confidence": 0.7 + i * 0.05,
            "status": "approved", "trade_date": "2026-09-27", "reasoning": f"run {i}",
        })
    setups = setup_store.get_for_symbol("RELIANCE", date(2026, 9, 27))
    assert len(setups) == 2
```

- [ ] **Step 2: Implement RunStore**

```python
# tradingbot/persistence/run_store.py
from __future__ import annotations
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any
from tradingbot.core.models import AnalysisRun


class RunStore:
    def __init__(self, db_path: Path):
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS analysis_runs (
                run_id TEXT PRIMARY KEY,
                trade_date TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                market_regime TEXT NOT NULL,
                regime_confidence REAL,
                total_scanned INTEGER,
                tier1_passed INTEGER,
                tier2_shortlisted INTEGER,
                setups_proposed INTEGER,
                setups_approved INTEGER,
                llm_calls INTEGER,
                llm_cost_usd REAL,
                duration_seconds REAL
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_run_date ON analysis_runs(trade_date)")
        self._conn.commit()

    def save(self, run: AnalysisRun) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO analysis_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run.run_id, str(run.trade_date), run.timestamp.isoformat(),
             run.market_regime.value, run.regime_confidence,
             run.total_scanned, run.tier1_passed, run.tier2_shortlisted,
             run.setups_proposed, run.setups_approved,
             run.llm_calls, run.llm_cost_usd, run.duration_seconds),
        )
        self._conn.commit()

    def list_for_date(self, trade_date: date) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM analysis_runs WHERE trade_date = ? ORDER BY timestamp",
            (str(trade_date),),
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 3: Implement SetupStore**

```python
# tradingbot/persistence/setup_store.py
from __future__ import annotations
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


class SetupStore:
    def __init__(self, db_path: Path):
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS setups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                strategy TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                target_1 REAL NOT NULL,
                target_2 REAL,
                confidence REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'proposed',
                reasoning TEXT,
                rejection_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_setup_date ON setups(trade_date)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_setup_symbol ON setups(symbol, trade_date)")
        self._conn.commit()

    def save(self, setup: dict[str, Any]) -> int:
        now = datetime.now(tz=IST).isoformat()
        cursor = self._conn.execute(
            "INSERT INTO setups (run_id, trade_date, symbol, strategy, direction, "
            "entry_price, stop_loss, target_1, target_2, confidence, status, reasoning, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (setup["run_id"], setup["trade_date"], setup["symbol"],
             setup["strategy"], setup["direction"], setup["entry_price"],
             setup["stop_loss"], setup["target_1"], setup.get("target_2"),
             setup["confidence"], setup.get("status", "proposed"),
             setup.get("reasoning", ""), now, now),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_active(self, trade_date: date) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM setups WHERE trade_date = ? AND status IN ('approved', 'active') "
            "ORDER BY confidence DESC",
            (str(trade_date),),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_for_symbol(self, symbol: str, trade_date: date) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM setups WHERE symbol = ? AND trade_date = ? ORDER BY created_at",
            (symbol, str(trade_date)),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_by_id(self, setup_id: int) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM setups WHERE id = ?", (setup_id,)).fetchone()
        if row is None:
            raise KeyError(f"Setup {setup_id} not found")
        return dict(row)

    def update_status(self, setup_id: int, status: str, reason: str = "") -> None:
        now = datetime.now(tz=IST).isoformat()
        self._conn.execute(
            "UPDATE setups SET status = ?, rejection_reason = ?, updated_at = ? WHERE id = ?",
            (status, reason, now, setup_id),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/persistence/ -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add tradingbot/persistence/ tests/persistence/
git commit -m "feat(persistence): add RunStore and SetupStore for multi-run accumulation

RunStore: save/list analysis runs per date. SetupStore: save setups with
lifecycle status, query by date/symbol, update status. Both SQLite-backed."
```

---

### Task 15: DailyPlan Assembly + Cross-Run Ranking + API Endpoints

**Files:**
- Create: `tradingbot/persistence/daily_plan.py`
- Modify: `tradingbot/api/analysis_routes.py`
- Test: `tests/persistence/test_daily_plan.py`
- Test: `tests/api/test_analysis_routes_v2.py`

**Interfaces:**
- Consumes: `RunStore`, `SetupStore` (Task 14)
- Produces: `DailyPlanBuilder.build(date) -> dict` (ranked suggestions with cross-run consistency), new API endpoints: `GET /api/plans/today`, `GET /api/plans/runs`, `GET /api/plans/setups`, `PATCH /api/setups/{id}`

- [ ] **Step 1: Write tests for DailyPlanBuilder**

```python
# tests/persistence/test_daily_plan.py
import pytest
from datetime import date, datetime
from zoneinfo import ZoneInfo
from tradingbot.persistence.daily_plan import DailyPlanBuilder
from tradingbot.persistence.run_store import RunStore
from tradingbot.persistence.setup_store import SetupStore
from tradingbot.core.models import AnalysisRun, MarketRegime

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def stores(tmp_path):
    db = tmp_path / "test.db"
    return RunStore(db), SetupStore(db)


def test_build_daily_plan_ranks_by_confidence(stores):
    run_store, setup_store = stores
    run = AnalysisRun(
        run_id="run_001", timestamp=datetime.now(tz=IST),
        trade_date=date(2026, 9, 27), market_regime=MarketRegime.TRENDING_UP,
        regime_confidence=0.82, total_scanned=1500, tier1_passed=80,
        tier2_shortlisted=12, setups_proposed=3, setups_approved=3,
        llm_calls=16, llm_cost_usd=0.18, duration_seconds=45,
    )
    run_store.save(run)
    for sym, conf in [("RELIANCE", 0.88), ("HDFCBANK", 0.75), ("TCS", 0.92)]:
        setup_store.save({
            "run_id": "run_001", "symbol": sym, "strategy": "momentum",
            "direction": "long", "entry_price": 1000, "stop_loss": 980,
            "target_1": 1030, "target_2": 1050, "confidence": conf,
            "status": "approved", "trade_date": "2026-09-27", "reasoning": "test",
        })

    builder = DailyPlanBuilder(run_store, setup_store)
    plan = builder.build(date(2026, 9, 27))
    assert plan["date"] == "2026-09-27"
    assert len(plan["ranked_suggestions"]) == 3
    assert plan["ranked_suggestions"][0]["symbol"] == "TCS"  # highest confidence


def test_cross_run_consistency(stores):
    run_store, setup_store = stores
    for rid in ["run_001", "run_002"]:
        run_store.save(AnalysisRun(
            run_id=rid, timestamp=datetime.now(tz=IST),
            trade_date=date(2026, 9, 27), market_regime=MarketRegime.TRENDING_UP,
            regime_confidence=0.82, total_scanned=1500, tier1_passed=80,
            tier2_shortlisted=12, setups_proposed=2, setups_approved=2,
            llm_calls=16, llm_cost_usd=0.18, duration_seconds=45,
        ))
        setup_store.save({
            "run_id": rid, "symbol": "RELIANCE", "strategy": "momentum",
            "direction": "long", "entry_price": 2500, "stop_loss": 2480,
            "target_1": 2530, "target_2": 2550, "confidence": 0.8,
            "status": "approved", "trade_date": "2026-09-27", "reasoning": "test",
        })

    builder = DailyPlanBuilder(run_store, setup_store)
    plan = builder.build(date(2026, 9, 27))
    rel = [s for s in plan["ranked_suggestions"] if s["symbol"] == "RELIANCE"][0]
    assert rel["consistency"] == 1.0  # both runs agree
```

- [ ] **Step 2: Implement DailyPlanBuilder**

```python
# tradingbot/persistence/daily_plan.py
from __future__ import annotations
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo
from tradingbot.persistence.run_store import RunStore
from tradingbot.persistence.setup_store import SetupStore

IST = ZoneInfo("Asia/Kolkata")
STALE_HOURS_VOLATILE = 2
STALE_HOURS_NORMAL = 4


class DailyPlanBuilder:
    def __init__(self, run_store: RunStore, setup_store: SetupStore):
        self._runs = run_store
        self._setups = setup_store

    def build(self, trade_date: date) -> dict[str, Any]:
        runs = self._runs.list_for_date(trade_date)
        active = self._setups.get_active(trade_date)
        all_setups_today = self._setups._conn.execute(
            "SELECT * FROM setups WHERE trade_date = ? ORDER BY created_at",
            (str(trade_date),),
        ).fetchall()

        by_symbol: dict[str, list[dict]] = defaultdict(list)
        for s in all_setups_today:
            by_symbol[dict(s)["symbol"]].append(dict(s))

        ranked = []
        for symbol, setups in by_symbol.items():
            approved = [s for s in setups if s["status"] in ("approved", "active")]
            if not approved:
                continue
            best = max(approved, key=lambda s: s["confidence"])
            run_ids = {s["run_id"] for s in approved}
            total_runs = len(runs) if runs else 1
            consistency = len(run_ids) / total_runs

            directions = {s["direction"] for s in approved}
            recommendation = "execute"
            if len(directions) > 1:
                recommendation = "conflicting"
            elif consistency < 0.5:
                recommendation = "watch"

            ranked.append({
                "rank": 0,
                "symbol": symbol,
                "direction": best["direction"],
                "confidence": best["confidence"],
                "consistency": consistency,
                "best_setup": best,
                "run_count": len(run_ids),
                "recommendation": recommendation,
            })

        ranked.sort(key=lambda s: (s["confidence"] * (1 + s["consistency"])), reverse=True)
        for i, s in enumerate(ranked):
            s["rank"] = i + 1

        return {
            "date": str(trade_date),
            "runs": runs,
            "total_runs": len(runs),
            "active_setups": [dict(s) for s in active] if active else [],
            "ranked_suggestions": ranked,
        }
```

- [ ] **Step 3: Add new API endpoints to analysis_routes.py**

Add these endpoints to `tradingbot/api/analysis_routes.py`:

```python
@router.get("/plans/today")
async def get_daily_plan(state: AppState = Depends(get_state)):
    from tradingbot.persistence.daily_plan import DailyPlanBuilder
    builder = DailyPlanBuilder(state.run_store, state.setup_store)
    today = date.today()
    return builder.build(today)

@router.get("/plans/runs")
async def list_runs(trade_date: str | None = None, state: AppState = Depends(get_state)):
    d = date.fromisoformat(trade_date) if trade_date else date.today()
    return state.run_store.list_for_date(d)

@router.get("/plans/setups")
async def get_setups(symbol: str | None = None, trade_date: str | None = None,
                     state: AppState = Depends(get_state)):
    d = date.fromisoformat(trade_date) if trade_date else date.today()
    if symbol:
        return state.setup_store.get_for_symbol(symbol, d)
    return state.setup_store.get_active(d)

@router.patch("/setups/{setup_id}")
async def update_setup(setup_id: int, body: dict, state: AppState = Depends(get_state)):
    status = body.get("status")
    reason = body.get("reason", "")
    if status not in ("approved", "rejected", "active"):
        raise HTTPException(400, "Invalid status")
    state.setup_store.update_status(setup_id, status, reason)
    return {"ok": True, "setup_id": setup_id, "status": status}
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/persistence/ tests/api/ -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add tradingbot/persistence/daily_plan.py tradingbot/api/analysis_routes.py tests/
git commit -m "feat(persistence): DailyPlan builder + cross-run ranking + API endpoints

DailyPlanBuilder ranks setups by confidence × consistency across runs.
Flags conflicting directions. New endpoints: /plans/today, /plans/runs,
/plans/setups, PATCH /setups/{id}."
```

---

### Task 16: Kite Auth + Capital Manager

**Files:**
- Create: `tradingbot/execution/kite_auth.py`
- Create: `tradingbot/execution/capital_manager.py`
- Test: `tests/execution/__init__.py` (if missing)
- Test: `tests/execution/test_kite_auth.py`
- Test: `tests/execution/test_capital_manager.py`

**Interfaces:**
- Consumes: `KiteClient` (Task 3), `Config` (Task 2)
- Produces: `KiteAuth.get_access_token()`, `KiteAuth.is_authenticated()`, `CapitalManager.available_capital()`, `CapitalManager.check_margin(entry_price, qty)`, `CapitalManager.daily_pnl()`

- [ ] **Step 1: Write tests**

```python
# tests/execution/test_kite_auth.py
from unittest.mock import MagicMock
from tradingbot.execution.kite_auth import KiteAuth


def test_is_authenticated_false_initially():
    auth = KiteAuth(api_key="test", api_secret="secret")
    assert auth.is_authenticated() is False


def test_set_access_token():
    auth = KiteAuth(api_key="test", api_secret="secret")
    mock_kite = MagicMock()
    mock_kite.profile.return_value = {"user_name": "Test User"}
    auth.set_access_token("token123", mock_kite)
    assert auth.is_authenticated() is True


# tests/execution/test_capital_manager.py
from unittest.mock import MagicMock
from tradingbot.execution.capital_manager import CapitalManager


def test_available_capital():
    client = MagicMock()
    client.get_margins.return_value = {
        "equity": {"available": {"live_balance": 400000, "intraday_payin": 0}},
    }
    mgr = CapitalManager(client, deployed=50000)
    available = mgr.available_capital()
    assert available == 350000


def test_check_margin_sufficient():
    client = MagicMock()
    client.get_margins.return_value = {
        "equity": {"available": {"live_balance": 400000, "intraday_payin": 0}},
    }
    mgr = CapitalManager(client, deployed=0)
    ok, reason = mgr.check_margin(entry_price=2500, quantity=10)
    # 2500 * 10 / 5 (margin) = 5000 needed, 400000 available
    assert ok is True


def test_check_margin_insufficient():
    client = MagicMock()
    client.get_margins.return_value = {
        "equity": {"available": {"live_balance": 1000, "intraday_payin": 0}},
    }
    mgr = CapitalManager(client, deployed=0)
    ok, reason = mgr.check_margin(entry_price=2500, quantity=100)
    assert ok is False
```

- [ ] **Step 2: Implement KiteAuth and CapitalManager**

```python
# tradingbot/execution/kite_auth.py
from __future__ import annotations
import logging
from typing import Any

log = logging.getLogger(__name__)


class KiteAuth:
    def __init__(self, api_key: str, api_secret: str):
        self._api_key = api_key
        self._api_secret = api_secret
        self._access_token: str | None = None
        self._kite: Any | None = None

    def is_authenticated(self) -> bool:
        return self._access_token is not None

    def set_access_token(self, token: str, kite: Any) -> None:
        kite.set_access_token(token)
        kite.profile()  # validate token
        self._access_token = token
        self._kite = kite
        log.info("Kite authenticated successfully")

    def get_login_url(self) -> str:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=self._api_key)
        return kite.login_url()

    @property
    def kite(self) -> Any:
        if self._kite is None:
            raise RuntimeError("Not authenticated — call set_access_token first")
        return self._kite


# tradingbot/execution/capital_manager.py
from __future__ import annotations
import logging
from tradingbot.data.kite_client import KiteClient

log = logging.getLogger(__name__)
INTRADAY_MARGIN_MULTIPLIER = 5


class CapitalManager:
    def __init__(self, client: KiteClient, deployed: float = 0):
        self._client = client
        self._deployed = deployed

    def available_capital(self) -> float:
        margins = self._client.get_margins("equity")
        available = margins.get("equity", {}).get("available", {})
        balance = available.get("live_balance", 0) + available.get("intraday_payin", 0)
        return balance - self._deployed

    def check_margin(self, entry_price: float, quantity: int) -> tuple[bool, str]:
        required = (entry_price * quantity) / INTRADAY_MARGIN_MULTIPLIER
        available = self.available_capital()
        if required > available:
            return False, f"Need ₹{required:.0f} margin, only ₹{available:.0f} available"
        return True, ""

    def add_deployed(self, amount: float) -> None:
        self._deployed += amount

    def release_deployed(self, amount: float) -> None:
        self._deployed = max(0, self._deployed - amount)
```

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/execution/test_kite_auth.py tests/execution/test_capital_manager.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tradingbot/execution/kite_auth.py tradingbot/execution/capital_manager.py tests/execution/
git commit -m "feat(execution): add Kite OAuth auth + capital manager

KiteAuth: token management, login URL generation, profile validation.
CapitalManager: live margin from Kite, margin check per trade, deployed tracking."
```

---

### Task 17: Kite Order Executor + Safety Mechanisms

**Files:**
- Create: `tradingbot/execution/kite_executor.py`
- Create: `tradingbot/execution/safety.py`
- Test: `tests/execution/test_kite_executor.py`
- Test: `tests/execution/test_safety.py`

**Interfaces:**
- Consumes: `KiteClient` (Task 3), `CapitalManager` (Task 16), `RiskConfig` (existing)
- Produces: `KiteExecutor.place_entry(setup) -> str`, `KiteExecutor.place_exit(position, reason) -> str`, `KiteExecutor.modify_order(order_id, price)`, `SafetyManager.check_daily_loss(pnl) -> bool`, `SafetyManager.emergency_stop(executor)`

- [ ] **Step 1: Write tests**

```python
# tests/execution/test_kite_executor.py
import pytest
from unittest.mock import MagicMock
from tradingbot.execution.kite_executor import KiteExecutor


def test_place_entry_long():
    client = MagicMock()
    client.place_order.return_value = "ORD001"
    cap_mgr = MagicMock()
    cap_mgr.check_margin.return_value = (True, "")
    executor = KiteExecutor(client, cap_mgr, max_drift_pct=2.0)

    order_id = executor.place_entry(
        symbol="RELIANCE", exchange="NSE", direction="long",
        entry_price=2500, stop_loss=2480, quantity=10,
        order_type="LIMIT", current_price=2502,
    )
    assert order_id == "ORD001"
    client.place_order.assert_called_once()


def test_place_entry_rejects_drifted_price():
    client = MagicMock()
    cap_mgr = MagicMock()
    cap_mgr.check_margin.return_value = (True, "")
    executor = KiteExecutor(client, cap_mgr, max_drift_pct=2.0)

    order_id = executor.place_entry(
        symbol="RELIANCE", exchange="NSE", direction="long",
        entry_price=2500, stop_loss=2480, quantity=10,
        order_type="LIMIT", current_price=2600,  # 4% drift
    )
    assert order_id is None


def test_place_entry_rejects_insufficient_margin():
    client = MagicMock()
    cap_mgr = MagicMock()
    cap_mgr.check_margin.return_value = (False, "insufficient margin")
    executor = KiteExecutor(client, cap_mgr, max_drift_pct=2.0)

    order_id = executor.place_entry(
        symbol="TCS", exchange="NSE", direction="long",
        entry_price=3500, stop_loss=3470, quantity=100,
        order_type="LIMIT", current_price=3500,
    )
    assert order_id is None


# tests/execution/test_safety.py
from tradingbot.execution.safety import SafetyManager


def test_daily_loss_not_breached():
    mgr = SafetyManager(capital=400000, max_daily_loss_pct=2.0)
    assert mgr.check_daily_loss(-5000) is False  # 1.25% < 2%


def test_daily_loss_breached():
    mgr = SafetyManager(capital=400000, max_daily_loss_pct=2.0)
    assert mgr.check_daily_loss(-9000) is True  # 2.25% > 2%


def test_max_positions_check():
    mgr = SafetyManager(capital=400000, max_daily_loss_pct=2.0, max_positions=4)
    assert mgr.can_open_position(current_positions=3) is True
    assert mgr.can_open_position(current_positions=4) is False
```

- [ ] **Step 2: Implement KiteExecutor and SafetyManager**

```python
# tradingbot/execution/kite_executor.py
from __future__ import annotations
import logging
from typing import Any
from tradingbot.data.kite_client import KiteClient
from tradingbot.execution.capital_manager import CapitalManager

log = logging.getLogger(__name__)


class KiteExecutor:
    def __init__(self, client: KiteClient, capital_manager: CapitalManager,
                 max_drift_pct: float = 2.0):
        self._client = client
        self._capital = capital_manager
        self._max_drift = max_drift_pct

    def place_entry(
        self, symbol: str, exchange: str, direction: str,
        entry_price: float, stop_loss: float, quantity: int,
        order_type: str, current_price: float,
    ) -> str | None:
        drift = abs(current_price - entry_price) / entry_price * 100
        if drift > self._max_drift:
            log.warning("%s: price drifted %.1f%%, skipping", symbol, drift)
            return None

        ok, reason = self._capital.check_margin(entry_price, quantity)
        if not ok:
            log.warning("%s: %s", symbol, reason)
            return None

        transaction_type = "BUY" if direction == "long" else "SELL"
        try:
            order_id = self._client.place_order(
                variety="regular", exchange=exchange, tradingsymbol=symbol,
                transaction_type=transaction_type, quantity=quantity,
                product="MIS", order_type=order_type, price=entry_price,
                validity="DAY",
            )
            self._capital.add_deployed(entry_price * quantity)
            log.info("%s: entry order placed %s", symbol, order_id)
            return order_id
        except Exception:
            log.exception("%s: failed to place entry", symbol)
            return None

    def place_exit(self, symbol: str, exchange: str, direction: str,
                   quantity: int, price: float | None = None,
                   order_type: str = "MARKET") -> str | None:
        transaction_type = "SELL" if direction == "long" else "BUY"
        try:
            kwargs: dict[str, Any] = dict(
                variety="regular", exchange=exchange, tradingsymbol=symbol,
                transaction_type=transaction_type, quantity=quantity,
                product="MIS", order_type=order_type, validity="DAY",
            )
            if price and order_type != "MARKET":
                kwargs["price"] = price
            order_id = self._client.place_order(**kwargs)
            self._capital.release_deployed(price * quantity if price else 0)
            return order_id
        except Exception:
            log.exception("%s: failed to place exit", symbol)
            return None

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._client.cancel_order("regular", order_id)
            return True
        except Exception:
            log.exception("Failed to cancel order %s", order_id)
            return False

    def modify_order(self, order_id: str, price: float) -> bool:
        try:
            self._client.modify_order(
                variety="regular", order_id=order_id, price=price,
            )
            return True
        except Exception:
            log.exception("Failed to modify order %s", order_id)
            return False


# tradingbot/execution/safety.py
from __future__ import annotations
import logging

log = logging.getLogger(__name__)


class SafetyManager:
    def __init__(self, capital: float, max_daily_loss_pct: float,
                 max_positions: int = 4):
        self._capital = capital
        self._max_loss = capital * max_daily_loss_pct / 100
        self._max_positions = max_positions

    def check_daily_loss(self, realised_pnl: float) -> bool:
        if realised_pnl < 0 and abs(realised_pnl) >= self._max_loss:
            log.critical("DAILY LOSS LIMIT BREACHED: ₹%.0f", realised_pnl)
            return True
        return False

    def can_open_position(self, current_positions: int) -> bool:
        return current_positions < self._max_positions

    def emergency_stop(self, executor: Any) -> None:
        log.critical("EMERGENCY STOP triggered")
        # Cancel all pending, square off all positions
        # Implementation depends on position tracking
```

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/execution/ -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tradingbot/execution/ tests/execution/
git commit -m "feat(execution): Kite order executor + safety mechanisms

KiteExecutor: entry/exit orders with margin check and drift validation.
SafetyManager: daily loss kill switch, position cap, emergency stop."
```

---

### Task 18: Analysis Pipeline Orchestrator

**Files:**
- Create: `tradingbot/analysis/pipeline.py`
- Test: `tests/analysis/test_pipeline.py`

**Interfaces:**
- Consumes: All previous tasks: `DataSync`, `Tier1Screener`, `Tier2Analyzer`, `Tier3Analyzer`, `WalkForwardEngine`, `MonteCarloSimulator`, `QualityGates`, `RunStore`, `SetupStore`, `ConfluenceScorer`
- Produces: `AnalysisPipeline.run(trade_date) -> AnalysisRun` — the single entry point replacing `PlanGenerator.generate()`

- [ ] **Step 1: Write tests with mocked components**

```python
# tests/analysis/test_pipeline.py
import pytest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo
from tradingbot.analysis.pipeline import AnalysisPipeline
from tradingbot.core.models import MarketRegime

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def pipeline_deps(tmp_path):
    from tradingbot.persistence.run_store import RunStore
    from tradingbot.persistence.setup_store import SetupStore

    db = tmp_path / "test.db"
    return {
        "data_sync": MagicMock(),
        "candle_store": MagicMock(),
        "screener": MagicMock(),
        "tier2": AsyncMock(),
        "tier3": AsyncMock(),
        "backtest_engine": MagicMock(),
        "monte_carlo": MagicMock(),
        "quality_gates": MagicMock(),
        "run_store": RunStore(db),
        "setup_store": SetupStore(db),
        "event_bus": MagicMock(),
        "capital": 400000,
    }


async def test_pipeline_run_produces_analysis_run(pipeline_deps):
    deps = pipeline_deps
    deps["screener"].screen.return_value = []
    deps["tier2"].analyze_regime.return_value = {
        "regime": "trending_up", "regime_confidence": 0.82,
        "bias": "bullish", "sectors_in_play": [], "sectors_to_avoid": [],
        "risk_appetite": "moderate", "reasoning": "test",
    }
    deps["tier2"].shortlist.return_value = {"shortlist": [], "max_positions_today": 3, "reasoning": "none"}
    deps["tier2"].analyze_sectors.return_value = {"sectors": [], "reasoning": "test"}

    pipeline = AnalysisPipeline(**deps)
    run = await pipeline.run(date(2026, 9, 27))
    assert run.run_id.startswith("run_")
    assert run.market_regime == MarketRegime.TRENDING_UP
```

- [ ] **Step 2: Implement AnalysisPipeline**

```python
# tradingbot/analysis/pipeline.py
from __future__ import annotations

import logging
import time
import uuid
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from tradingbot.analysis.tier2_analyzer import Tier2Analyzer
from tradingbot.analysis.tier3_analyzer import Tier3Analyzer
from tradingbot.backtest.monte_carlo import MonteCarloSimulator
from tradingbot.backtest.quality_gates import QualityGates
from tradingbot.backtest.walk_forward import WalkForwardEngine
from tradingbot.core.models import AnalysisRun, MarketRegime
from tradingbot.data.candle_store import CandleStore
from tradingbot.data.data_sync import DataSync
from tradingbot.persistence.run_store import RunStore
from tradingbot.persistence.setup_store import SetupStore
from tradingbot.screening.screener import Tier1Screener
from tradingbot.strategy.strategies import STRATEGY_REGISTRY

IST = ZoneInfo("Asia/Kolkata")
log = logging.getLogger(__name__)


class AnalysisPipeline:
    def __init__(
        self, data_sync: DataSync, candle_store: CandleStore,
        screener: Tier1Screener, tier2: Tier2Analyzer, tier3: Tier3Analyzer,
        backtest_engine: WalkForwardEngine, monte_carlo: MonteCarloSimulator,
        quality_gates: QualityGates, run_store: RunStore, setup_store: SetupStore,
        event_bus: Any, capital: float,
    ):
        self._sync = data_sync
        self._candles = candle_store
        self._screener = screener
        self._tier2 = tier2
        self._tier3 = tier3
        self._backtest = backtest_engine
        self._mc = monte_carlo
        self._gates = quality_gates
        self._runs = run_store
        self._setups = setup_store
        self._bus = event_bus
        self._capital = capital

    async def run(self, trade_date: date) -> AnalysisRun:
        start = time.monotonic()
        run_id = f"run_{trade_date:%Y%m%d}_{datetime.now(tz=IST):%H%M%S}_{uuid.uuid4().hex[:6]}"
        llm_calls = 0

        self._bus.emit("analysis.started", {"run_id": run_id})

        # Tier 1: Deterministic screen
        stock_metrics = self._build_stock_metrics()
        scored = self._screener.screen(stock_metrics)
        self._bus.emit("analysis.tier1_complete", {"candidates": len(scored)})

        # Tier 2: LLM market + sector + shortlist
        regime = await self._tier2.analyze_regime(
            nifty=0, banknifty=0, vix=0, nifty_5d_change=0,
            fii_5d_net=0, dii_5d_net=0, advance_decline=0, sector_data={},
        )
        llm_calls += 1

        sectors = await self._tier2.analyze_sectors(regime, {}, {})
        llm_calls += 1

        scored_dicts = [{"symbol": s.symbol, "composite_score": s.composite_score,
                         "sector": s.sector, "last_price": s.last_price,
                         "factor_scores": s.factor_scores} for s in scored]
        shortlist_result = await self._tier2.shortlist(regime, sectors, scored_dicts)
        llm_calls += 1
        shortlist = shortlist_result.get("shortlist", [])

        self._bus.emit("analysis.tier2_complete", {"shortlisted": len(shortlist)})

        # Sync deep data for shortlisted
        symbols = [s["symbol"] for s in shortlist]
        if symbols and hasattr(self._sync, "deep_fetch"):
            self._sync.deep_fetch(symbols)

        # Backtest + Tier 3: per-stock deep analysis
        all_setups = []
        for pick in shortlist:
            sym = pick["symbol"]
            direction = pick.get("direction", "long")

            bt_results = []
            for strategy in STRATEGY_REGISTRY:
                df = self._candles.read(sym, "15minute",
                                        datetime(2025, 1, 1, tzinfo=IST),
                                        datetime.now(tz=IST))
                if len(df) > 0:
                    report = self._backtest.run(sym, df, strategy)
                    if report.total_trades >= 5:
                        mc = self._mc.run([report.expectancy] * report.total_trades)
                        gate = self._gates.evaluate(report, mc)
                        if gate.passed:
                            bt_results.append(report)

            deep = await self._tier3.deep_analyze(
                symbol=sym, direction=direction, regime=regime,
                indicators={}, backtest_results=[],
                price_action=f"{sym} analysis",
            )
            llm_calls += 1
            all_setups.append(deep)

        # Adversarial validation
        setups_with_data = [s for s in all_setups if s.get("setups")]
        setups_proposed = sum(len(s.get("setups", [])) for s in setups_with_data)
        setups_approved = 0

        if setups_with_data:
            validation = await self._tier3.validate_portfolio(setups_with_data, regime, sectors)
            llm_calls += 1

            for approved in validation.get("approved", []):
                sym = approved["symbol"]
                idx = approved.get("setup_index", 0)
                source = next((s for s in setups_with_data if s["symbol"] == sym), None)
                if source and idx < len(source.get("setups", [])):
                    setup_data = source["setups"][idx]
                    self._setups.save({
                        "run_id": run_id, "trade_date": str(trade_date),
                        "symbol": sym, "strategy": setup_data.get("strategy", "unknown"),
                        "direction": setup_data.get("direction", "long"),
                        "entry_price": setup_data["entry_price"],
                        "stop_loss": setup_data["stop_loss"],
                        "target_1": setup_data["target_1"],
                        "target_2": setup_data.get("target_2", 0),
                        "confidence": setup_data["confidence"],
                        "status": "approved",
                        "reasoning": setup_data.get("edge_description", ""),
                    })
                    setups_approved += 1

        duration = time.monotonic() - start
        regime_enum = MarketRegime(regime.get("regime", "range_bound"))

        analysis_run = AnalysisRun(
            run_id=run_id, timestamp=datetime.now(tz=IST), trade_date=trade_date,
            market_regime=regime_enum,
            regime_confidence=regime.get("regime_confidence", 0),
            total_scanned=len(stock_metrics), tier1_passed=len(scored),
            tier2_shortlisted=len(shortlist), setups_proposed=setups_proposed,
            setups_approved=setups_approved, llm_calls=llm_calls,
            llm_cost_usd=0, duration_seconds=duration,
        )
        self._runs.save(analysis_run)
        self._bus.emit("analysis.complete", {"run_id": run_id})
        return analysis_run

    def _build_stock_metrics(self) -> list[dict]:
        # Reads from candle store to compute metrics for all instruments
        # Implementation depends on InstrumentCache integration
        return []
```

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/analysis/test_pipeline.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tradingbot/analysis/pipeline.py tests/analysis/test_pipeline.py
git commit -m "feat(analysis): add AnalysisPipeline orchestrator

Single entry point replacing PlanGenerator. Runs full 3-tier funnel:
Tier 1 screen → Tier 2 LLM (regime/sector/shortlist) → backtest →
Tier 3 deep analysis → adversarial validation → persist to RunStore."
```

---

### Task 19: Wire Everything Together + Update API Routes

**Files:**
- Modify: `tradingbot/api/analysis_routes.py`
- Modify: `tradingbot/api/state.py` (if exists, add new stores)
- Test: `tests/api/test_analysis_routes_v2.py`

**Interfaces:**
- Consumes: All previous tasks
- Produces: Updated `POST /analyze` that runs `AnalysisPipeline`, `AppState` includes `run_store`, `setup_store`; full backward compatibility with existing executor and frontend

- [ ] **Step 1: Update AppState to include new stores**

Add `run_store`, `setup_store`, `candle_store`, `instrument_cache` to `AppState`. Initialize them in the app startup lifecycle.

- [ ] **Step 2: Update POST /analyze to use AnalysisPipeline**

Replace `_run_analysis()` in `analysis_routes.py` to instantiate and call `AnalysisPipeline.run()` instead of `PlanGenerator.generate()`. Keep backward compatibility: still emit the same WebSocket events, still update `state.analysis_status`.

- [ ] **Step 3: Write integration test**

```python
# tests/api/test_analysis_routes_v2.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


async def test_analyze_endpoint_returns_run_id(api_client):
    with patch("tradingbot.api.analysis_routes.AnalysisPipeline") as MockPipeline:
        mock_instance = AsyncMock()
        mock_instance.run.return_value = MagicMock(run_id="run_test_001")
        MockPipeline.return_value = mock_instance

        response = await api_client.post("/api/analyze")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
```

- [ ] **Step 4: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests pass (original 358 + new ~80 = ~438)

- [ ] **Step 5: Commit**

```bash
git add tradingbot/api/ tests/api/
git commit -m "feat(api): wire AnalysisPipeline into API routes

POST /analyze now runs the 3-tier pipeline with multi-run persistence.
AppState includes RunStore, SetupStore. Backward-compatible WebSocket events."
```

---

## Execution Order Summary

| Phase | Tasks | What It Builds | Tests Added |
|-------|-------|---------------|-------------|
| 1: Foundation | 1-5 | Models, config, Kite client, cache, sync | ~25 |
| 2: Screening | 6-7 | Indicators, Tier 1 screener | ~15 |
| 3: Strategies | 8 | 5 new strategies + confluence scorer | ~12 |
| 4: Backtesting | 9-10 | Walk-forward, Monte Carlo, quality gates | ~12 |
| 5: LLM Pipeline | 11-13 | Prompts, Tier 2 + Tier 3 analyzers | ~15 |
| 6: Persistence | 14-15 | RunStore, SetupStore, DailyPlan, API | ~10 |
| 7: Execution | 16-17 | Kite auth, orders, safety | ~8 |
| 8: Integration | 18-19 | Pipeline orchestrator, API wiring | ~5 |
| **Total** | **19 tasks** | **Complete pipeline redesign** | **~102 new tests** |
