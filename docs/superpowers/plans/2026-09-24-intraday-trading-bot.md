# Intraday Trading Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI-driven Python system that scans the NSE equity universe, uses Claude to pick 1-2 intraday trade setups per day, writes them to a JSON trade plan, and executes that plan deterministically during market hours with hard risk limits.

**Architecture:** A single Python package (`tradingbot`) with three logically separated agents. The Scanner and Strategy agents run before market open and write a `TradePlan` JSON artifact to disk. The Executor agent reads that artifact and follows it mechanically with no LLM in the loop. Broker access sits behind a `BrokerInterface` ABC so paper trading and live trading share one code path.

**Tech Stack:** Python 3.12+, kiteconnect (Zerodha), anthropic (Claude Sonnet 5), pandas, numpy, scikit-learn (DBSCAN), click, SQLite (stdlib), httpx, yfinance, pytest, pytest-asyncio, freezegun.

**Spec:** `docs/superpowers/specs/2026-09-23-intraday-trading-bot-design.md`

## Global Constraints

- Python 3.12+ — no syntax or stdlib features newer than 3.12.
- No heavy frameworks: no Django, FastAPI, CrewAI, LangChain, or agent frameworks.
- All timestamps are timezone-aware in `Asia/Kolkata` (IST). Never use naive `datetime`.
- All money values are `float` rupees. Quantities are `int` shares.
- Database is SQLite via stdlib `sqlite3`. No ORM, no external database.
- The executor package (`tradingbot/executor/`) must never import anything under `tradingbot/core/llm/`. This is a hard architectural rule enforced by a test in Task 11.
- LLM model id is exactly `claude-sonnet-5`. LLM calls use `tool_use` for structured output — never regex or free-text parsing.
- Secrets live only in `.env` and are read via `os.environ`. Never commit `.env`; never log secret values.
- Market hours are 09:15–15:30 IST. Hard square-off is 15:10 IST.
- Every module gets a matching test file under `tests/` mirroring the package path.

## Review Focus

These are failure modes the spec implies but does not spell out. Each has a test pinned to the task that owns the code.

1. **Stop loss equal to entry price** — position sizing divides by `(entry - stop_loss)`; a zero denominator must raise a clear error, not crash with `ZeroDivisionError` or emit an infinite quantity. Test lives in Task 7.
2. **LLM returns a symbol that was never in the shortlist** — a hallucinated or renamed ticker must be dropped with a logged warning, not silently traded. Test lives in Task 9.
3. **Executor restarted after an entry already filled** — restarting mid-session must adopt the existing position rather than placing a second entry order. Test lives in Task 11.
4. **Trade plan file missing, malformed, or from a different schema version** — loading must fail loudly with a readable message rather than producing a half-populated `TradePlan`. Test lives in Task 2.
5. **Analysis run for a date that is not a trading day** — a weekend or NSE holiday must abort the run with a clear message instead of generating a plan nobody can execute. Test lives in Task 6.

---

## File Structure

```
tradingbot/
├── __init__.py
├── __main__.py                      # Task 12 — python -m tradingbot entry point
├── cli.py                           # Task 12 — click command group
├── core/
│   ├── __init__.py
│   ├── models.py                    # Task 1 — all dataclasses + enums
│   ├── config.py                    # Task 1 — TOML + env → Config
│   ├── database.py                  # Task 2 — SQLite schema + CRUD
│   ├── plan_store.py                # Task 2 — TradePlan JSON read/write
│   ├── risk_manager.py              # Task 7 — three risk layers
│   ├── broker.py                    # Task 10 — BrokerInterface ABC
│   ├── kite_client.py               # Task 10 — live Zerodha implementation
│   └── llm/
│       ├── __init__.py
│       ├── provider.py              # Task 3 — LLMProvider ABC
│       └── anthropic_provider.py    # Task 3 — Claude implementation
├── scanner/
│   ├── __init__.py
│   ├── calendar.py                  # Task 6 — trading-day checks
│   ├── data_fetcher.py              # Task 5 — universe + candles
│   ├── filters.py                   # Task 5 — deterministic filters
│   ├── market_context.py            # Task 6 — FII/DII, index trend
│   ├── market_analyzer.py           # Task 6 — LLM call 1
│   └── scanner.py                   # Task 6 — orchestration
├── strategy/
│   ├── __init__.py
│   ├── indicators.py                # Task 4 — all technical indicators
│   ├── backtester.py                # Task 9 — per-strategy stats
│   ├── strategy_selector.py         # Task 9 — LLM call 2
│   ├── plan_generator.py            # Task 9 — setups → TradePlan
│   └── strategies/
│       ├── __init__.py              # Task 8 — STRATEGY_REGISTRY
│       ├── base.py                  # Task 8 — Strategy ABC
│       ├── breakout.py              # Task 8
│       ├── momentum.py              # Task 8
│       ├── mean_reversion.py        # Task 8
│       ├── vwap_bounce.py           # Task 8
│       └── orb.py                   # Task 8
├── executor/
│   ├── __init__.py
│   ├── order_manager.py             # Task 11
│   ├── position_monitor.py          # Task 11
│   ├── exit_manager.py              # Task 11
│   └── executor.py                  # Task 11
└── paper/
    ├── __init__.py
    └── virtual_broker.py            # Task 10 — BrokerInterface impl
```

---

## Task 1: Project Setup, Core Models, Config

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `config.toml`
- Create: `tradingbot/__init__.py`, `tradingbot/core/__init__.py`
- Create: `tradingbot/core/models.py`
- Create: `tradingbot/core/config.py`
- Test: `tests/core/test_models.py`, `tests/core/test_config.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - Enums: `Direction` (`LONG`/`SHORT`), `EntryType` (`LIMIT`/`STOP`), `StrategyName` (`BREAKOUT`/`MOMENTUM`/`MEAN_REVERSION`/`VWAP_BOUNCE`/`ORB`), `MarketRegime` (`TRENDING`/`RANGING`/`VOLATILE`/`LOW_VOL`), `TradeStatus` (`PENDING`/`OPEN`/`CLOSED`/`CANCELLED`/`SKIPPED`), `Mode` (`PAPER`/`LIVE`).
  - Dataclasses: `Stock`, `MarketContext`, `ShortlistedStock`, `IndicatorSnapshot`, `BacktestResult`, `TradeSetup`, `TradeLeg`, `TradePlan`, `Position`, `ExecutedTrade`.
  - `IST: ZoneInfo` constant and `now_ist() -> datetime`.
  - `Config` dataclass with nested `GeneralConfig`, `ScannerConfig`, `StrategyConfig`, `RiskConfig`, `ExecutionConfig`, `LLMConfig`, `PaperConfig`, plus `Secrets`.
  - `load_config(config_path: Path | None = None) -> Config`.

- [ ] **Step 1: Create the package skeleton and dependency manifest**

Create `pyproject.toml`:

```toml
[project]
name = "tradingbot"
version = "0.1.0"
description = "Automated intraday equity trading bot for Indian markets"
requires-python = ">=3.12"
dependencies = [
    "kiteconnect>=5.0.1",
    "anthropic>=0.40.0",
    "pandas>=2.2.0",
    "numpy>=1.26.0",
    "scikit-learn>=1.5.0",
    "click>=8.1.0",
    "httpx>=0.27.0",
    "python-dotenv>=1.0.0",
    "yfinance>=0.2.40",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "freezegun>=1.5.0",
]

[project.scripts]
tradingbot = "tradingbot.cli:cli"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

Create `.gitignore`:

```
__pycache__/
*.py[cod]
.venv/
venv/
.env
*.db
*.sqlite3
trade_plans/
logs/
.pytest_cache/
*.egg-info/
```

Create `.env.example`:

```
ANTHROPIC_API_KEY=sk-ant-replace-me
KITE_API_KEY=replace-me
KITE_API_SECRET=replace-me
```

Create empty `tradingbot/__init__.py`, `tradingbot/core/__init__.py`, `tests/__init__.py`, `tests/core/__init__.py`.

- [ ] **Step 2: Write the failing test for models**

Create `tests/core/test_models.py`:

```python
from datetime import datetime, time

import pytest

from tradingbot.core.models import (
    IST,
    Direction,
    EntryType,
    MarketRegime,
    StrategyName,
    TradeLeg,
    TradePlan,
    TradeSetup,
    TradeStatus,
    now_ist,
)


def test_now_ist_is_timezone_aware_and_in_kolkata():
    ts = now_ist()
    assert ts.tzinfo is not None
    assert ts.utcoffset().total_seconds() == 5.5 * 3600


def test_trade_leg_round_trips_through_dict():
    leg = TradeLeg(
        symbol="RELIANCE",
        exchange="NSE",
        strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG,
        entry_price=2855.0,
        entry_type=EntryType.LIMIT,
        stop_loss=2830.0,
        target_1=2890.0,
        target_2=2920.0,
        quantity=16,
        risk_amount=4000.0,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        max_entry_wait=time(11, 0),
        exit_before=time(15, 10),
        confidence=0.72,
        reasoning="Breaking out of consolidation.",
    )
    restored = TradeLeg.from_dict(leg.to_dict())
    assert restored == leg


def test_trade_leg_reward_risk_uses_target_1():
    leg = TradeLeg(
        symbol="TCS",
        exchange="NSE",
        strategy=StrategyName.MOMENTUM,
        direction=Direction.LONG,
        entry_price=100.0,
        entry_type=EntryType.LIMIT,
        stop_loss=90.0,
        target_1=120.0,
        target_2=130.0,
        quantity=10,
        risk_amount=100.0,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        max_entry_wait=time(11, 0),
        exit_before=time(15, 10),
        confidence=0.6,
        reasoning="Momentum continuation.",
    )
    assert leg.reward_risk == pytest.approx(2.0)


def test_short_leg_reward_risk_uses_absolute_distances():
    leg = TradeLeg(
        symbol="INFY",
        exchange="NSE",
        strategy=StrategyName.MEAN_REVERSION,
        direction=Direction.SHORT,
        entry_price=100.0,
        entry_type=EntryType.LIMIT,
        stop_loss=110.0,
        target_1=85.0,
        target_2=80.0,
        quantity=10,
        risk_amount=100.0,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        max_entry_wait=time(11, 0),
        exit_before=time(15, 10),
        confidence=0.6,
        reasoning="Overextended, reverting to mean.",
    )
    assert leg.reward_risk == pytest.approx(1.5)


def test_trade_plan_round_trips_through_dict():
    setup = TradeSetup(
        symbol="RELIANCE",
        strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG,
        entry_price=2855.0,
        entry_type=EntryType.LIMIT,
        stop_loss=2830.0,
        target_1=2890.0,
        target_2=2920.0,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        confidence=0.72,
        reasoning="Breaking out of consolidation.",
    )
    leg = setup.to_leg(quantity=16, risk_amount=4000.0, max_entry_wait=time(11, 0), exit_before=time(15, 10))
    plan = TradePlan(
        trade_date="2026-09-24",
        generated_at=datetime(2026, 9, 23, 22, 30, tzinfo=IST),
        capital=400000.0,
        max_risk_per_trade_pct=0.01,
        max_daily_loss_pct=0.02,
        market_regime=MarketRegime.TRENDING,
        market_summary="Nifty bullish, IT leading.",
        legs=[leg],
    )
    restored = TradePlan.from_dict(plan.to_dict())
    assert restored == plan
    assert restored.legs[0].symbol == "RELIANCE"


def test_trade_plan_age_hours_measured_from_generated_at():
    plan = TradePlan(
        trade_date="2026-09-24",
        generated_at=datetime(2026, 9, 23, 22, 0, tzinfo=IST),
        capital=400000.0,
        max_risk_per_trade_pct=0.01,
        max_daily_loss_pct=0.02,
        market_regime=MarketRegime.TRENDING,
        market_summary="Nifty bullish.",
        legs=[],
    )
    reference = datetime(2026, 9, 24, 9, 0, tzinfo=IST)
    assert plan.age_hours(reference) == pytest.approx(11.0)


def test_trade_status_enum_values_are_stable_strings():
    assert TradeStatus.PENDING.value == "pending"
    assert TradeStatus.OPEN.value == "open"
    assert TradeStatus.CLOSED.value == "closed"
    assert TradeStatus.CANCELLED.value == "cancelled"
    assert TradeStatus.SKIPPED.value == "skipped"
```

- [ ] **Step 3: Run the model tests to verify they fail**

Run: `pytest tests/core/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.core.models'`

- [ ] **Step 4: Implement the models module**

Create `tradingbot/core/models.py`:

```python
"""Core data structures shared by every agent in the system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

PLAN_SCHEMA_VERSION = 1


def now_ist() -> datetime:
    """Current wall-clock time in Indian Standard Time."""
    return datetime.now(tz=IST)


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


class EntryType(str, Enum):
    LIMIT = "limit"
    STOP = "stop"


class StrategyName(str, Enum):
    BREAKOUT = "breakout"
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    VWAP_BOUNCE = "vwap_bounce"
    ORB = "orb"


class MarketRegime(str, Enum):
    TRENDING = "trending"
    RANGING = "ranging"
    VOLATILE = "volatile"
    LOW_VOL = "low_vol"


class TradeStatus(str, Enum):
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class Mode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


def _fmt_time(value: time) -> str:
    return value.strftime("%H:%M")


def _parse_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


@dataclass(frozen=True)
class Stock:
    """One tradable instrument with the metrics the scanner filters on."""

    symbol: str
    exchange: str
    last_price: float
    avg_volume: float
    market_cap_cr: float
    atr_pct: float
    sector: str


@dataclass(frozen=True)
class MarketContext:
    """Macro picture handed to the LLM alongside the candidate list."""

    nifty_level: float
    nifty_trend: str
    banknifty_trend: str
    india_vix: float
    fii_net_cr: float
    dii_net_cr: float
    global_cues: str
    sector_leaders: list[str]
    sector_laggards: list[str]
    regime: MarketRegime

    def to_dict(self) -> dict[str, Any]:
        return {
            "nifty_level": self.nifty_level,
            "nifty_trend": self.nifty_trend,
            "banknifty_trend": self.banknifty_trend,
            "india_vix": self.india_vix,
            "fii_net_cr": self.fii_net_cr,
            "dii_net_cr": self.dii_net_cr,
            "global_cues": self.global_cues,
            "sector_leaders": list(self.sector_leaders),
            "sector_laggards": list(self.sector_laggards),
            "regime": self.regime.value,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> MarketContext:
        return cls(
            nifty_level=float(raw["nifty_level"]),
            nifty_trend=raw["nifty_trend"],
            banknifty_trend=raw["banknifty_trend"],
            india_vix=float(raw["india_vix"]),
            fii_net_cr=float(raw["fii_net_cr"]),
            dii_net_cr=float(raw["dii_net_cr"]),
            global_cues=raw["global_cues"],
            sector_leaders=list(raw["sector_leaders"]),
            sector_laggards=list(raw["sector_laggards"]),
            regime=MarketRegime(raw["regime"]),
        )


@dataclass(frozen=True)
class ShortlistedStock:
    """A stock the LLM picked out of the filtered candidate pool."""

    symbol: str
    reasoning: str
    suggested_strategy: StrategyName
    direction_bias: str
    key_levels: list[float]


@dataclass(frozen=True)
class IndicatorSnapshot:
    """Indicator values for one symbol at the moment of analysis."""

    symbol: str
    last_close: float
    rsi_14: float
    macd: float
    macd_signal: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    atr_14: float
    sma_20: float
    sma_50: float
    sma_200: float
    ema_12: float
    ema_26: float
    vwap: float
    pivot: float
    support_levels: list[float]
    resistance_levels: list[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "last_close": self.last_close,
            "rsi_14": self.rsi_14,
            "macd": self.macd,
            "macd_signal": self.macd_signal,
            "bb_upper": self.bb_upper,
            "bb_middle": self.bb_middle,
            "bb_lower": self.bb_lower,
            "atr_14": self.atr_14,
            "sma_20": self.sma_20,
            "sma_50": self.sma_50,
            "sma_200": self.sma_200,
            "ema_12": self.ema_12,
            "ema_26": self.ema_26,
            "vwap": self.vwap,
            "pivot": self.pivot,
            "support_levels": list(self.support_levels),
            "resistance_levels": list(self.resistance_levels),
        }


@dataclass(frozen=True)
class BacktestResult:
    """How one strategy performed on one symbol over the lookback window."""

    symbol: str
    strategy: StrategyName
    trades: int
    wins: int
    win_rate: float
    avg_reward_risk: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "strategy": self.strategy.value,
            "trades": self.trades,
            "wins": self.wins,
            "win_rate": self.win_rate,
            "avg_reward_risk": self.avg_reward_risk,
        }


@dataclass(frozen=True)
class TradeSetup:
    """An LLM-designed setup before risk sizing has been applied."""

    symbol: str
    strategy: StrategyName
    direction: Direction
    entry_price: float
    entry_type: EntryType
    stop_loss: float
    target_1: float
    target_2: float
    entry_window_start: time
    entry_window_end: time
    confidence: float
    reasoning: str

    @property
    def risk_per_share(self) -> float:
        return abs(self.entry_price - self.stop_loss)

    @property
    def reward_risk(self) -> float:
        risk = self.risk_per_share
        if risk == 0:
            return 0.0
        return abs(self.target_1 - self.entry_price) / risk

    def to_leg(
        self,
        quantity: int,
        risk_amount: float,
        max_entry_wait: time,
        exit_before: time,
        exchange: str = "NSE",
    ) -> TradeLeg:
        return TradeLeg(
            symbol=self.symbol,
            exchange=exchange,
            strategy=self.strategy,
            direction=self.direction,
            entry_price=self.entry_price,
            entry_type=self.entry_type,
            stop_loss=self.stop_loss,
            target_1=self.target_1,
            target_2=self.target_2,
            quantity=quantity,
            risk_amount=risk_amount,
            entry_window_start=self.entry_window_start,
            entry_window_end=self.entry_window_end,
            max_entry_wait=max_entry_wait,
            exit_before=exit_before,
            confidence=self.confidence,
            reasoning=self.reasoning,
        )


@dataclass(frozen=True)
class TradeLeg:
    """A fully sized, executable trade instruction."""

    symbol: str
    exchange: str
    strategy: StrategyName
    direction: Direction
    entry_price: float
    entry_type: EntryType
    stop_loss: float
    target_1: float
    target_2: float
    quantity: int
    risk_amount: float
    entry_window_start: time
    entry_window_end: time
    max_entry_wait: time
    exit_before: time
    confidence: float
    reasoning: str

    @property
    def risk_per_share(self) -> float:
        return abs(self.entry_price - self.stop_loss)

    @property
    def reward_risk(self) -> float:
        risk = self.risk_per_share
        if risk == 0:
            return 0.0
        return abs(self.target_1 - self.entry_price) / risk

    @property
    def notional(self) -> float:
        return self.entry_price * self.quantity

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "strategy": self.strategy.value,
            "direction": self.direction.value,
            "entry_price": self.entry_price,
            "entry_type": self.entry_type.value,
            "stop_loss": self.stop_loss,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "quantity": self.quantity,
            "risk_amount": self.risk_amount,
            "entry_window_start": _fmt_time(self.entry_window_start),
            "entry_window_end": _fmt_time(self.entry_window_end),
            "max_entry_wait": _fmt_time(self.max_entry_wait),
            "exit_before": _fmt_time(self.exit_before),
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TradeLeg:
        return cls(
            symbol=raw["symbol"],
            exchange=raw["exchange"],
            strategy=StrategyName(raw["strategy"]),
            direction=Direction(raw["direction"]),
            entry_price=float(raw["entry_price"]),
            entry_type=EntryType(raw["entry_type"]),
            stop_loss=float(raw["stop_loss"]),
            target_1=float(raw["target_1"]),
            target_2=float(raw["target_2"]),
            quantity=int(raw["quantity"]),
            risk_amount=float(raw["risk_amount"]),
            entry_window_start=_parse_time(raw["entry_window_start"]),
            entry_window_end=_parse_time(raw["entry_window_end"]),
            max_entry_wait=_parse_time(raw["max_entry_wait"]),
            exit_before=_parse_time(raw["exit_before"]),
            confidence=float(raw["confidence"]),
            reasoning=raw["reasoning"],
        )


@dataclass(frozen=True)
class TradePlan:
    """The artifact analysis writes and execution reads."""

    trade_date: str
    generated_at: datetime
    capital: float
    max_risk_per_trade_pct: float
    max_daily_loss_pct: float
    market_regime: MarketRegime
    market_summary: str
    legs: list[TradeLeg] = field(default_factory=list)
    schema_version: int = PLAN_SCHEMA_VERSION

    def age_hours(self, reference: datetime) -> float:
        return (reference - self.generated_at).total_seconds() / 3600.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "trade_date": self.trade_date,
            "generated_at": self.generated_at.isoformat(),
            "capital": self.capital,
            "max_risk_per_trade_pct": self.max_risk_per_trade_pct,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "market_regime": self.market_regime.value,
            "market_summary": self.market_summary,
            "legs": [leg.to_dict() for leg in self.legs],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TradePlan:
        return cls(
            schema_version=int(raw.get("schema_version", PLAN_SCHEMA_VERSION)),
            trade_date=raw["trade_date"],
            generated_at=datetime.fromisoformat(raw["generated_at"]),
            capital=float(raw["capital"]),
            max_risk_per_trade_pct=float(raw["max_risk_per_trade_pct"]),
            max_daily_loss_pct=float(raw["max_daily_loss_pct"]),
            market_regime=MarketRegime(raw["market_regime"]),
            market_summary=raw["market_summary"],
            legs=[TradeLeg.from_dict(item) for item in raw["legs"]],
        )


@dataclass
class Position:
    """A live or simulated holding the executor is managing."""

    symbol: str
    direction: Direction
    quantity: int
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    entered_at: datetime
    target_1_booked: bool = False

    def unrealised_pnl(self, last_price: float) -> float:
        delta = last_price - self.entry_price
        if self.direction is Direction.SHORT:
            delta = -delta
        return delta * self.quantity


@dataclass
class ExecutedTrade:
    """A completed round trip, written to the database for history."""

    trade_date: str
    symbol: str
    strategy: StrategyName
    direction: Direction
    quantity: int
    entry_price: float
    exit_price: float
    stop_loss: float
    target_1: float
    target_2: float
    entered_at: datetime
    exited_at: datetime
    pnl: float
    exit_reason: str
    status: TradeStatus
    mode: Mode
```

- [ ] **Step 5: Run the model tests to verify they pass**

Run: `pytest tests/core/test_models.py -v`
Expected: PASS — 7 tests.

- [ ] **Step 6: Write the failing test for config**

Create `tests/core/test_config.py`:

```python
import pytest

from tradingbot.core.config import ConfigError, load_config
from tradingbot.core.models import Mode

CONFIG_TEXT = """
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
max_entry_price_drift_pct = 2.0

[llm]
provider = "anthropic"
model = "claude-sonnet-5"
timeout_sec = 60
max_retries = 1

[paper]
slippage_pct = 0.05
initial_capital = 400000
"""


@pytest.fixture()
def config_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG_TEXT)
    return path


def test_load_config_parses_every_section(config_file, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("KITE_API_KEY", "kite-key")
    monkeypatch.setenv("KITE_API_SECRET", "kite-secret")

    config = load_config(config_file)

    assert config.general.mode is Mode.PAPER
    assert config.general.capital == 400000.0
    assert config.scanner.min_volume == 500000
    assert config.strategy.max_trades_per_day == 2
    assert config.risk.max_risk_per_trade_pct == 0.01
    assert config.execution.square_off_time.hour == 15
    assert config.execution.square_off_time.minute == 10
    assert config.llm.model == "claude-sonnet-5"
    assert config.paper.slippage_pct == 0.05
    assert config.secrets.anthropic_api_key == "sk-ant-test"


def test_missing_anthropic_key_raises_config_error(config_file, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("KITE_API_KEY", "kite-key")
    monkeypatch.setenv("KITE_API_SECRET", "kite-secret")

    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        load_config(config_file)


def test_missing_config_file_raises_config_error(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("KITE_API_KEY", "kite-key")
    monkeypatch.setenv("KITE_API_SECRET", "kite-secret")

    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.toml")


def test_invalid_mode_raises_config_error(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("KITE_API_KEY", "kite-key")
    monkeypatch.setenv("KITE_API_SECRET", "kite-secret")
    path = tmp_path / "config.toml"
    path.write_text(CONFIG_TEXT.replace('mode = "paper"', 'mode = "turbo"'))

    with pytest.raises(ConfigError, match="mode"):
        load_config(path)


def test_secrets_are_not_present_in_repr(config_file, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-super-secret")
    monkeypatch.setenv("KITE_API_KEY", "kite-key")
    monkeypatch.setenv("KITE_API_SECRET", "kite-secret")

    config = load_config(config_file)

    assert "sk-ant-super-secret" not in repr(config)
    assert "kite-secret" not in repr(config)
```

- [ ] **Step 7: Run the config tests to verify they fail**

Run: `pytest tests/core/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.core.config'`

- [ ] **Step 8: Implement the config module**

Create `tradingbot/core/config.py`:

```python
"""Configuration loading: TOML for settings, environment for secrets."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

from dotenv import load_dotenv

from tradingbot.core.models import Mode

DEFAULT_CONFIG_PATH = Path("config.toml")


class ConfigError(Exception):
    """Raised when configuration is missing, malformed, or invalid."""


@dataclass(frozen=True)
class GeneralConfig:
    mode: Mode
    capital: float
    log_level: str


@dataclass(frozen=True)
class ScannerConfig:
    min_volume: int
    min_price: float
    max_price: float
    min_market_cap_cr: float
    min_atr_pct: float
    max_stocks_to_llm: int
    llm_pick_count: int


@dataclass(frozen=True)
class StrategyConfig:
    backtest_days: int
    candle_interval: str
    min_confidence: float
    min_reward_risk: float
    max_trades_per_day: int


@dataclass(frozen=True)
class RiskConfig:
    max_risk_per_trade_pct: float
    max_daily_loss_pct: float
    max_capital_deployed_pct: float
    max_concurrent_positions: int


@dataclass(frozen=True)
class ExecutionConfig:
    entry_slippage_pct: float
    square_off_time: time
    connection_timeout_sec: int
    heartbeat_interval_sec: int
    plan_max_age_hours: float
    max_entry_price_drift_pct: float


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    timeout_sec: int
    max_retries: int


@dataclass(frozen=True)
class PaperConfig:
    slippage_pct: float
    initial_capital: float


@dataclass(frozen=True)
class Secrets:
    anthropic_api_key: str = field(repr=False)
    kite_api_key: str = field(repr=False)
    kite_api_secret: str = field(repr=False)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "Secrets(<redacted>)"


@dataclass(frozen=True)
class Config:
    general: GeneralConfig
    scanner: ScannerConfig
    strategy: StrategyConfig
    risk: RiskConfig
    execution: ExecutionConfig
    llm: LLMConfig
    paper: PaperConfig
    secrets: Secrets


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is not set. Copy .env.example to .env and fill it in.")
    return value


def _parse_time(raw: str, key: str) -> time:
    try:
        hour, minute = raw.split(":")
        return time(int(hour), int(minute))
    except (ValueError, AttributeError) as exc:
        raise ConfigError(f"{key} must look like 'HH:MM', got {raw!r}") from exc


def _section(data: dict, name: str) -> dict:
    if name not in data:
        raise ConfigError(f"config is missing the [{name}] section")
    return data[name]


def load_config(config_path: Path | None = None) -> Config:
    """Read settings from TOML and secrets from the environment."""
    load_dotenv()
    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise ConfigError(f"config file not found at {path}")

    with path.open("rb") as handle:
        data = tomllib.load(handle)

    general_raw = _section(data, "general")
    try:
        mode = Mode(general_raw["mode"])
    except ValueError as exc:
        raise ConfigError(
            f"general.mode must be 'paper' or 'live', got {general_raw['mode']!r}"
        ) from exc

    scanner_raw = _section(data, "scanner")
    strategy_raw = _section(data, "strategy")
    risk_raw = _section(data, "risk")
    execution_raw = _section(data, "execution")
    llm_raw = _section(data, "llm")
    paper_raw = _section(data, "paper")

    return Config(
        general=GeneralConfig(
            mode=mode,
            capital=float(general_raw["capital"]),
            log_level=general_raw["log_level"],
        ),
        scanner=ScannerConfig(
            min_volume=int(scanner_raw["min_volume"]),
            min_price=float(scanner_raw["min_price"]),
            max_price=float(scanner_raw["max_price"]),
            min_market_cap_cr=float(scanner_raw["min_market_cap_cr"]),
            min_atr_pct=float(scanner_raw["min_atr_pct"]),
            max_stocks_to_llm=int(scanner_raw["max_stocks_to_llm"]),
            llm_pick_count=int(scanner_raw["llm_pick_count"]),
        ),
        strategy=StrategyConfig(
            backtest_days=int(strategy_raw["backtest_days"]),
            candle_interval=strategy_raw["candle_interval"],
            min_confidence=float(strategy_raw["min_confidence"]),
            min_reward_risk=float(strategy_raw["min_reward_risk"]),
            max_trades_per_day=int(strategy_raw["max_trades_per_day"]),
        ),
        risk=RiskConfig(
            max_risk_per_trade_pct=float(risk_raw["max_risk_per_trade_pct"]),
            max_daily_loss_pct=float(risk_raw["max_daily_loss_pct"]),
            max_capital_deployed_pct=float(risk_raw["max_capital_deployed_pct"]),
            max_concurrent_positions=int(risk_raw["max_concurrent_positions"]),
        ),
        execution=ExecutionConfig(
            entry_slippage_pct=float(execution_raw["entry_slippage_pct"]),
            square_off_time=_parse_time(
                execution_raw["square_off_time"], "execution.square_off_time"
            ),
            connection_timeout_sec=int(execution_raw["connection_timeout_sec"]),
            heartbeat_interval_sec=int(execution_raw["heartbeat_interval_sec"]),
            plan_max_age_hours=float(execution_raw["plan_max_age_hours"]),
            max_entry_price_drift_pct=float(execution_raw["max_entry_price_drift_pct"]),
        ),
        llm=LLMConfig(
            provider=llm_raw["provider"],
            model=llm_raw["model"],
            timeout_sec=int(llm_raw["timeout_sec"]),
            max_retries=int(llm_raw["max_retries"]),
        ),
        paper=PaperConfig(
            slippage_pct=float(paper_raw["slippage_pct"]),
            initial_capital=float(paper_raw["initial_capital"]),
        ),
        secrets=Secrets(
            anthropic_api_key=_require_env("ANTHROPIC_API_KEY"),
            kite_api_key=_require_env("KITE_API_KEY"),
            kite_api_secret=_require_env("KITE_API_SECRET"),
        ),
    )
```

- [ ] **Step 9: Create the real config.toml**

Create `config.toml` at the repository root with exactly the content used in the test fixture (the `CONFIG_TEXT` string in `tests/core/test_config.py`, minus the leading newline).

- [ ] **Step 10: Run the full test suite to verify it passes**

Run: `pytest tests/ -v`
Expected: PASS — 12 tests.

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml .gitignore .env.example config.toml tradingbot/ tests/
git commit -m "feat: add project skeleton, core models, and config loading"
```

---

## Task 2: Persistence — Database and Plan Store

**Files:**
- Create: `tradingbot/core/database.py`
- Create: `tradingbot/core/plan_store.py`
- Test: `tests/core/test_database.py`, `tests/core/test_plan_store.py`

**Interfaces:**
- Consumes: `TradePlan`, `TradeLeg`, `ExecutedTrade`, `StrategyName`, `Direction`, `TradeStatus`, `Mode`, `IST`, `PLAN_SCHEMA_VERSION` from `tradingbot.core.models` (Task 1).
- Produces:
  - `Database(db_path: Path)` with `initialise() -> None`, `record_trade(trade: ExecutedTrade) -> int`, `trades_for_date(trade_date: str) -> list[ExecutedTrade]`, `recent_trades(days: int, today: date) -> list[ExecutedTrade]`, `realised_pnl_for_date(trade_date: str) -> float`, `save_plan_snapshot(plan: TradePlan) -> None`, `close() -> None`.
  - `PlanStore(plan_dir: Path)` with `save(plan: TradePlan) -> Path`, `load(trade_date: str) -> TradePlan`, `load_latest() -> TradePlan`, `path_for(trade_date: str) -> Path`.
  - `PlanNotFoundError`, `PlanCorruptError` exceptions.

- [ ] **Step 1: Write the failing test for the database**

Create `tests/core/test_database.py`:

```python
from datetime import date, datetime

import pytest

from tradingbot.core.database import Database
from tradingbot.core.models import (
    IST,
    Direction,
    ExecutedTrade,
    MarketRegime,
    Mode,
    StrategyName,
    TradePlan,
    TradeStatus,
)


def make_trade(trade_date: str, symbol: str, pnl: float) -> ExecutedTrade:
    return ExecutedTrade(
        trade_date=trade_date,
        symbol=symbol,
        strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG,
        quantity=10,
        entry_price=100.0,
        exit_price=100.0 + pnl / 10,
        stop_loss=95.0,
        target_1=110.0,
        target_2=115.0,
        entered_at=datetime(2026, 9, 24, 9, 45, tzinfo=IST),
        exited_at=datetime(2026, 9, 24, 13, 15, tzinfo=IST),
        pnl=pnl,
        exit_reason="target_1",
        status=TradeStatus.CLOSED,
        mode=Mode.PAPER,
    )


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialise()
    yield database
    database.close()


def test_initialise_is_idempotent(tmp_path):
    database = Database(tmp_path / "twice.db")
    database.initialise()
    database.initialise()
    database.close()


def test_record_and_read_back_a_trade(db):
    trade = make_trade("2026-09-24", "RELIANCE", 1040.0)
    trade_id = db.record_trade(trade)
    assert trade_id > 0

    stored = db.trades_for_date("2026-09-24")
    assert len(stored) == 1
    assert stored[0].symbol == "RELIANCE"
    assert stored[0].pnl == pytest.approx(1040.0)
    assert stored[0].strategy is StrategyName.BREAKOUT
    assert stored[0].mode is Mode.PAPER
    assert stored[0].entered_at.tzinfo is not None


def test_realised_pnl_sums_all_trades_for_the_day(db):
    db.record_trade(make_trade("2026-09-24", "RELIANCE", 1000.0))
    db.record_trade(make_trade("2026-09-24", "TCS", -400.0))
    db.record_trade(make_trade("2026-09-25", "INFY", 9999.0))

    assert db.realised_pnl_for_date("2026-09-24") == pytest.approx(600.0)


def test_realised_pnl_for_a_day_with_no_trades_is_zero(db):
    assert db.realised_pnl_for_date("2026-01-01") == pytest.approx(0.0)


def test_recent_trades_respects_the_lookback_window(db):
    db.record_trade(make_trade("2026-09-24", "RELIANCE", 100.0))
    db.record_trade(make_trade("2026-09-10", "TCS", 200.0))

    recent = db.recent_trades(days=7, today=date(2026, 9, 24))

    assert [trade.symbol for trade in recent] == ["RELIANCE"]


def test_save_plan_snapshot_stores_one_row_per_trade_date(db):
    plan = TradePlan(
        trade_date="2026-09-24",
        generated_at=datetime(2026, 9, 23, 22, 0, tzinfo=IST),
        capital=400000.0,
        max_risk_per_trade_pct=0.01,
        max_daily_loss_pct=0.02,
        market_regime=MarketRegime.TRENDING,
        market_summary="Nifty bullish.",
        legs=[],
    )
    db.save_plan_snapshot(plan)
    db.save_plan_snapshot(plan)

    cursor = db.connection.execute("SELECT COUNT(*) FROM plan_snapshots WHERE trade_date = ?", ("2026-09-24",))
    assert cursor.fetchone()[0] == 1
```

- [ ] **Step 2: Run the database tests to verify they fail**

Run: `pytest tests/core/test_database.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.core.database'`

- [ ] **Step 3: Implement the database module**

Create `tradingbot/core/database.py`:

```python
"""SQLite persistence for executed trades and plan snapshots."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from tradingbot.core.models import (
    Direction,
    ExecutedTrade,
    Mode,
    StrategyName,
    TradePlan,
    TradeStatus,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    direction TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    target_1 REAL NOT NULL,
    target_2 REAL NOT NULL,
    entered_at TEXT NOT NULL,
    exited_at TEXT NOT NULL,
    pnl REAL NOT NULL,
    exit_reason TEXT NOT NULL,
    status TEXT NOT NULL,
    mode TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trades_date ON trades (trade_date);

CREATE TABLE IF NOT EXISTS plan_snapshots (
    trade_date TEXT PRIMARY KEY,
    generated_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


class Database:
    """Thin wrapper over a SQLite file. One instance per process."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row

    def initialise(self) -> None:
        """Create tables if they do not exist. Safe to call repeatedly."""
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def record_trade(self, trade: ExecutedTrade) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO trades (
                trade_date, symbol, strategy, direction, quantity,
                entry_price, exit_price, stop_loss, target_1, target_2,
                entered_at, exited_at, pnl, exit_reason, status, mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.trade_date,
                trade.symbol,
                trade.strategy.value,
                trade.direction.value,
                trade.quantity,
                trade.entry_price,
                trade.exit_price,
                trade.stop_loss,
                trade.target_1,
                trade.target_2,
                trade.entered_at.isoformat(),
                trade.exited_at.isoformat(),
                trade.pnl,
                trade.exit_reason,
                trade.status.value,
                trade.mode.value,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def trades_for_date(self, trade_date: str) -> list[ExecutedTrade]:
        rows = self.connection.execute(
            "SELECT * FROM trades WHERE trade_date = ? ORDER BY id",
            (trade_date,),
        ).fetchall()
        return [self._row_to_trade(row) for row in rows]

    def recent_trades(self, days: int, today: date) -> list[ExecutedTrade]:
        cutoff = (today - timedelta(days=days)).isoformat()
        rows = self.connection.execute(
            "SELECT * FROM trades WHERE trade_date >= ? ORDER BY trade_date, id",
            (cutoff,),
        ).fetchall()
        return [self._row_to_trade(row) for row in rows]

    def realised_pnl_for_date(self, trade_date: str) -> float:
        row = self.connection.execute(
            "SELECT COALESCE(SUM(pnl), 0.0) AS total FROM trades WHERE trade_date = ?",
            (trade_date,),
        ).fetchone()
        return float(row["total"])

    def save_plan_snapshot(self, plan: TradePlan) -> None:
        self.connection.execute(
            """
            INSERT INTO plan_snapshots (trade_date, generated_at, payload)
            VALUES (?, ?, ?)
            ON CONFLICT(trade_date) DO UPDATE SET
                generated_at = excluded.generated_at,
                payload = excluded.payload
            """,
            (plan.trade_date, plan.generated_at.isoformat(), json.dumps(plan.to_dict())),
        )
        self.connection.commit()

    @staticmethod
    def _row_to_trade(row: sqlite3.Row) -> ExecutedTrade:
        return ExecutedTrade(
            trade_date=row["trade_date"],
            symbol=row["symbol"],
            strategy=StrategyName(row["strategy"]),
            direction=Direction(row["direction"]),
            quantity=int(row["quantity"]),
            entry_price=float(row["entry_price"]),
            exit_price=float(row["exit_price"]),
            stop_loss=float(row["stop_loss"]),
            target_1=float(row["target_1"]),
            target_2=float(row["target_2"]),
            entered_at=datetime.fromisoformat(row["entered_at"]),
            exited_at=datetime.fromisoformat(row["exited_at"]),
            pnl=float(row["pnl"]),
            exit_reason=row["exit_reason"],
            status=TradeStatus(row["status"]),
            mode=Mode(row["mode"]),
        )
```

- [ ] **Step 4: Run the database tests to verify they pass**

Run: `pytest tests/core/test_database.py -v`
Expected: PASS — 6 tests.

- [ ] **Step 5: Write the failing test for the plan store (covers Review Focus item 4)**

Create `tests/core/test_plan_store.py`:

```python
import json
from datetime import datetime, time

import pytest

from tradingbot.core.models import (
    IST,
    Direction,
    EntryType,
    MarketRegime,
    StrategyName,
    TradeLeg,
    TradePlan,
)
from tradingbot.core.plan_store import PlanCorruptError, PlanNotFoundError, PlanStore


def make_plan(trade_date: str = "2026-09-24") -> TradePlan:
    leg = TradeLeg(
        symbol="RELIANCE",
        exchange="NSE",
        strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG,
        entry_price=2855.0,
        entry_type=EntryType.LIMIT,
        stop_loss=2830.0,
        target_1=2890.0,
        target_2=2920.0,
        quantity=16,
        risk_amount=4000.0,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        max_entry_wait=time(11, 0),
        exit_before=time(15, 10),
        confidence=0.72,
        reasoning="Breaking out.",
    )
    return TradePlan(
        trade_date=trade_date,
        generated_at=datetime(2026, 9, 23, 22, 30, tzinfo=IST),
        capital=400000.0,
        max_risk_per_trade_pct=0.01,
        max_daily_loss_pct=0.02,
        market_regime=MarketRegime.TRENDING,
        market_summary="Nifty bullish.",
        legs=[leg],
    )


def test_save_then_load_returns_an_identical_plan(tmp_path):
    store = PlanStore(tmp_path)
    plan = make_plan()

    written = store.save(plan)

    assert written.name == "2026-09-24.json"
    assert store.load("2026-09-24") == plan


def test_load_latest_picks_the_newest_trade_date(tmp_path):
    store = PlanStore(tmp_path)
    store.save(make_plan("2026-09-22"))
    store.save(make_plan("2026-09-24"))
    store.save(make_plan("2026-09-23"))

    assert store.load_latest().trade_date == "2026-09-24"


def test_load_missing_plan_raises_plan_not_found(tmp_path):
    store = PlanStore(tmp_path)

    with pytest.raises(PlanNotFoundError, match="2026-09-24"):
        store.load("2026-09-24")


def test_load_latest_with_no_plans_raises_plan_not_found(tmp_path):
    store = PlanStore(tmp_path)

    with pytest.raises(PlanNotFoundError, match="no trade plans"):
        store.load_latest()


def test_malformed_json_raises_plan_corrupt(tmp_path):
    store = PlanStore(tmp_path)
    (tmp_path / "2026-09-24.json").write_text("{not valid json")

    with pytest.raises(PlanCorruptError, match="could not be parsed"):
        store.load("2026-09-24")


def test_plan_missing_required_field_raises_plan_corrupt(tmp_path):
    store = PlanStore(tmp_path)
    payload = make_plan().to_dict()
    del payload["capital"]
    (tmp_path / "2026-09-24.json").write_text(json.dumps(payload))

    with pytest.raises(PlanCorruptError, match="capital"):
        store.load("2026-09-24")


def test_plan_with_future_schema_version_raises_plan_corrupt(tmp_path):
    store = PlanStore(tmp_path)
    payload = make_plan().to_dict()
    payload["schema_version"] = 99
    (tmp_path / "2026-09-24.json").write_text(json.dumps(payload))

    with pytest.raises(PlanCorruptError, match="schema version 99"):
        store.load("2026-09-24")
```

- [ ] **Step 6: Run the plan store tests to verify they fail**

Run: `pytest tests/core/test_plan_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.core.plan_store'`

- [ ] **Step 7: Implement the plan store**

Create `tradingbot/core/plan_store.py`:

```python
"""Read and write the TradePlan JSON artifact that decouples analysis from execution."""

from __future__ import annotations

import json
from pathlib import Path

from tradingbot.core.models import PLAN_SCHEMA_VERSION, TradePlan


class PlanNotFoundError(Exception):
    """Raised when the requested trade plan file does not exist."""


class PlanCorruptError(Exception):
    """Raised when a trade plan file exists but cannot be trusted."""


class PlanStore:
    """Trade plans live as one JSON file per trade date."""

    def __init__(self, plan_dir: Path) -> None:
        self.plan_dir = Path(plan_dir)
        self.plan_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, trade_date: str) -> Path:
        return self.plan_dir / f"{trade_date}.json"

    def save(self, plan: TradePlan) -> Path:
        path = self.path_for(plan.trade_date)
        path.write_text(json.dumps(plan.to_dict(), indent=2))
        return path

    def load(self, trade_date: str) -> TradePlan:
        path = self.path_for(trade_date)
        if not path.exists():
            raise PlanNotFoundError(f"no trade plan for {trade_date} at {path}")

        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise PlanCorruptError(f"{path} could not be parsed as JSON: {exc}") from exc

        version = raw.get("schema_version", PLAN_SCHEMA_VERSION)
        if version > PLAN_SCHEMA_VERSION:
            raise PlanCorruptError(
                f"{path} uses schema version {version}, but this build understands "
                f"version {PLAN_SCHEMA_VERSION}. Regenerate the plan with `tradingbot analyze`."
            )

        try:
            return TradePlan.from_dict(raw)
        except KeyError as exc:
            raise PlanCorruptError(f"{path} is missing required field {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise PlanCorruptError(f"{path} has an invalid field value: {exc}") from exc

    def load_latest(self) -> TradePlan:
        candidates = sorted(self.plan_dir.glob("*.json"))
        if not candidates:
            raise PlanNotFoundError(f"no trade plans found in {self.plan_dir}")
        return self.load(candidates[-1].stem)
```

- [ ] **Step 8: Run the full test suite to verify it passes**

Run: `pytest tests/ -v`
Expected: PASS — 25 tests.

- [ ] **Step 9: Commit**

```bash
git add tradingbot/core/database.py tradingbot/core/plan_store.py tests/core/test_database.py tests/core/test_plan_store.py
git commit -m "feat: add SQLite trade history and trade plan JSON store"
```

---

## Task 3: LLM Provider Interface and Anthropic Implementation

**Files:**
- Create: `tradingbot/core/llm/__init__.py`
- Create: `tradingbot/core/llm/provider.py`
- Create: `tradingbot/core/llm/anthropic_provider.py`
- Test: `tests/core/llm/test_provider.py`, `tests/core/llm/test_anthropic_provider.py`

**Interfaces:**
- Consumes: `LLMConfig`, `Secrets` from `tradingbot.core.config` (Task 1).
- Produces:
  - `LLMProvider` ABC with `async analyze(system_prompt: str, user_prompt: str, tool_name: str, tool_description: str, input_schema: dict) -> dict` and `async health_check() -> bool`.
  - `LLMError`, `LLMTimeoutError`, `LLMResponseError` exceptions.
  - `AnthropicProvider(config: LLMConfig, api_key: str, client: Any | None = None, log_dir: Path | None = None)`.
  - `build_provider(config: LLMConfig, secrets: Secrets, log_dir: Path | None = None) -> LLMProvider`.

The provider returns the dict the model passed as `tool_use` input. Structured output is never parsed out of free text.

- [ ] **Step 1: Write the failing test for the provider contract**

Create `tests/core/llm/__init__.py` (empty) and `tests/core/llm/test_provider.py`:

```python
import inspect

import pytest

from tradingbot.core.llm.provider import LLMError, LLMProvider, LLMResponseError, LLMTimeoutError


def test_provider_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        LLMProvider()


def test_provider_declares_the_expected_async_methods():
    assert inspect.iscoroutinefunction(LLMProvider.analyze)
    assert inspect.iscoroutinefunction(LLMProvider.health_check)


def test_analyze_signature_is_stable():
    params = list(inspect.signature(LLMProvider.analyze).parameters)
    assert params == [
        "self",
        "system_prompt",
        "user_prompt",
        "tool_name",
        "tool_description",
        "input_schema",
    ]


def test_specific_errors_subclass_llm_error():
    assert issubclass(LLMTimeoutError, LLMError)
    assert issubclass(LLMResponseError, LLMError)


def test_a_concrete_subclass_can_be_instantiated():
    class StubProvider(LLMProvider):
        async def analyze(self, system_prompt, user_prompt, tool_name, tool_description, input_schema):
            return {"ok": True}

        async def health_check(self):
            return True

    assert isinstance(StubProvider(), LLMProvider)
```

- [ ] **Step 2: Run the provider tests to verify they fail**

Run: `pytest tests/core/llm/test_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.core.llm'`

- [ ] **Step 3: Implement the provider interface**

Create `tradingbot/core/llm/__init__.py` (empty) and `tradingbot/core/llm/provider.py`:

```python
"""Provider-agnostic LLM interface. Swapping vendors must not touch agent code."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMError(Exception):
    """Base class for every LLM failure."""


class LLMTimeoutError(LLMError):
    """The model did not respond within the configured timeout."""


class LLMResponseError(LLMError):
    """The model responded, but not with the structured output we asked for."""


class LLMProvider(ABC):
    """Every provider returns structured output via a forced tool call."""

    @abstractmethod
    async def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Send the prompts and return the tool input the model produced."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True when the provider is reachable and credentials work."""
```

- [ ] **Step 4: Run the provider tests to verify they pass**

Run: `pytest tests/core/llm/test_provider.py -v`
Expected: PASS — 5 tests.

- [ ] **Step 5: Write the failing test for the Anthropic implementation**

Create `tests/core/llm/test_anthropic_provider.py`:

```python
import json
from types import SimpleNamespace

import pytest

from tradingbot.core.config import LLMConfig
from tradingbot.core.llm.anthropic_provider import AnthropicProvider
from tradingbot.core.llm.provider import LLMResponseError

SCHEMA = {
    "type": "object",
    "properties": {"picks": {"type": "array", "items": {"type": "string"}}},
    "required": ["picks"],
    "additionalProperties": False,
}


def make_config() -> LLMConfig:
    return LLMConfig(provider="anthropic", model="claude-sonnet-5", timeout_sec=60, max_retries=1)


class FakeMessages:
    """Stands in for client.messages, recording the kwargs it was called with."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def make_client(responses):
    return SimpleNamespace(messages=FakeMessages(responses))


def tool_use_response(payload):
    block = SimpleNamespace(type="tool_use", name="emit_result", input=payload)
    return SimpleNamespace(content=[block], stop_reason="tool_use")


def text_only_response(text="I cannot help with that."):
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block], stop_reason="end_turn")


async def test_analyze_returns_the_tool_input(tmp_path):
    client = make_client([tool_use_response({"picks": ["RELIANCE", "TCS"]})])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    result = await provider.analyze(
        system_prompt="You are an analyst.",
        user_prompt="Pick two stocks.",
        tool_name="emit_result",
        tool_description="Return the chosen stocks.",
        input_schema=SCHEMA,
    )

    assert result == {"picks": ["RELIANCE", "TCS"]}


async def test_analyze_sends_the_configured_model_and_tool(tmp_path):
    client = make_client([tool_use_response({"picks": []})])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)

    sent = client.messages.calls[0]
    assert sent["model"] == "claude-sonnet-5"
    assert sent["system"] == "sys"
    assert sent["tools"][0]["name"] == "emit_result"
    assert sent["tools"][0]["input_schema"] == SCHEMA
    assert sent["messages"] == [{"role": "user", "content": "user"}]


async def test_missing_tool_use_block_raises_llm_response_error(tmp_path):
    client = make_client([text_only_response(), text_only_response()])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    with pytest.raises(LLMResponseError, match="no tool_use block"):
        await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)


async def test_a_transient_failure_is_retried_once(tmp_path):
    client = make_client([RuntimeError("connection reset"), tool_use_response({"picks": ["INFY"]})])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    result = await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)

    assert result == {"picks": ["INFY"]}
    assert len(client.messages.calls) == 2


async def test_failures_beyond_max_retries_raise(tmp_path):
    client = make_client([RuntimeError("boom"), RuntimeError("boom again")])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    with pytest.raises(Exception, match="boom again"):
        await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)


async def test_every_call_is_logged_as_jsonl(tmp_path):
    client = make_client([tool_use_response({"picks": ["SBIN"]})])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    await provider.analyze("sys prompt", "user prompt", "emit_result", "desc", SCHEMA)

    log_files = list(tmp_path.glob("*.jsonl"))
    assert len(log_files) == 1
    entry = json.loads(log_files[0].read_text().strip())
    assert entry["tool_name"] == "emit_result"
    assert entry["system_prompt"] == "sys prompt"
    assert entry["response"] == {"picks": ["SBIN"]}


async def test_the_api_key_never_appears_in_the_log(tmp_path):
    client = make_client([tool_use_response({"picks": []})])
    provider = AnthropicProvider(
        make_config(), api_key="sk-ant-super-secret", client=client, log_dir=tmp_path
    )

    await provider.analyze("sys", "user", "emit_result", "desc", SCHEMA)

    written = "".join(path.read_text() for path in tmp_path.glob("*.jsonl"))
    assert "sk-ant-super-secret" not in written


async def test_health_check_is_true_when_the_call_succeeds(tmp_path):
    client = make_client([tool_use_response({"picks": []})])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    assert await provider.health_check() is True


async def test_health_check_is_false_when_the_call_fails(tmp_path):
    client = make_client([RuntimeError("no network"), RuntimeError("still no network")])
    provider = AnthropicProvider(make_config(), api_key="sk-ant-test", client=client, log_dir=tmp_path)

    assert await provider.health_check() is False
```

- [ ] **Step 6: Run the Anthropic tests to verify they fail**

Run: `pytest tests/core/llm/test_anthropic_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.core.llm.anthropic_provider'`

- [ ] **Step 7: Implement the Anthropic provider**

Create `tradingbot/core/llm/anthropic_provider.py`:

```python
"""Claude implementation of LLMProvider. Structured output comes from tool_use."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from tradingbot.core.config import LLMConfig, Secrets
from tradingbot.core.llm.provider import LLMProvider, LLMResponseError

logger = logging.getLogger(__name__)

MAX_TOKENS = 16000

HEALTH_CHECK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


class AnthropicProvider(LLMProvider):
    """Calls the Anthropic Messages API and returns the forced tool input."""

    def __init__(
        self,
        config: LLMConfig,
        api_key: str,
        client: Any | None = None,
        log_dir: Path | None = None,
    ) -> None:
        self.config = config
        self.log_dir = Path(log_dir) if log_dir is not None else None
        if self.log_dir is not None:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        if client is not None:
            self.client = client
        else:
            from anthropic import AsyncAnthropic

            self.client = AsyncAnthropic(api_key=api_key, timeout=config.timeout_sec)

    async def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
    ) -> dict[str, Any]:
        tool = {
            "name": tool_name,
            "description": tool_description,
            "input_schema": input_schema,
            "strict": True,
        }

        attempts = self.config.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await self.client.messages.create(
                    model=self.config.model,
                    max_tokens=MAX_TOKENS,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                    tools=[tool],
                )
            except Exception as exc:  # noqa: BLE001 - surfaced after retries
                last_error = exc
                logger.warning("LLM call failed on attempt %s/%s: %s", attempt, attempts, exc)
                continue

            payload = self._extract_tool_input(response, tool_name)
            if payload is None:
                last_error = LLMResponseError(
                    f"model returned no tool_use block for {tool_name!r}; "
                    f"stop_reason={getattr(response, 'stop_reason', 'unknown')}"
                )
                logger.warning("LLM returned no tool_use on attempt %s/%s", attempt, attempts)
                continue

            self._log_call(system_prompt, user_prompt, tool_name, payload)
            return payload

        assert last_error is not None
        raise last_error

    async def health_check(self) -> bool:
        try:
            await self.analyze(
                system_prompt="You are a connectivity probe.",
                user_prompt="Call the tool with ok set to true.",
                tool_name="report_health",
                tool_description="Report that the connection works.",
                input_schema=HEALTH_CHECK_SCHEMA,
            )
        except Exception:  # noqa: BLE001 - a health check never propagates
            return False
        return True

    @staticmethod
    def _extract_tool_input(response: Any, tool_name: str) -> dict[str, Any] | None:
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
                return dict(block.input)
        return None

    def _log_call(
        self,
        system_prompt: str,
        user_prompt: str,
        tool_name: str,
        payload: dict[str, Any],
    ) -> None:
        if self.log_dir is None:
            return
        entry = {
            "model": self.config.model,
            "tool_name": tool_name,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "response": payload,
        }
        path = self.log_dir / f"{date.today().isoformat()}.jsonl"
        with path.open("a") as handle:
            handle.write(json.dumps(entry) + "\n")


def build_provider(
    config: LLMConfig,
    secrets: Secrets,
    log_dir: Path | None = None,
) -> LLMProvider:
    """Return the provider named in config. Only 'anthropic' ships today."""
    if config.provider == "anthropic":
        return AnthropicProvider(config, api_key=secrets.anthropic_api_key, log_dir=log_dir)
    raise ValueError(f"unknown llm.provider {config.provider!r}; expected 'anthropic'")
```

- [ ] **Step 8: Run the full test suite to verify it passes**

Run: `pytest tests/ -v`
Expected: PASS — 39 tests.

- [ ] **Step 9: Commit**

```bash
git add tradingbot/core/llm/ tests/core/llm/
git commit -m "feat: add provider-agnostic LLM interface with Claude implementation"
```

---

## Task 4: Technical Indicators

**Files:**
- Create: `tradingbot/strategy/__init__.py`
- Create: `tradingbot/strategy/indicators.py`
- Test: `tests/strategy/test_indicators.py`

**Interfaces:**
- Consumes: `IndicatorSnapshot` from `tradingbot.core.models` (Task 1).
- Produces, all operating on a candle `DataFrame` with columns `open`, `high`, `low`, `close`, `volume` and a `DatetimeIndex`:
  - `rsi(close: pd.Series, period: int = 14) -> pd.Series`
  - `macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series]`
  - `bollinger_bands(close: pd.Series, period: int = 20, std: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]`
  - `atr(df: pd.DataFrame, period: int = 14) -> pd.Series`
  - `sma(close: pd.Series, period: int) -> pd.Series`
  - `ema(close: pd.Series, period: int) -> pd.Series`
  - `vwap(df: pd.DataFrame) -> pd.Series`
  - `pivot_points(df: pd.DataFrame) -> dict[str, float]`
  - `support_resistance(df: pd.DataFrame, eps_pct: float = 0.5, min_samples: int = 3) -> tuple[list[float], list[float]]`
  - `compute_snapshot(symbol: str, df: pd.DataFrame) -> IndicatorSnapshot`
  - `InsufficientDataError`

- [ ] **Step 1: Write the failing test for indicators**

Create `tests/strategy/__init__.py` (empty) and `tests/strategy/test_indicators.py`:

```python
import numpy as np
import pandas as pd
import pytest

from tradingbot.strategy.indicators import (
    InsufficientDataError,
    atr,
    bollinger_bands,
    compute_snapshot,
    ema,
    macd,
    pivot_points,
    rsi,
    sma,
    support_resistance,
    vwap,
)


def make_candles(closes, volumes=None, spread=1.0):
    index = pd.date_range("2026-09-01 09:15", periods=len(closes), freq="15min", tz="Asia/Kolkata")
    closes = np.asarray(closes, dtype=float)
    volumes = np.full(len(closes), 10000.0) if volumes is None else np.asarray(volumes, dtype=float)
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes + spread,
            "low": closes - spread,
            "close": closes,
            "volume": volumes,
        },
        index=index,
    )


def test_rsi_of_a_monotonic_rise_approaches_100():
    df = make_candles(np.arange(100, 140, dtype=float))
    assert rsi(df["close"], period=14).iloc[-1] == pytest.approx(100.0, abs=1e-6)


def test_rsi_of_a_monotonic_fall_approaches_zero():
    df = make_candles(np.arange(140, 100, -1, dtype=float))
    assert rsi(df["close"], period=14).iloc[-1] == pytest.approx(0.0, abs=1e-6)


def test_rsi_of_a_flat_series_is_neutral():
    df = make_candles([100.0] * 40)
    assert rsi(df["close"], period=14).iloc[-1] == pytest.approx(50.0)


def test_sma_equals_the_arithmetic_mean_of_the_window():
    series = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
    assert sma(series, period=5).iloc[-1] == pytest.approx(30.0)


def test_ema_weights_recent_values_more_heavily_than_sma():
    series = pd.Series([10.0] * 19 + [100.0])
    assert ema(series, period=20).iloc[-1] > sma(series, period=20).iloc[-1]


def test_macd_line_is_positive_when_the_trend_is_up():
    df = make_candles(np.arange(100, 160, dtype=float))
    macd_line, signal_line = macd(df["close"])
    assert macd_line.iloc[-1] > 0
    assert len(signal_line) == len(macd_line)


def test_bollinger_bands_are_ordered_and_centred_on_the_sma():
    df = make_candles(np.random.default_rng(42).normal(100, 2, 60))
    upper, middle, lower = bollinger_bands(df["close"], period=20, std=2.0)
    assert upper.iloc[-1] > middle.iloc[-1] > lower.iloc[-1]
    assert middle.iloc[-1] == pytest.approx(sma(df["close"], 20).iloc[-1])


def test_atr_of_a_constant_range_equals_that_range():
    df = make_candles([100.0] * 30, spread=2.5)
    assert atr(df, period=14).iloc[-1] == pytest.approx(5.0)


def test_vwap_equals_price_when_price_never_moves():
    df = make_candles([100.0] * 10)
    assert vwap(df).iloc[-1] == pytest.approx(100.0)


def test_vwap_is_pulled_toward_the_high_volume_price():
    df = make_candles([100.0, 200.0], volumes=[1.0, 99.0], spread=0.0)
    assert vwap(df).iloc[-1] == pytest.approx(199.0)


def test_pivot_points_follow_the_classic_formula():
    df = make_candles([100.0, 110.0, 105.0], spread=0.0)
    df.iloc[-1, df.columns.get_loc("high")] = 110.0
    df.iloc[-1, df.columns.get_loc("low")] = 100.0
    df.iloc[-1, df.columns.get_loc("close")] = 105.0

    levels = pivot_points(df)

    assert levels["pivot"] == pytest.approx(105.0)
    assert levels["r1"] == pytest.approx(110.0)
    assert levels["s1"] == pytest.approx(100.0)


def test_support_resistance_clusters_repeated_touches():
    closes = [100.0, 120.0, 100.5, 121.0, 99.8, 120.5, 100.2, 119.5] * 4
    df = make_candles(closes, spread=0.2)

    supports, resistances = support_resistance(df, eps_pct=1.0, min_samples=3)

    assert any(99.0 <= level <= 102.0 for level in supports + resistances)
    assert any(118.0 <= level <= 122.0 for level in supports + resistances)


def test_support_levels_sit_below_the_last_close_and_resistance_above():
    closes = [100.0, 120.0, 100.5, 121.0, 99.8, 120.5, 100.2, 119.5] * 4 + [110.0]
    df = make_candles(closes, spread=0.2)

    supports, resistances = support_resistance(df, eps_pct=1.0, min_samples=3)

    assert all(level < 110.0 for level in supports)
    assert all(level > 110.0 for level in resistances)


def test_compute_snapshot_populates_every_field():
    rng = np.random.default_rng(7)
    df = make_candles(100 + np.cumsum(rng.normal(0, 1, 250)))

    snapshot = compute_snapshot("RELIANCE", df)

    assert snapshot.symbol == "RELIANCE"
    assert snapshot.last_close == pytest.approx(df["close"].iloc[-1])
    assert 0.0 <= snapshot.rsi_14 <= 100.0
    assert snapshot.atr_14 > 0
    assert snapshot.bb_upper > snapshot.bb_lower
    assert isinstance(snapshot.support_levels, list)
    assert isinstance(snapshot.resistance_levels, list)


def test_compute_snapshot_rejects_too_few_candles():
    df = make_candles([100.0] * 10)

    with pytest.raises(InsufficientDataError, match="at least"):
        compute_snapshot("TCS", df)


def test_indicator_functions_never_mutate_the_input_frame():
    df = make_candles(np.arange(100, 160, dtype=float))
    before = df.copy(deep=True)

    compute_snapshot("INFY", df)

    pd.testing.assert_frame_equal(df, before)
```

- [ ] **Step 2: Run the indicator tests to verify they fail**

Run: `pytest tests/strategy/test_indicators.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.strategy'`

- [ ] **Step 3: Implement the indicators module**

Create `tradingbot/strategy/__init__.py` (empty) and `tradingbot/strategy/indicators.py`:

```python
"""Deterministic technical indicators. Pure pandas and numpy, no LLM involvement."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

from tradingbot.core.models import IndicatorSnapshot

MIN_CANDLES = 200


class InsufficientDataError(Exception):
    """Raised when there are not enough candles to compute a full snapshot."""


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI. A flat series returns 50 rather than NaN."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    result = 100.0 - (100.0 / (1.0 + rs))
    both_flat = (avg_gain == 0.0) & (avg_loss == 0.0)
    result = result.mask(both_flat, 50.0)
    result = result.mask((avg_loss == 0.0) & (avg_gain > 0.0), 100.0)
    return result


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series]:
    """Return the MACD line and its signal line."""
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def bollinger_bands(
    close: pd.Series,
    period: int = 20,
    std: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (upper, middle, lower) bands."""
    middle = close.rolling(window=period).mean()
    deviation = close.rolling(window=period).std(ddof=0)
    return middle + std * deviation, middle, middle - std * deviation


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range using Wilder's smoothing."""
    high, low, prev_close = df["high"], df["low"], df["close"].shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(window=period).mean()


def ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def vwap(df: pd.DataFrame) -> pd.Series:
    """Cumulative volume weighted average price across the supplied frame."""
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    cumulative_volume = df["volume"].cumsum()
    return (typical * df["volume"]).cumsum() / cumulative_volume


def pivot_points(df: pd.DataFrame) -> dict[str, float]:
    """Classic floor-trader pivots derived from the most recent candle."""
    last = df.iloc[-1]
    high, low, close = float(last["high"]), float(last["low"]), float(last["close"])
    pivot = (high + low + close) / 3.0
    return {
        "pivot": pivot,
        "r1": 2 * pivot - low,
        "r2": pivot + (high - low),
        "s1": 2 * pivot - high,
        "s2": pivot - (high - low),
    }


def support_resistance(
    df: pd.DataFrame,
    eps_pct: float = 0.5,
    min_samples: int = 3,
) -> tuple[list[float], list[float]]:
    """Cluster swing highs and lows with DBSCAN into support and resistance levels.

    eps_pct is expressed as a percentage of the last close so the same setting
    behaves consistently across a 90 rupee stock and a 3000 rupee one.
    """
    last_close = float(df["close"].iloc[-1])
    pivots = np.concatenate([df["high"].to_numpy(), df["low"].to_numpy()]).reshape(-1, 1)
    if len(pivots) < min_samples:
        return [], []

    eps = last_close * (eps_pct / 100.0)
    labels = DBSCAN(eps=eps, min_samples=min_samples).fit(pivots).labels_

    levels = [
        float(pivots[labels == label].mean())
        for label in sorted(set(labels))
        if label != -1
    ]

    supports = sorted(level for level in levels if level < last_close)
    resistances = sorted(level for level in levels if level > last_close)
    return supports, resistances


def compute_snapshot(symbol: str, df: pd.DataFrame) -> IndicatorSnapshot:
    """Compute every indicator the strategy layer needs for one symbol."""
    if len(df) < MIN_CANDLES:
        raise InsufficientDataError(
            f"{symbol}: need at least {MIN_CANDLES} candles to compute a snapshot, got {len(df)}"
        )

    close = df["close"]
    macd_line, signal_line = macd(close)
    upper, middle, lower = bollinger_bands(close)
    supports, resistances = support_resistance(df)

    return IndicatorSnapshot(
        symbol=symbol,
        last_close=float(close.iloc[-1]),
        rsi_14=float(rsi(close).iloc[-1]),
        macd=float(macd_line.iloc[-1]),
        macd_signal=float(signal_line.iloc[-1]),
        bb_upper=float(upper.iloc[-1]),
        bb_middle=float(middle.iloc[-1]),
        bb_lower=float(lower.iloc[-1]),
        atr_14=float(atr(df).iloc[-1]),
        sma_20=float(sma(close, 20).iloc[-1]),
        sma_50=float(sma(close, 50).iloc[-1]),
        sma_200=float(sma(close, 200).iloc[-1]),
        ema_12=float(ema(close, 12).iloc[-1]),
        ema_26=float(ema(close, 26).iloc[-1]),
        vwap=float(vwap(df).iloc[-1]),
        pivot=float(pivot_points(df)["pivot"]),
        support_levels=supports,
        resistance_levels=resistances,
    )
```

- [ ] **Step 4: Run the indicator tests to verify they pass**

Run: `pytest tests/strategy/test_indicators.py -v`
Expected: PASS — 16 tests.

- [ ] **Step 5: Commit**

```bash
git add tradingbot/strategy/__init__.py tradingbot/strategy/indicators.py tests/strategy/
git commit -m "feat: add technical indicators with DBSCAN support/resistance clustering"
```

---

## Task 5: Scanner — Universe Fetching and Deterministic Filters

**Files:**
- Create: `tradingbot/scanner/__init__.py`
- Create: `tradingbot/scanner/data_fetcher.py`
- Create: `tradingbot/scanner/filters.py`
- Test: `tests/scanner/test_data_fetcher.py`, `tests/scanner/test_filters.py`

**Interfaces:**
- Consumes: `Stock` from `tradingbot.core.models` (Task 1); `ScannerConfig` from `tradingbot.core.config` (Task 1).
- Produces:
  - `DataFetcher(cache_dir: Path | None = None)` with `fetch_universe() -> list[str]`, `fetch_stock_metrics(symbols: list[str]) -> list[Stock]`, `fetch_candles(symbol: str, days: int, interval: str) -> pd.DataFrame`.
  - `DataFetchError`.
  - `apply_filters(stocks: list[Stock], config: ScannerConfig) -> FilterResult`.
  - `FilterResult` dataclass with `passed: list[Stock]` and `rejected: dict[str, int]` (reason → count).

- [ ] **Step 1: Write the failing test for filters**

Create `tests/scanner/__init__.py` (empty) and `tests/scanner/test_filters.py`:

```python
import pytest

from tradingbot.core.config import ScannerConfig
from tradingbot.core.models import Stock
from tradingbot.scanner.filters import apply_filters


def make_config(**overrides) -> ScannerConfig:
    defaults = {
        "min_volume": 500000,
        "min_price": 50.0,
        "max_price": 5000.0,
        "min_market_cap_cr": 5000.0,
        "min_atr_pct": 0.5,
        "max_stocks_to_llm": 100,
        "llm_pick_count": 15,
    }
    defaults.update(overrides)
    return ScannerConfig(**defaults)


def make_stock(
    symbol="RELIANCE",
    last_price=2855.0,
    avg_volume=2_000_000.0,
    market_cap_cr=1_900_000.0,
    atr_pct=1.4,
) -> Stock:
    return Stock(
        symbol=symbol,
        exchange="NSE",
        last_price=last_price,
        avg_volume=avg_volume,
        market_cap_cr=market_cap_cr,
        atr_pct=atr_pct,
        sector="Energy",
    )


def test_a_fully_qualified_stock_passes():
    result = apply_filters([make_stock()], make_config())

    assert [stock.symbol for stock in result.passed] == ["RELIANCE"]
    assert result.rejected == {}


def test_illiquid_stock_is_rejected_for_volume():
    result = apply_filters([make_stock(avg_volume=1000.0)], make_config())

    assert result.passed == []
    assert result.rejected == {"volume": 1}


def test_penny_stock_is_rejected_for_price():
    result = apply_filters([make_stock(last_price=12.0)], make_config())

    assert result.passed == []
    assert result.rejected == {"price": 1}


def test_very_expensive_stock_is_rejected_for_price():
    result = apply_filters([make_stock(last_price=9000.0)], make_config())

    assert result.passed == []
    assert result.rejected == {"price": 1}


def test_micro_cap_is_rejected_for_market_cap():
    result = apply_filters([make_stock(market_cap_cr=300.0)], make_config())

    assert result.passed == []
    assert result.rejected == {"market_cap": 1}


def test_stock_that_barely_moves_is_rejected_for_atr():
    result = apply_filters([make_stock(atr_pct=0.05)], make_config())

    assert result.passed == []
    assert result.rejected == {"atr": 1}


def test_boundary_values_are_inclusive():
    config = make_config(min_volume=1000, min_price=50.0, max_price=5000.0, min_market_cap_cr=5000.0, min_atr_pct=0.5)
    at_lower = make_stock(symbol="LOW", last_price=50.0, avg_volume=1000.0, market_cap_cr=5000.0, atr_pct=0.5)
    at_upper = make_stock(symbol="HIGH", last_price=5000.0)

    result = apply_filters([at_lower, at_upper], config)

    assert sorted(stock.symbol for stock in result.passed) == ["HIGH", "LOW"]


def test_each_stock_is_counted_under_its_first_failing_reason():
    stock = make_stock(avg_volume=10.0, last_price=5.0, market_cap_cr=1.0, atr_pct=0.0)

    result = apply_filters([stock], make_config())

    assert result.rejected == {"volume": 1}


def test_results_are_capped_at_max_stocks_to_llm_keeping_the_most_liquid():
    stocks = [
        make_stock(symbol=f"SYM{index}", avg_volume=1_000_000.0 + index)
        for index in range(10)
    ]

    result = apply_filters(stocks, make_config(max_stocks_to_llm=3))

    assert [stock.symbol for stock in result.passed] == ["SYM9", "SYM8", "SYM7"]


def test_an_empty_universe_produces_an_empty_result():
    result = apply_filters([], make_config())

    assert result.passed == []
    assert result.rejected == {}
```

- [ ] **Step 2: Run the filter tests to verify they fail**

Run: `pytest tests/scanner/test_filters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.scanner'`

- [ ] **Step 3: Implement the filters module**

Create `tradingbot/scanner/__init__.py` (empty) and `tradingbot/scanner/filters.py`:

```python
"""Deterministic screening. Runs before the LLM so the model only sees plausible names."""

from __future__ import annotations

from dataclasses import dataclass, field

from tradingbot.core.config import ScannerConfig
from tradingbot.core.models import Stock


@dataclass
class FilterResult:
    """Which stocks survived, and a tally of why the rest did not."""

    passed: list[Stock] = field(default_factory=list)
    rejected: dict[str, int] = field(default_factory=dict)


def _rejection_reason(stock: Stock, config: ScannerConfig) -> str | None:
    """Return the first failing filter name, or None when the stock passes."""
    if stock.avg_volume < config.min_volume:
        return "volume"
    if not (config.min_price <= stock.last_price <= config.max_price):
        return "price"
    if stock.market_cap_cr < config.min_market_cap_cr:
        return "market_cap"
    if stock.atr_pct < config.min_atr_pct:
        return "atr"
    return None


def apply_filters(stocks: list[Stock], config: ScannerConfig) -> FilterResult:
    """Screen the universe down to the candidates worth spending LLM tokens on."""
    result = FilterResult()

    for stock in stocks:
        reason = _rejection_reason(stock, config)
        if reason is None:
            result.passed.append(stock)
        else:
            result.rejected[reason] = result.rejected.get(reason, 0) + 1

    result.passed.sort(key=lambda stock: stock.avg_volume, reverse=True)
    result.passed = result.passed[: config.max_stocks_to_llm]
    return result
```

- [ ] **Step 4: Run the filter tests to verify they pass**

Run: `pytest tests/scanner/test_filters.py -v`
Expected: PASS — 10 tests.

- [ ] **Step 5: Write the failing test for the data fetcher**

Create `tests/scanner/test_data_fetcher.py`:

```python
import pandas as pd
import pytest

from tradingbot.scanner.data_fetcher import DataFetcher, DataFetchError


class FakeTicker:
    def __init__(self, info, history):
        self.info = info
        self._history = history

    def history(self, period=None, interval=None):
        return self._history


def make_history(rows=250):
    index = pd.date_range("2026-01-01", periods=rows, freq="15min", tz="Asia/Kolkata")
    return pd.DataFrame(
        {
            "Open": [100.0] * rows,
            "High": [101.0] * rows,
            "Low": [99.0] * rows,
            "Close": [100.0] * rows,
            "Volume": [50000.0] * rows,
        },
        index=index,
    )


def test_fetch_universe_returns_nonempty_uppercase_symbols(tmp_path):
    fetcher = DataFetcher(cache_dir=tmp_path)

    symbols = fetcher.fetch_universe()

    assert len(symbols) > 0
    assert all(symbol == symbol.upper() for symbol in symbols)
    assert "RELIANCE" in symbols


def test_fetch_universe_result_has_no_duplicates(tmp_path):
    fetcher = DataFetcher(cache_dir=tmp_path)

    symbols = fetcher.fetch_universe()

    assert len(symbols) == len(set(symbols))


def test_fetch_candles_normalises_column_names(tmp_path, monkeypatch):
    fetcher = DataFetcher(cache_dir=tmp_path)
    monkeypatch.setattr(
        "tradingbot.scanner.data_fetcher.yf.Ticker",
        lambda symbol: FakeTicker({}, make_history()),
    )

    df = fetcher.fetch_candles("RELIANCE", days=30, interval="15m")

    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 250


def test_fetch_candles_raises_when_the_frame_is_empty(tmp_path, monkeypatch):
    fetcher = DataFetcher(cache_dir=tmp_path)
    monkeypatch.setattr(
        "tradingbot.scanner.data_fetcher.yf.Ticker",
        lambda symbol: FakeTicker({}, pd.DataFrame()),
    )

    with pytest.raises(DataFetchError, match="no candle data"):
        fetcher.fetch_candles("GHOST", days=30, interval="15m")


def test_fetch_stock_metrics_builds_stock_objects(tmp_path, monkeypatch):
    info = {"marketCap": 19_000_000_000_000, "sector": "Energy"}
    monkeypatch.setattr(
        "tradingbot.scanner.data_fetcher.yf.Ticker",
        lambda symbol: FakeTicker(info, make_history()),
    )
    fetcher = DataFetcher(cache_dir=tmp_path)

    stocks = fetcher.fetch_stock_metrics(["RELIANCE"])

    assert len(stocks) == 1
    stock = stocks[0]
    assert stock.symbol == "RELIANCE"
    assert stock.exchange == "NSE"
    assert stock.last_price == pytest.approx(100.0)
    assert stock.avg_volume == pytest.approx(50000.0)
    assert stock.market_cap_cr == pytest.approx(1_900_000.0)
    assert stock.sector == "Energy"
    assert stock.atr_pct > 0


def test_fetch_stock_metrics_skips_symbols_that_fail(tmp_path, monkeypatch):
    def ticker(symbol):
        if symbol.startswith("BROKEN"):
            raise RuntimeError("delisted")
        return FakeTicker({"marketCap": 1e12, "sector": "IT"}, make_history())

    monkeypatch.setattr("tradingbot.scanner.data_fetcher.yf.Ticker", ticker)
    fetcher = DataFetcher(cache_dir=tmp_path)

    stocks = fetcher.fetch_stock_metrics(["BROKEN.NS", "TCS"])

    assert [stock.symbol for stock in stocks] == ["TCS"]


def test_fetch_stock_metrics_skips_symbols_with_too_little_history(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tradingbot.scanner.data_fetcher.yf.Ticker",
        lambda symbol: FakeTicker({"marketCap": 1e12, "sector": "IT"}, make_history(rows=3)),
    )
    fetcher = DataFetcher(cache_dir=tmp_path)

    assert fetcher.fetch_stock_metrics(["TINY"]) == []
```

- [ ] **Step 6: Run the data fetcher tests to verify they fail**

Run: `pytest tests/scanner/test_data_fetcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.scanner.data_fetcher'`

- [ ] **Step 7: Implement the data fetcher**

Create `tradingbot/scanner/data_fetcher.py`:

```python
"""Market data access for the analysis phase.

Analysis runs the night before or early morning, so a 15 minute delayed free
source is acceptable here. The executor uses live broker data instead.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import yfinance as yf

from tradingbot.core.models import Stock

logger = logging.getLogger(__name__)

MIN_HISTORY_ROWS = 20

NSE_UNIVERSE: tuple[str, ...] = (
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "HINDUNILVR", "ITC",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "MARUTI",
    "TITAN", "SUNPHARMA", "ULTRACEMCO", "BAJFINANCE", "WIPRO", "NESTLEIND",
    "ONGC", "NTPC", "POWERGRID", "TATAMOTORS", "TATASTEEL", "JSWSTEEL",
    "HINDALCO", "COALINDIA", "GRASIM", "ADANIENT", "ADANIPORTS", "CIPLA",
    "DRREDDY", "DIVISLAB", "EICHERMOT", "HEROMOTOCO", "BAJAJ-AUTO", "BRITANNIA",
    "APOLLOHOSP", "INDUSINDBK", "BAJAJFINSV", "TECHM", "HCLTECH", "SBILIFE",
    "HDFCLIFE", "TATACONSUM", "UPL", "BPCL", "SHREECEM", "M&M",
)


class DataFetchError(Exception):
    """Raised when market data could not be retrieved for a symbol."""


class DataFetcher:
    """Fetches the tradable universe, per-symbol metrics, and candle history."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch_universe(self) -> list[str]:
        """Return the NSE symbols the scanner is allowed to consider."""
        return list(dict.fromkeys(NSE_UNIVERSE))

    def fetch_candles(self, symbol: str, days: int, interval: str) -> pd.DataFrame:
        """Return OHLCV candles with lowercase column names."""
        ticker = yf.Ticker(f"{symbol}.NS")
        raw = ticker.history(period=f"{days}d", interval=interval)
        if raw is None or raw.empty:
            raise DataFetchError(f"no candle data returned for {symbol}")

        df = raw.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )
        return df[["open", "high", "low", "close", "volume"]]

    def fetch_stock_metrics(self, symbols: list[str]) -> list[Stock]:
        """Build Stock records. Symbols that fail to load are skipped, not fatal."""
        stocks: list[Stock] = []

        for symbol in symbols:
            try:
                ticker = yf.Ticker(f"{symbol}.NS")
                info = ticker.info or {}
                history = ticker.history(period="60d", interval="1d")
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the scan
                logger.warning("skipping %s: %s", symbol, exc)
                continue

            if history is None or history.empty or len(history) < MIN_HISTORY_ROWS:
                logger.warning("skipping %s: insufficient history", symbol)
                continue

            df = history.rename(
                columns={
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                }
            )
            last_price = float(df["close"].iloc[-1])
            daily_range = (df["high"] - df["low"]).tail(14).mean()
            atr_pct = float(daily_range / last_price * 100.0) if last_price else 0.0

            stocks.append(
                Stock(
                    symbol=symbol,
                    exchange="NSE",
                    last_price=last_price,
                    avg_volume=float(df["volume"].tail(20).mean()),
                    market_cap_cr=float(info.get("marketCap", 0.0)) / 1e7,
                    atr_pct=atr_pct,
                    sector=info.get("sector", "Unknown"),
                )
            )

        return stocks
```

- [ ] **Step 8: Run the full test suite to verify it passes**

Run: `pytest tests/ -v`
Expected: PASS — 72 tests.

- [ ] **Step 9: Commit**

```bash
git add tradingbot/scanner/ tests/scanner/
git commit -m "feat: add NSE universe fetching and deterministic candidate filters"
```

---

## Task 6: Scanner — Trading Calendar, Market Context, LLM Selection, Orchestration

**Files:**
- Create: `tradingbot/scanner/calendar.py`
- Create: `tradingbot/scanner/market_context.py`
- Create: `tradingbot/scanner/market_analyzer.py`
- Create: `tradingbot/scanner/scanner.py`
- Test: `tests/scanner/test_calendar.py`, `tests/scanner/test_market_context.py`, `tests/scanner/test_market_analyzer.py`, `tests/scanner/test_scanner.py`

**Interfaces:**
- Consumes: `Stock`, `ShortlistedStock`, `MarketContext`, `MarketRegime`, `StrategyName` (Task 1); `ScannerConfig` (Task 1); `LLMProvider` (Task 3); `DataFetcher` (Task 5); `apply_filters` (Task 5).
- Produces:
  - `NSE_HOLIDAYS_2026: frozenset[date]`, `is_trading_day(day: date) -> bool`, `next_trading_day(day: date) -> date`, `NotATradingDayError`.
  - `MarketContextFetcher(http_client: httpx.Client | None = None)` with `fetch() -> MarketContext`.
  - `MarketAnalyzer(provider: LLMProvider, config: ScannerConfig)` with `async shortlist(stocks: list[Stock], context: MarketContext) -> list[ShortlistedStock]` and `SHORTLIST_SCHEMA`.
  - `Scanner(fetcher, context_fetcher, analyzer, config)` with `async scan(trade_date: date) -> ScanResult`.
  - `ScanResult` dataclass with `trade_date: date`, `context: MarketContext`, `shortlist: list[ShortlistedStock]`, `filter_result: FilterResult`.

- [ ] **Step 1: Write the failing test for the trading calendar (covers Review Focus item 5)**

Create `tests/scanner/test_calendar.py`:

```python
from datetime import date

import pytest

from tradingbot.scanner.calendar import NotATradingDayError, is_trading_day, next_trading_day


def test_a_weekday_that_is_not_a_holiday_is_a_trading_day():
    assert is_trading_day(date(2026, 9, 24)) is True


def test_saturday_is_not_a_trading_day():
    assert is_trading_day(date(2026, 9, 26)) is False


def test_sunday_is_not_a_trading_day():
    assert is_trading_day(date(2026, 9, 27)) is False


def test_republic_day_is_not_a_trading_day():
    assert is_trading_day(date(2026, 1, 26)) is False


def test_independence_day_is_not_a_trading_day():
    assert is_trading_day(date(2026, 8, 15)) is False


def test_next_trading_day_skips_the_weekend():
    assert next_trading_day(date(2026, 9, 25)) == date(2026, 9, 28)


def test_next_trading_day_skips_a_holiday():
    assert next_trading_day(date(2026, 1, 23)) == date(2026, 1, 27)


def test_not_a_trading_day_error_names_the_date():
    with pytest.raises(NotATradingDayError, match="2026-09-26"):
        raise NotATradingDayError("2026-09-26 is not an NSE trading day")
```

- [ ] **Step 2: Run the calendar tests to verify they fail**

Run: `pytest tests/scanner/test_calendar.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.scanner.calendar'`

- [ ] **Step 3: Implement the trading calendar**

Create `tradingbot/scanner/calendar.py`:

```python
"""NSE trading calendar. Prevents generating plans nobody can execute."""

from __future__ import annotations

from datetime import date, timedelta

NSE_HOLIDAYS_2026: frozenset[date] = frozenset(
    {
        date(2026, 1, 26),   # Republic Day
        date(2026, 3, 4),    # Holi
        date(2026, 3, 21),   # Id-ul-Fitr
        date(2026, 4, 1),    # Annual bank closing
        date(2026, 4, 3),    # Good Friday
        date(2026, 4, 14),   # Dr. Ambedkar Jayanti
        date(2026, 5, 1),    # Maharashtra Day
        date(2026, 8, 15),   # Independence Day
        date(2026, 9, 14),   # Ganesh Chaturthi
        date(2026, 10, 2),   # Gandhi Jayanti
        date(2026, 10, 20),  # Dussehra
        date(2026, 11, 9),   # Diwali Laxmi Pujan
        date(2026, 11, 24),  # Guru Nanak Jayanti
        date(2026, 12, 25),  # Christmas
    }
)


class NotATradingDayError(Exception):
    """Raised when an operation is attempted for a non-trading date."""


def is_trading_day(day: date) -> bool:
    """True for weekdays that are not on the NSE holiday list."""
    if day.weekday() >= 5:
        return False
    return day not in NSE_HOLIDAYS_2026


def next_trading_day(day: date) -> date:
    """The first trading day strictly after the given date."""
    candidate = day + timedelta(days=1)
    while not is_trading_day(candidate):
        candidate += timedelta(days=1)
    return candidate
```

- [ ] **Step 4: Run the calendar tests to verify they pass**

Run: `pytest tests/scanner/test_calendar.py -v`
Expected: PASS — 8 tests.

- [ ] **Step 5: Write the failing test for market context**

Create `tests/scanner/test_market_context.py`:

```python
import httpx
import pytest

from tradingbot.core.models import MarketRegime
from tradingbot.scanner.market_context import MarketContextFetcher

FII_DII_PAYLOAD = [
    {"category": "FII/FPI *", "buyValue": "12000.00", "sellValue": "9700.00", "netValue": "2300.00"},
    {"category": "DII **", "buyValue": "7000.00", "sellValue": "7800.00", "netValue": "-800.00"},
]


def make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_returns_a_populated_context():
    def handler(request):
        if "fiidiiTradeReact" in str(request.url):
            return httpx.Response(200, json=FII_DII_PAYLOAD)
        return httpx.Response(200, json={})

    fetcher = MarketContextFetcher(http_client=make_client(handler))

    context = fetcher.fetch()

    assert context.fii_net_cr == pytest.approx(2300.0)
    assert context.dii_net_cr == pytest.approx(-800.0)
    assert isinstance(context.regime, MarketRegime)
    assert isinstance(context.sector_leaders, list)


def test_fii_dii_default_to_zero_when_the_nse_call_fails():
    def handler(request):
        return httpx.Response(503, text="service unavailable")

    fetcher = MarketContextFetcher(http_client=make_client(handler))

    context = fetcher.fetch()

    assert context.fii_net_cr == pytest.approx(0.0)
    assert context.dii_net_cr == pytest.approx(0.0)


def test_high_vix_classifies_the_regime_as_volatile():
    fetcher = MarketContextFetcher(http_client=make_client(lambda request: httpx.Response(200, json=[])))

    assert fetcher.classify_regime(vix=28.0, nifty_above_sma20=True, nifty_above_sma50=True) is MarketRegime.VOLATILE


def test_low_vix_classifies_the_regime_as_low_vol():
    fetcher = MarketContextFetcher(http_client=make_client(lambda request: httpx.Response(200, json=[])))

    assert fetcher.classify_regime(vix=9.0, nifty_above_sma20=True, nifty_above_sma50=True) is MarketRegime.LOW_VOL


def test_aligned_moving_averages_classify_the_regime_as_trending():
    fetcher = MarketContextFetcher(http_client=make_client(lambda request: httpx.Response(200, json=[])))

    assert fetcher.classify_regime(vix=15.0, nifty_above_sma20=True, nifty_above_sma50=True) is MarketRegime.TRENDING


def test_conflicting_moving_averages_classify_the_regime_as_ranging():
    fetcher = MarketContextFetcher(http_client=make_client(lambda request: httpx.Response(200, json=[])))

    assert fetcher.classify_regime(vix=15.0, nifty_above_sma20=True, nifty_above_sma50=False) is MarketRegime.RANGING
```

- [ ] **Step 6: Run the market context tests to verify they fail**

Run: `pytest tests/scanner/test_market_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.scanner.market_context'`

- [ ] **Step 7: Implement market context**

Create `tradingbot/scanner/market_context.py`:

```python
"""Macro backdrop for the scanner: index trend, volatility, institutional flows.

The NSE JSON endpoints require a browser-like session: fetch the homepage first
so the server sets its cookies, then call the API with those cookies attached.
"""

from __future__ import annotations

import logging

import httpx
import yfinance as yf

from tradingbot.core.models import MarketContext, MarketRegime

logger = logging.getLogger(__name__)

NSE_HOME = "https://www.nseindia.com"
NSE_FII_DII_URL = "https://www.nseindia.com/api/fiidiiTradeReact"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

VIX_VOLATILE_THRESHOLD = 20.0
VIX_LOW_THRESHOLD = 11.0


class MarketContextFetcher:
    """Assembles the MarketContext handed to the scanner LLM call."""

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self.http_client = http_client or httpx.Client(headers=BROWSER_HEADERS, timeout=10.0)

    def fetch(self) -> MarketContext:
        fii_net, dii_net = self._fetch_fii_dii()
        nifty_level, above_sma20, above_sma50 = self._fetch_index_trend("^NSEI")
        _, bank_above_sma20, bank_above_sma50 = self._fetch_index_trend("^NSEBANK")
        vix = self._fetch_vix()

        return MarketContext(
            nifty_level=nifty_level,
            nifty_trend=self._describe_trend(above_sma20, above_sma50),
            banknifty_trend=self._describe_trend(bank_above_sma20, bank_above_sma50),
            india_vix=vix,
            fii_net_cr=fii_net,
            dii_net_cr=dii_net,
            global_cues="unavailable",
            sector_leaders=[],
            sector_laggards=[],
            regime=self.classify_regime(vix, above_sma20, above_sma50),
        )

    def classify_regime(
        self,
        vix: float,
        nifty_above_sma20: bool,
        nifty_above_sma50: bool,
    ) -> MarketRegime:
        """Volatility dominates; direction only decides trending versus ranging."""
        if vix >= VIX_VOLATILE_THRESHOLD:
            return MarketRegime.VOLATILE
        if vix <= VIX_LOW_THRESHOLD:
            return MarketRegime.LOW_VOL
        if nifty_above_sma20 == nifty_above_sma50:
            return MarketRegime.TRENDING
        return MarketRegime.RANGING

    @staticmethod
    def _describe_trend(above_sma20: bool, above_sma50: bool) -> str:
        if above_sma20 and above_sma50:
            return "bullish"
        if not above_sma20 and not above_sma50:
            return "bearish"
        return "mixed"

    def _fetch_fii_dii(self) -> tuple[float, float]:
        """Return (FII net, DII net) in crore. Zeros when NSE is unreachable."""
        try:
            self.http_client.get(NSE_HOME, headers=BROWSER_HEADERS)
            response = self.http_client.get(NSE_FII_DII_URL, headers=BROWSER_HEADERS)
            response.raise_for_status()
            rows = response.json()
        except Exception as exc:  # noqa: BLE001 - macro data is nice to have, not required
            logger.warning("FII/DII fetch failed, defaulting to zero: %s", exc)
            return 0.0, 0.0

        fii_net = dii_net = 0.0
        for row in rows:
            category = str(row.get("category", "")).upper()
            try:
                net = float(row.get("netValue", 0.0))
            except (TypeError, ValueError):
                continue
            if "FII" in category or "FPI" in category:
                fii_net = net
            elif "DII" in category:
                dii_net = net
        return fii_net, dii_net

    @staticmethod
    def _fetch_index_trend(ticker: str) -> tuple[float, bool, bool]:
        """Return (last level, above 20 day SMA, above 50 day SMA)."""
        try:
            history = yf.Ticker(ticker).history(period="120d", interval="1d")
            closes = history["Close"]
            last = float(closes.iloc[-1])
            return (
                last,
                last > float(closes.rolling(20).mean().iloc[-1]),
                last > float(closes.rolling(50).mean().iloc[-1]),
            )
        except Exception as exc:  # noqa: BLE001 - fall back to a neutral reading
            logger.warning("index trend fetch failed for %s: %s", ticker, exc)
            return 0.0, False, False

    @staticmethod
    def _fetch_vix() -> float:
        try:
            history = yf.Ticker("^INDIAVIX").history(period="5d", interval="1d")
            return float(history["Close"].iloc[-1])
        except Exception as exc:  # noqa: BLE001 - a mid-range default keeps regime sane
            logger.warning("VIX fetch failed, defaulting to 15.0: %s", exc)
            return 15.0
```

- [ ] **Step 8: Write the failing test for the market analyzer**

Create `tests/scanner/test_market_analyzer.py`:

```python
import pytest

from tradingbot.core.config import ScannerConfig
from tradingbot.core.llm.provider import LLMProvider
from tradingbot.core.models import MarketContext, MarketRegime, Stock, StrategyName
from tradingbot.scanner.market_analyzer import MarketAnalyzer


class StubProvider(LLMProvider):
    def __init__(self, payload):
        self.payload = payload
        self.last_user_prompt = None
        self.last_schema = None

    async def analyze(self, system_prompt, user_prompt, tool_name, tool_description, input_schema):
        self.last_user_prompt = user_prompt
        self.last_schema = input_schema
        return self.payload

    async def health_check(self):
        return True


def make_config(llm_pick_count=15) -> ScannerConfig:
    return ScannerConfig(
        min_volume=500000,
        min_price=50.0,
        max_price=5000.0,
        min_market_cap_cr=5000.0,
        min_atr_pct=0.5,
        max_stocks_to_llm=100,
        llm_pick_count=llm_pick_count,
    )


def make_context() -> MarketContext:
    return MarketContext(
        nifty_level=25400.0,
        nifty_trend="bullish",
        banknifty_trend="bullish",
        india_vix=12.5,
        fii_net_cr=2300.0,
        dii_net_cr=-800.0,
        global_cues="US flat",
        sector_leaders=["IT"],
        sector_laggards=["FMCG"],
        regime=MarketRegime.TRENDING,
    )


def make_stocks(*symbols) -> list[Stock]:
    return [
        Stock(
            symbol=symbol,
            exchange="NSE",
            last_price=100.0,
            avg_volume=1_000_000.0,
            market_cap_cr=50000.0,
            atr_pct=1.2,
            sector="IT",
        )
        for symbol in symbols
    ]


async def test_shortlist_maps_the_llm_payload_to_dataclasses():
    provider = StubProvider(
        {
            "picks": [
                {
                    "symbol": "RELIANCE",
                    "reasoning": "Consolidating near resistance.",
                    "suggested_strategy": "breakout",
                    "direction_bias": "long",
                    "key_levels": [2850.0, 2900.0],
                }
            ]
        }
    )
    analyzer = MarketAnalyzer(provider, make_config())

    picks = await analyzer.shortlist(make_stocks("RELIANCE", "TCS"), make_context())

    assert len(picks) == 1
    assert picks[0].symbol == "RELIANCE"
    assert picks[0].suggested_strategy is StrategyName.BREAKOUT
    assert picks[0].key_levels == [2850.0, 2900.0]


async def test_picks_not_present_in_the_candidate_pool_are_dropped():
    provider = StubProvider(
        {
            "picks": [
                {
                    "symbol": "RELIANCE",
                    "reasoning": "Real candidate.",
                    "suggested_strategy": "breakout",
                    "direction_bias": "long",
                    "key_levels": [2850.0],
                },
                {
                    "symbol": "NOTREAL",
                    "reasoning": "Hallucinated ticker.",
                    "suggested_strategy": "momentum",
                    "direction_bias": "long",
                    "key_levels": [100.0],
                },
            ]
        }
    )
    analyzer = MarketAnalyzer(provider, make_config())

    picks = await analyzer.shortlist(make_stocks("RELIANCE", "TCS"), make_context())

    assert [pick.symbol for pick in picks] == ["RELIANCE"]


async def test_picks_with_an_unknown_strategy_are_dropped():
    provider = StubProvider(
        {
            "picks": [
                {
                    "symbol": "TCS",
                    "reasoning": "Unknown strategy name.",
                    "suggested_strategy": "telepathy",
                    "direction_bias": "long",
                    "key_levels": [100.0],
                }
            ]
        }
    )
    analyzer = MarketAnalyzer(provider, make_config())

    assert await analyzer.shortlist(make_stocks("TCS"), make_context()) == []


async def test_the_prompt_lists_every_candidate_and_the_market_context():
    provider = StubProvider({"picks": []})
    analyzer = MarketAnalyzer(provider, make_config())

    await analyzer.shortlist(make_stocks("RELIANCE", "TCS"), make_context())

    assert "RELIANCE" in provider.last_user_prompt
    assert "TCS" in provider.last_user_prompt
    assert "25400" in provider.last_user_prompt
    assert "trending" in provider.last_user_prompt


async def test_the_result_is_capped_at_the_configured_pick_count():
    provider = StubProvider(
        {
            "picks": [
                {
                    "symbol": symbol,
                    "reasoning": "Candidate.",
                    "suggested_strategy": "breakout",
                    "direction_bias": "long",
                    "key_levels": [100.0],
                }
                for symbol in ("A", "B", "C", "D")
            ]
        }
    )
    analyzer = MarketAnalyzer(provider, make_config(llm_pick_count=2))

    picks = await analyzer.shortlist(make_stocks("A", "B", "C", "D"), make_context())

    assert [pick.symbol for pick in picks] == ["A", "B"]


async def test_an_empty_candidate_pool_skips_the_llm_call():
    provider = StubProvider({"picks": [{"symbol": "GHOST", "reasoning": "x", "suggested_strategy": "orb", "direction_bias": "long", "key_levels": []}]})
    analyzer = MarketAnalyzer(provider, make_config())

    picks = await analyzer.shortlist([], make_context())

    assert picks == []
    assert provider.last_user_prompt is None
```

- [ ] **Step 9: Run the market analyzer tests to verify they fail**

Run: `pytest tests/scanner/test_market_analyzer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.scanner.market_analyzer'`

- [ ] **Step 10: Implement the market analyzer**

Create `tradingbot/scanner/market_analyzer.py`:

```python
"""LLM call 1: narrow the filtered candidate pool to high conviction names."""

from __future__ import annotations

import logging

from tradingbot.core.config import ScannerConfig
from tradingbot.core.llm.provider import LLMProvider
from tradingbot.core.models import MarketContext, ShortlistedStock, Stock, StrategyName

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an expert Indian equity market analyst specialising in intraday trading "
    "on the NSE. You identify stocks with the highest probability of a significant "
    "intraday move, based on technical setups, market context, and institutional "
    "activity. You only ever choose from the candidate list you are given. You never "
    "invent a ticker, and you never recommend a stock you cannot justify from the "
    "supplied data."
)

SHORTLIST_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "reasoning": {"type": "string"},
                    "suggested_strategy": {
                        "type": "string",
                        "enum": ["breakout", "momentum", "mean_reversion", "vwap_bounce", "orb"],
                    },
                    "direction_bias": {"type": "string", "enum": ["long", "short", "neutral"]},
                    "key_levels": {"type": "array", "items": {"type": "number"}},
                },
                "required": [
                    "symbol",
                    "reasoning",
                    "suggested_strategy",
                    "direction_bias",
                    "key_levels",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["picks"],
    "additionalProperties": False,
}


class MarketAnalyzer:
    """Wraps the shortlist LLM call and validates everything it returns."""

    def __init__(self, provider: LLMProvider, config: ScannerConfig) -> None:
        self.provider = provider
        self.config = config

    async def shortlist(
        self,
        stocks: list[Stock],
        context: MarketContext,
    ) -> list[ShortlistedStock]:
        if not stocks:
            logger.warning("no candidates survived filtering; skipping the LLM call")
            return []

        payload = await self.provider.analyze(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=self._build_prompt(stocks, context),
            tool_name="submit_shortlist",
            tool_description="Return the intraday candidates chosen from the supplied list.",
            input_schema=SHORTLIST_SCHEMA,
        )

        allowed = {stock.symbol for stock in stocks}
        picks: list[ShortlistedStock] = []

        for raw in payload.get("picks", []):
            symbol = str(raw.get("symbol", "")).upper()
            if symbol not in allowed:
                logger.warning("dropping %s: not in the candidate pool", symbol or "<blank>")
                continue
            try:
                strategy = StrategyName(raw["suggested_strategy"])
            except (KeyError, ValueError):
                logger.warning("dropping %s: unknown strategy %r", symbol, raw.get("suggested_strategy"))
                continue

            picks.append(
                ShortlistedStock(
                    symbol=symbol,
                    reasoning=str(raw.get("reasoning", "")),
                    suggested_strategy=strategy,
                    direction_bias=str(raw.get("direction_bias", "neutral")),
                    key_levels=[float(level) for level in raw.get("key_levels", [])],
                )
            )

        return picks[: self.config.llm_pick_count]

    def _build_prompt(self, stocks: list[Stock], context: MarketContext) -> str:
        rows = "\n".join(
            f"| {stock.symbol} | {stock.sector} | {stock.last_price:.2f} | "
            f"{stock.avg_volume:,.0f} | {stock.market_cap_cr:,.0f} | {stock.atr_pct:.2f} |"
            for stock in stocks
        )
        return (
            "MARKET CONTEXT\n"
            f"Nifty: {context.nifty_level:.0f} ({context.nifty_trend})\n"
            f"Bank Nifty: {context.banknifty_trend}\n"
            f"India VIX: {context.india_vix:.2f}\n"
            f"FII net: {context.fii_net_cr:+.0f} Cr | DII net: {context.dii_net_cr:+.0f} Cr\n"
            f"Global cues: {context.global_cues}\n"
            f"Leading sectors: {', '.join(context.sector_leaders) or 'n/a'}\n"
            f"Lagging sectors: {', '.join(context.sector_laggards) or 'n/a'}\n"
            f"Regime: {context.regime.value}\n\n"
            "CANDIDATES (all passed liquidity, price, market cap, and volatility screens)\n"
            "| Symbol | Sector | Price | Avg Volume | Market Cap (Cr) | ATR % |\n"
            "|---|---|---|---|---|---|\n"
            f"{rows}\n\n"
            f"TASK\nSelect at most {self.config.llm_pick_count} of these stocks that are most "
            "suitable for an intraday trade on the next session. Use only symbols from the "
            "table above. For each pick, give your reasoning, the strategy type that best "
            "suits the setup, a direction bias, and the key price levels that matter."
        )
```

- [ ] **Step 11: Write the failing test for the scanner orchestrator (covers Review Focus item 5)**

Create `tests/scanner/test_scanner.py`:

```python
from datetime import date

import pytest

from tradingbot.core.config import ScannerConfig
from tradingbot.core.models import MarketContext, MarketRegime, ShortlistedStock, Stock, StrategyName
from tradingbot.scanner.calendar import NotATradingDayError
from tradingbot.scanner.scanner import Scanner


class StubFetcher:
    def __init__(self, stocks):
        self.stocks = stocks
        self.universe_calls = 0

    def fetch_universe(self):
        self.universe_calls += 1
        return [stock.symbol for stock in self.stocks]

    def fetch_stock_metrics(self, symbols):
        return [stock for stock in self.stocks if stock.symbol in set(symbols)]


class StubContextFetcher:
    def __init__(self):
        self.calls = 0

    def fetch(self):
        self.calls += 1
        return MarketContext(
            nifty_level=25400.0,
            nifty_trend="bullish",
            banknifty_trend="bullish",
            india_vix=12.5,
            fii_net_cr=2300.0,
            dii_net_cr=-800.0,
            global_cues="US flat",
            sector_leaders=["IT"],
            sector_laggards=["FMCG"],
            regime=MarketRegime.TRENDING,
        )


class StubAnalyzer:
    def __init__(self, picks):
        self.picks = picks
        self.seen_stocks = None

    async def shortlist(self, stocks, context):
        self.seen_stocks = stocks
        return self.picks


def make_config() -> ScannerConfig:
    return ScannerConfig(
        min_volume=500000,
        min_price=50.0,
        max_price=5000.0,
        min_market_cap_cr=5000.0,
        min_atr_pct=0.5,
        max_stocks_to_llm=100,
        llm_pick_count=15,
    )


def make_stock(symbol, avg_volume=1_000_000.0) -> Stock:
    return Stock(
        symbol=symbol,
        exchange="NSE",
        last_price=100.0,
        avg_volume=avg_volume,
        market_cap_cr=50000.0,
        atr_pct=1.2,
        sector="IT",
    )


def make_pick(symbol) -> ShortlistedStock:
    return ShortlistedStock(
        symbol=symbol,
        reasoning="Looks good.",
        suggested_strategy=StrategyName.BREAKOUT,
        direction_bias="long",
        key_levels=[100.0],
    )


async def test_scan_returns_the_shortlist_and_the_context():
    fetcher = StubFetcher([make_stock("RELIANCE"), make_stock("TCS")])
    context_fetcher = StubContextFetcher()
    analyzer = StubAnalyzer([make_pick("RELIANCE")])
    scanner = Scanner(fetcher, context_fetcher, analyzer, make_config())

    result = await scanner.scan(date(2026, 9, 24))

    assert result.trade_date == date(2026, 9, 24)
    assert [pick.symbol for pick in result.shortlist] == ["RELIANCE"]
    assert result.context.nifty_level == pytest.approx(25400.0)
    assert context_fetcher.calls == 1


async def test_scan_only_sends_filtered_stocks_to_the_analyzer():
    fetcher = StubFetcher([make_stock("RELIANCE"), make_stock("ILLIQUID", avg_volume=10.0)])
    analyzer = StubAnalyzer([])
    scanner = Scanner(fetcher, StubContextFetcher(), analyzer, make_config())

    await scanner.scan(date(2026, 9, 24))

    assert [stock.symbol for stock in analyzer.seen_stocks] == ["RELIANCE"]


async def test_scan_records_why_stocks_were_rejected():
    fetcher = StubFetcher([make_stock("RELIANCE"), make_stock("ILLIQUID", avg_volume=10.0)])
    scanner = Scanner(fetcher, StubContextFetcher(), StubAnalyzer([]), make_config())

    result = await scanner.scan(date(2026, 9, 24))

    assert result.filter_result.rejected == {"volume": 1}


async def test_scan_refuses_a_saturday():
    scanner = Scanner(StubFetcher([]), StubContextFetcher(), StubAnalyzer([]), make_config())

    with pytest.raises(NotATradingDayError, match="2026-09-26"):
        await scanner.scan(date(2026, 9, 26))


async def test_scan_refuses_an_nse_holiday():
    scanner = Scanner(StubFetcher([]), StubContextFetcher(), StubAnalyzer([]), make_config())

    with pytest.raises(NotATradingDayError, match="2026-08-15"):
        await scanner.scan(date(2026, 8, 15))


async def test_scan_does_no_network_work_on_a_non_trading_day():
    fetcher = StubFetcher([make_stock("RELIANCE")])
    context_fetcher = StubContextFetcher()
    scanner = Scanner(fetcher, context_fetcher, StubAnalyzer([]), make_config())

    with pytest.raises(NotATradingDayError):
        await scanner.scan(date(2026, 9, 27))

    assert fetcher.universe_calls == 0
    assert context_fetcher.calls == 0
```

- [ ] **Step 12: Run the scanner tests to verify they fail**

Run: `pytest tests/scanner/test_scanner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.scanner.scanner'`

- [ ] **Step 13: Implement the scanner orchestrator**

Create `tradingbot/scanner/scanner.py`:

```python
"""Scanner agent: universe to filters to market context to LLM shortlist."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from tradingbot.core.config import ScannerConfig
from tradingbot.core.models import MarketContext, ShortlistedStock
from tradingbot.scanner.calendar import NotATradingDayError, is_trading_day
from tradingbot.scanner.filters import FilterResult, apply_filters

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Everything the strategy agent needs from the scanner."""

    trade_date: date
    context: MarketContext
    shortlist: list[ShortlistedStock]
    filter_result: FilterResult


class Scanner:
    """Runs the full pre-market narrowing pipeline for one trade date."""

    def __init__(self, fetcher, context_fetcher, analyzer, config: ScannerConfig) -> None:
        self.fetcher = fetcher
        self.context_fetcher = context_fetcher
        self.analyzer = analyzer
        self.config = config

    async def scan(self, trade_date: date) -> ScanResult:
        if not is_trading_day(trade_date):
            raise NotATradingDayError(
                f"{trade_date.isoformat()} is not an NSE trading day; nothing to plan"
            )

        symbols = self.fetcher.fetch_universe()
        logger.info("universe contains %d symbols", len(symbols))

        stocks = self.fetcher.fetch_stock_metrics(symbols)
        filter_result = apply_filters(stocks, self.config)
        logger.info(
            "%d/%d symbols passed filters (rejected: %s)",
            len(filter_result.passed),
            len(stocks),
            filter_result.rejected or "none",
        )

        context = self.context_fetcher.fetch()
        shortlist = await self.analyzer.shortlist(filter_result.passed, context)
        logger.info("LLM shortlisted %d candidates", len(shortlist))

        return ScanResult(
            trade_date=trade_date,
            context=context,
            shortlist=shortlist,
            filter_result=filter_result,
        )
```

- [ ] **Step 14: Run the full test suite to verify it passes**

Run: `pytest tests/ -v`
Expected: PASS — 98 tests.

- [ ] **Step 15: Commit**

```bash
git add tradingbot/scanner/ tests/scanner/
git commit -m "feat: add trading calendar, market context, and LLM-driven scanner"
```

---

## Task 7: Risk Manager

**Files:**
- Create: `tradingbot/core/risk_manager.py`
- Test: `tests/core/test_risk_manager.py`

**Interfaces:**
- Consumes: `TradeSetup`, `TradeLeg`, `TradePlan`, `Direction` (Task 1); `RiskConfig`, `StrategyConfig` (Task 1).
- Produces:
  - `RiskManager(risk_config: RiskConfig, strategy_config: StrategyConfig, capital: float)`.
  - `position_size(setup: TradeSetup) -> int`
  - `risk_amount_for(setup: TradeSetup, quantity: int) -> float`
  - `vet_setup(setup: TradeSetup) -> str | None` — returns a rejection reason or `None`.
  - `select_legs(setups: list[TradeSetup], max_entry_wait, exit_before) -> list[TradeLeg]`
  - `vet_plan_for_execution(plan, now, available_capital) -> list[str]` — Layer 2 blocking reasons.
  - `vet_leg_at_open(leg: TradeLeg, current_price: float) -> str | None` — Layer 2 per-leg check.
  - `daily_loss_breached(realised_pnl: float) -> bool` — Layer 3 kill switch.
  - `InvalidSetupError`

- [ ] **Step 1: Write the failing test (covers Review Focus item 1)**

Create `tests/core/test_risk_manager.py`:

```python
from datetime import datetime, time

import pytest

from tradingbot.core.config import RiskConfig, StrategyConfig
from tradingbot.core.models import (
    IST,
    Direction,
    EntryType,
    MarketRegime,
    StrategyName,
    TradePlan,
    TradeSetup,
)
from tradingbot.core.risk_manager import InvalidSetupError, RiskManager


def make_risk_config(**overrides) -> RiskConfig:
    defaults = {
        "max_risk_per_trade_pct": 0.01,
        "max_daily_loss_pct": 0.02,
        "max_capital_deployed_pct": 0.50,
        "max_concurrent_positions": 2,
    }
    defaults.update(overrides)
    return RiskConfig(**defaults)


def make_strategy_config(**overrides) -> StrategyConfig:
    defaults = {
        "backtest_days": 30,
        "candle_interval": "15minute",
        "min_confidence": 0.5,
        "min_reward_risk": 1.5,
        "max_trades_per_day": 2,
    }
    defaults.update(overrides)
    return StrategyConfig(**defaults)


def make_manager(capital=400000.0, **risk_overrides) -> RiskManager:
    return RiskManager(make_risk_config(**risk_overrides), make_strategy_config(), capital)


def make_setup(
    symbol="RELIANCE",
    entry=2855.0,
    stop=2830.0,
    target_1=2890.0,
    target_2=2920.0,
    confidence=0.72,
    direction=Direction.LONG,
) -> TradeSetup:
    return TradeSetup(
        symbol=symbol,
        strategy=StrategyName.BREAKOUT,
        direction=direction,
        entry_price=entry,
        entry_type=EntryType.LIMIT,
        stop_loss=stop,
        target_1=target_1,
        target_2=target_2,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        confidence=confidence,
        reasoning="Setup under test.",
    )


def make_plan(legs, generated_at=datetime(2026, 9, 23, 22, 0, tzinfo=IST)) -> TradePlan:
    return TradePlan(
        trade_date="2026-09-24",
        generated_at=generated_at,
        capital=400000.0,
        max_risk_per_trade_pct=0.01,
        max_daily_loss_pct=0.02,
        market_regime=MarketRegime.TRENDING,
        market_summary="Nifty bullish.",
        legs=legs,
    )


def test_position_size_uses_risk_divided_by_stop_distance():
    manager = make_manager()

    # 1% of 400000 = 4000 risk budget; 25 rupees of risk per share -> 160 shares.
    assert manager.position_size(make_setup()) == 160


def test_position_size_is_floored_not_rounded_up():
    manager = make_manager(max_risk_per_trade_pct=0.01)

    # 4000 / 30 = 133.33 -> 133 shares.
    assert manager.position_size(make_setup(entry=100.0, stop=70.0)) == 133


def test_position_size_is_capped_by_deployable_capital():
    manager = make_manager(max_capital_deployed_pct=0.10)

    # Risk sizing wants 4000/1 = 4000 shares, but 10% of 400000 at 100/share allows 400.
    assert manager.position_size(make_setup(entry=100.0, stop=99.0)) == 400


def test_stop_loss_equal_to_entry_raises_invalid_setup():
    manager = make_manager()

    with pytest.raises(InvalidSetupError, match="stop loss equals entry"):
        manager.position_size(make_setup(entry=100.0, stop=100.0))


def test_stop_loss_within_a_rounding_hair_of_entry_also_raises():
    manager = make_manager()

    with pytest.raises(InvalidSetupError, match="stop loss equals entry"):
        manager.position_size(make_setup(entry=100.0, stop=100.0000001))


def test_short_setups_size_on_the_absolute_stop_distance():
    manager = make_manager()

    setup = make_setup(direction=Direction.SHORT, entry=100.0, stop=110.0, target_1=85.0, target_2=80.0)

    assert manager.position_size(setup) == 400


def test_risk_amount_is_quantity_times_stop_distance():
    manager = make_manager()

    assert manager.risk_amount_for(make_setup(), quantity=160) == pytest.approx(4000.0)


def test_vet_setup_accepts_a_healthy_setup():
    assert make_manager().vet_setup(make_setup()) is None


def test_vet_setup_rejects_low_confidence():
    assert make_manager().vet_setup(make_setup(confidence=0.3)) == "confidence below minimum"


def test_vet_setup_rejects_poor_reward_to_risk():
    # 25 of risk against 25 of reward is 1.0, below the 1.5 minimum.
    assert make_manager().vet_setup(make_setup(target_1=2880.0)) == "reward:risk below minimum"


def test_vet_setup_rejects_a_long_whose_stop_sits_above_entry():
    assert make_manager().vet_setup(make_setup(stop=2900.0)) == "stop loss on the wrong side of entry"


def test_vet_setup_rejects_a_long_whose_target_sits_below_entry():
    assert make_manager().vet_setup(make_setup(target_1=2800.0)) == "target on the wrong side of entry"


def test_vet_setup_rejects_a_zero_width_stop():
    assert make_manager().vet_setup(make_setup(stop=2855.0)) == "stop loss equals entry price"


def test_select_legs_keeps_only_the_highest_confidence_setups():
    manager = make_manager()
    setups = [
        make_setup(symbol="A", confidence=0.6),
        make_setup(symbol="B", confidence=0.9),
        make_setup(symbol="C", confidence=0.75),
    ]

    legs = manager.select_legs(setups, max_entry_wait=time(11, 0), exit_before=time(15, 10))

    assert [leg.symbol for leg in legs] == ["B", "C"]


def test_select_legs_drops_setups_that_fail_vetting():
    manager = make_manager()
    setups = [make_setup(symbol="GOOD", confidence=0.9), make_setup(symbol="WEAK", confidence=0.2)]

    legs = manager.select_legs(setups, max_entry_wait=time(11, 0), exit_before=time(15, 10))

    assert [leg.symbol for leg in legs] == ["GOOD"]


def test_select_legs_drops_setups_that_would_size_to_zero_shares():
    manager = make_manager(max_risk_per_trade_pct=0.0001)
    setups = [make_setup(symbol="TOOBIG", entry=5000.0, stop=1000.0, target_1=12000.0, confidence=0.9)]

    assert manager.select_legs(setups, max_entry_wait=time(11, 0), exit_before=time(15, 10)) == []


def test_select_legs_stops_adding_once_total_exposure_is_reached():
    manager = make_manager(max_capital_deployed_pct=0.05, max_concurrent_positions=2)
    setups = [
        make_setup(symbol="A", entry=100.0, stop=95.0, target_1=115.0, confidence=0.9),
        make_setup(symbol="B", entry=100.0, stop=95.0, target_1=115.0, confidence=0.8),
    ]

    legs = manager.select_legs(setups, max_entry_wait=time(11, 0), exit_before=time(15, 10))

    total_notional = sum(leg.notional for leg in legs)
    assert total_notional <= 0.05 * 400000.0


def test_select_legs_carries_the_sized_quantity_and_risk_onto_the_leg():
    manager = make_manager()

    legs = manager.select_legs([make_setup()], max_entry_wait=time(11, 0), exit_before=time(15, 10))

    assert legs[0].quantity == 160
    assert legs[0].risk_amount == pytest.approx(4000.0)
    assert legs[0].max_entry_wait == time(11, 0)
    assert legs[0].exit_before == time(15, 10)


def test_a_fresh_plan_passes_pre_execution_vetting():
    manager = make_manager()
    legs = manager.select_legs([make_setup()], max_entry_wait=time(11, 0), exit_before=time(15, 10))
    plan = make_plan(legs)

    blockers = manager.vet_plan_for_execution(
        plan, now=datetime(2026, 9, 24, 9, 0, tzinfo=IST), available_capital=400000.0
    )

    assert blockers == []


def test_a_stale_plan_is_blocked():
    manager = make_manager()
    plan = make_plan([], generated_at=datetime(2026, 9, 22, 8, 0, tzinfo=IST))

    blockers = manager.vet_plan_for_execution(
        plan, now=datetime(2026, 9, 24, 9, 0, tzinfo=IST), available_capital=400000.0
    )

    assert any("stale" in reason for reason in blockers)


def test_insufficient_capital_blocks_the_plan():
    manager = make_manager()
    legs = manager.select_legs([make_setup()], max_entry_wait=time(11, 0), exit_before=time(15, 10))
    plan = make_plan(legs)

    blockers = manager.vet_plan_for_execution(
        plan, now=datetime(2026, 9, 24, 9, 0, tzinfo=IST), available_capital=100.0
    )

    assert any("capital" in reason for reason in blockers)


def test_vet_leg_at_open_accepts_a_price_that_has_barely_moved():
    manager = make_manager()
    leg = manager.select_legs([make_setup()], max_entry_wait=time(11, 0), exit_before=time(15, 10))[0]

    assert manager.vet_leg_at_open(leg, current_price=2860.0) is None


def test_vet_leg_at_open_rejects_a_price_that_gapped_away():
    manager = make_manager()
    leg = manager.select_legs([make_setup()], max_entry_wait=time(11, 0), exit_before=time(15, 10))[0]

    reason = manager.vet_leg_at_open(leg, current_price=3100.0)

    assert reason is not None
    assert "drifted" in reason


def test_daily_loss_kill_switch_trips_at_the_configured_threshold():
    manager = make_manager()

    assert manager.daily_loss_breached(-7999.0) is False
    assert manager.daily_loss_breached(-8000.0) is True
    assert manager.daily_loss_breached(-9000.0) is True


def test_daily_loss_kill_switch_ignores_profits():
    assert make_manager().daily_loss_breached(5000.0) is False
```

- [ ] **Step 2: Run the risk manager tests to verify they fail**

Run: `pytest tests/core/test_risk_manager.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.core.risk_manager'`

- [ ] **Step 3: Implement the risk manager**

Create `tradingbot/core/risk_manager.py`:

```python
"""Three layers of risk control: sizing at analysis time, gates before the open,
and a kill switch during the session."""

from __future__ import annotations

import logging
import math
from datetime import datetime, time

from tradingbot.core.config import RiskConfig, StrategyConfig
from tradingbot.core.models import Direction, TradeLeg, TradePlan, TradeSetup

logger = logging.getLogger(__name__)

# A stop this close to entry is a data error, not a tight stop: sizing against it
# would produce an absurd quantity.
MIN_STOP_DISTANCE = 0.01

DEFAULT_PLAN_MAX_AGE_HOURS = 14.0
DEFAULT_MAX_ENTRY_DRIFT_PCT = 2.0


class InvalidSetupError(Exception):
    """Raised when a setup cannot be sized because its numbers are nonsensical."""


class RiskManager:
    """Owns every number that decides how much money is at risk."""

    def __init__(
        self,
        risk_config: RiskConfig,
        strategy_config: StrategyConfig,
        capital: float,
        plan_max_age_hours: float = DEFAULT_PLAN_MAX_AGE_HOURS,
        max_entry_price_drift_pct: float = DEFAULT_MAX_ENTRY_DRIFT_PCT,
    ) -> None:
        self.risk = risk_config
        self.strategy = strategy_config
        self.capital = capital
        self.plan_max_age_hours = plan_max_age_hours
        self.max_entry_price_drift_pct = max_entry_price_drift_pct

    # ----- Layer 1: analysis time -------------------------------------------------

    def position_size(self, setup: TradeSetup) -> int:
        """Shares to trade, from the risk budget, capped by deployable capital."""
        stop_distance = abs(setup.entry_price - setup.stop_loss)
        if stop_distance < MIN_STOP_DISTANCE:
            raise InvalidSetupError(
                f"{setup.symbol}: stop loss equals entry price "
                f"({setup.stop_loss} vs {setup.entry_price}); cannot size the position"
            )

        risk_budget = self.capital * self.risk.max_risk_per_trade_pct
        by_risk = math.floor(risk_budget / stop_distance)

        deployable = self.capital * self.risk.max_capital_deployed_pct
        by_capital = math.floor(deployable / setup.entry_price) if setup.entry_price > 0 else 0

        return max(0, min(by_risk, by_capital))

    def risk_amount_for(self, setup: TradeSetup, quantity: int) -> float:
        return abs(setup.entry_price - setup.stop_loss) * quantity

    def vet_setup(self, setup: TradeSetup) -> str | None:
        """Return why this setup is unacceptable, or None when it is fine."""
        if abs(setup.entry_price - setup.stop_loss) < MIN_STOP_DISTANCE:
            return "stop loss equals entry price"

        if setup.direction is Direction.LONG:
            if setup.stop_loss >= setup.entry_price:
                return "stop loss on the wrong side of entry"
            if setup.target_1 <= setup.entry_price:
                return "target on the wrong side of entry"
        else:
            if setup.stop_loss <= setup.entry_price:
                return "stop loss on the wrong side of entry"
            if setup.target_1 >= setup.entry_price:
                return "target on the wrong side of entry"

        if setup.confidence < self.strategy.min_confidence:
            return "confidence below minimum"
        if setup.reward_risk < self.strategy.min_reward_risk:
            return "reward:risk below minimum"
        return None

    def select_legs(
        self,
        setups: list[TradeSetup],
        max_entry_wait: time,
        exit_before: time,
    ) -> list[TradeLeg]:
        """Rank by confidence, size each survivor, stop at the exposure ceiling."""
        ranked = sorted(setups, key=lambda setup: setup.confidence, reverse=True)
        max_legs = min(self.strategy.max_trades_per_day, self.risk.max_concurrent_positions)
        exposure_ceiling = self.capital * self.risk.max_capital_deployed_pct

        legs: list[TradeLeg] = []
        deployed = 0.0

        for setup in ranked:
            if len(legs) >= max_legs:
                break

            reason = self.vet_setup(setup)
            if reason is not None:
                logger.info("dropping %s: %s", setup.symbol, reason)
                continue

            quantity = self.position_size(setup)
            if quantity <= 0:
                logger.info("dropping %s: position sizes to zero shares", setup.symbol)
                continue

            notional = quantity * setup.entry_price
            if deployed + notional > exposure_ceiling:
                logger.info("dropping %s: would exceed the exposure ceiling", setup.symbol)
                continue

            legs.append(
                setup.to_leg(
                    quantity=quantity,
                    risk_amount=self.risk_amount_for(setup, quantity),
                    max_entry_wait=max_entry_wait,
                    exit_before=exit_before,
                )
            )
            deployed += notional

        return legs

    # ----- Layer 2: before the open -----------------------------------------------

    def vet_plan_for_execution(
        self,
        plan: TradePlan,
        now: datetime,
        available_capital: float,
    ) -> list[str]:
        """Return every reason this plan must not be executed. Empty means go."""
        blockers: list[str] = []

        age = plan.age_hours(now)
        if age > self.plan_max_age_hours:
            blockers.append(
                f"plan is stale: generated {age:.1f}h ago, limit is {self.plan_max_age_hours:.0f}h"
            )

        required = sum(leg.notional for leg in plan.legs)
        if required > available_capital:
            blockers.append(
                f"insufficient capital: plan needs {required:,.0f} but {available_capital:,.0f} is available"
            )

        if len(plan.legs) > self.risk.max_concurrent_positions:
            blockers.append(
                f"plan has {len(plan.legs)} legs, above the {self.risk.max_concurrent_positions} position limit"
            )

        return blockers

    def vet_leg_at_open(self, leg: TradeLeg, current_price: float) -> str | None:
        """Reject a leg whose market price has run away from the planned entry."""
        if leg.entry_price <= 0:
            return "planned entry price is not positive"

        drift_pct = abs(current_price - leg.entry_price) / leg.entry_price * 100.0
        if drift_pct > self.max_entry_price_drift_pct:
            return (
                f"price drifted {drift_pct:.2f}% from the planned entry "
                f"({leg.entry_price:.2f} -> {current_price:.2f})"
            )
        return None

    # ----- Layer 3: during the session --------------------------------------------

    def daily_loss_breached(self, realised_pnl: float) -> bool:
        """True once the day's realised loss reaches the configured cap."""
        limit = self.capital * self.risk.max_daily_loss_pct
        return realised_pnl <= -limit
```

- [ ] **Step 4: Run the risk manager tests to verify they pass**

Run: `pytest tests/core/test_risk_manager.py -v`
Expected: PASS — 25 tests.

- [ ] **Step 5: Commit**

```bash
git add tradingbot/core/risk_manager.py tests/core/test_risk_manager.py
git commit -m "feat: add three-layer risk manager with position sizing and kill switch"
```

---

## Task 8: Strategy Library

**Files:**
- Create: `tradingbot/strategy/strategies/__init__.py`
- Create: `tradingbot/strategy/strategies/base.py`
- Create: `tradingbot/strategy/strategies/breakout.py`
- Create: `tradingbot/strategy/strategies/momentum.py`
- Create: `tradingbot/strategy/strategies/mean_reversion.py`
- Create: `tradingbot/strategy/strategies/vwap_bounce.py`
- Create: `tradingbot/strategy/strategies/orb.py`
- Test: `tests/strategy/test_strategies.py`

**Interfaces:**
- Consumes: `IndicatorSnapshot`, `StrategyName`, `Direction` (Task 1); indicator functions (Task 4).
- Produces:
  - `Signal` dataclass: `direction: Direction`, `entry_price: float`, `stop_loss: float`, `target_1: float`, `target_2: float`, `strength: float`.
  - `Strategy` ABC: `name: StrategyName` class attribute, `generate_signal(df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None`.
  - `BreakoutStrategy`, `MomentumStrategy`, `MeanReversionStrategy`, `VWAPBounceStrategy`, `ORBStrategy`.
  - `STRATEGY_REGISTRY: dict[StrategyName, Strategy]` and `all_strategies() -> list[Strategy]`.

Every strategy sets its stop and targets from ATR so that the risk:reward geometry is consistent: stop at 1 ATR, target 1 at 2 ATR, target 2 at 3 ATR from entry.

- [ ] **Step 1: Write the failing test for the strategy library**

Create `tests/strategy/test_strategies.py`:

```python
import numpy as np
import pandas as pd
import pytest

from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies import STRATEGY_REGISTRY, all_strategies
from tradingbot.strategy.strategies.base import Signal, Strategy
from tradingbot.strategy.strategies.breakout import BreakoutStrategy
from tradingbot.strategy.strategies.mean_reversion import MeanReversionStrategy
from tradingbot.strategy.strategies.momentum import MomentumStrategy
from tradingbot.strategy.strategies.orb import ORBStrategy
from tradingbot.strategy.strategies.vwap_bounce import VWAPBounceStrategy


def make_candles(closes, volumes=None, spread=1.0):
    index = pd.date_range("2026-09-24 09:15", periods=len(closes), freq="15min", tz="Asia/Kolkata")
    closes = np.asarray(closes, dtype=float)
    volumes = np.full(len(closes), 10000.0) if volumes is None else np.asarray(volumes, dtype=float)
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes + spread,
            "low": closes - spread,
            "close": closes,
            "volume": volumes,
        },
        index=index,
    )


def make_snapshot(**overrides) -> IndicatorSnapshot:
    defaults = {
        "symbol": "RELIANCE",
        "last_close": 100.0,
        "rsi_14": 55.0,
        "macd": 0.5,
        "macd_signal": 0.2,
        "bb_upper": 108.0,
        "bb_middle": 100.0,
        "bb_lower": 92.0,
        "atr_14": 2.0,
        "sma_20": 98.0,
        "sma_50": 95.0,
        "sma_200": 90.0,
        "ema_12": 99.0,
        "ema_26": 97.0,
        "vwap": 99.0,
        "pivot": 100.0,
        "support_levels": [95.0, 90.0],
        "resistance_levels": [105.0, 110.0],
    }
    defaults.update(overrides)
    return IndicatorSnapshot(**defaults)


def test_registry_contains_every_strategy_name():
    assert set(STRATEGY_REGISTRY) == set(StrategyName)


def test_all_strategies_returns_one_instance_per_name():
    strategies = all_strategies()

    assert len(strategies) == len(StrategyName)
    assert all(isinstance(strategy, Strategy) for strategy in strategies)


def test_strategy_abc_cannot_be_instantiated():
    with pytest.raises(TypeError):
        Strategy()


@pytest.mark.parametrize(
    "strategy",
    [
        BreakoutStrategy(),
        MomentumStrategy(),
        MeanReversionStrategy(),
        VWAPBounceStrategy(),
        ORBStrategy(),
    ],
)
def test_every_strategy_returns_none_or_a_well_formed_signal(strategy):
    df = make_candles(100 + np.cumsum(np.random.default_rng(3).normal(0, 1, 60)))
    signal = strategy.generate_signal(df, make_snapshot())

    if signal is not None:
        assert isinstance(signal, Signal)
        assert 0.0 <= signal.strength <= 1.0
        assert signal.stop_loss != signal.entry_price


@pytest.mark.parametrize(
    "strategy",
    [
        BreakoutStrategy(),
        MomentumStrategy(),
        MeanReversionStrategy(),
        VWAPBounceStrategy(),
        ORBStrategy(),
    ],
)
def test_no_strategy_mutates_the_candle_frame(strategy):
    df = make_candles(100 + np.cumsum(np.random.default_rng(5).normal(0, 1, 60)))
    before = df.copy(deep=True)

    strategy.generate_signal(df, make_snapshot())

    pd.testing.assert_frame_equal(df, before)


def test_breakout_goes_long_when_price_clears_resistance_on_volume():
    df = make_candles([100.0] * 30 + [106.0], volumes=[10000.0] * 30 + [50000.0])
    snapshot = make_snapshot(last_close=106.0, resistance_levels=[105.0], rsi_14=62.0)

    signal = BreakoutStrategy().generate_signal(df, snapshot)

    assert signal is not None
    assert signal.direction is Direction.LONG
    assert signal.entry_price == pytest.approx(106.0)


def test_breakout_is_silent_when_price_is_inside_the_range():
    df = make_candles([100.0] * 31)
    snapshot = make_snapshot(last_close=100.0, resistance_levels=[105.0], support_levels=[95.0])

    assert BreakoutStrategy().generate_signal(df, snapshot) is None


def test_breakout_stop_and_targets_follow_the_atr_geometry():
    df = make_candles([100.0] * 30 + [106.0], volumes=[10000.0] * 30 + [50000.0])
    snapshot = make_snapshot(last_close=106.0, resistance_levels=[105.0], rsi_14=62.0, atr_14=2.0)

    signal = BreakoutStrategy().generate_signal(df, snapshot)

    assert signal.stop_loss == pytest.approx(104.0)
    assert signal.target_1 == pytest.approx(110.0)
    assert signal.target_2 == pytest.approx(112.0)


def test_momentum_goes_long_when_trend_and_macd_agree():
    df = make_candles(np.arange(100, 160, dtype=float))
    snapshot = make_snapshot(
        last_close=159.0, sma_20=150.0, sma_50=140.0, macd=1.5, macd_signal=0.8, rsi_14=65.0
    )

    signal = MomentumStrategy().generate_signal(df, snapshot)

    assert signal is not None
    assert signal.direction is Direction.LONG


def test_momentum_is_silent_when_rsi_is_already_overbought():
    df = make_candles(np.arange(100, 160, dtype=float))
    snapshot = make_snapshot(
        last_close=159.0, sma_20=150.0, sma_50=140.0, macd=1.5, macd_signal=0.8, rsi_14=85.0
    )

    assert MomentumStrategy().generate_signal(df, snapshot) is None


def test_mean_reversion_goes_long_when_price_is_oversold_at_the_lower_band():
    df = make_candles([100.0] * 30 + [91.0])
    snapshot = make_snapshot(last_close=91.0, bb_lower=92.0, bb_middle=100.0, rsi_14=25.0)

    signal = MeanReversionStrategy().generate_signal(df, snapshot)

    assert signal is not None
    assert signal.direction is Direction.LONG


def test_mean_reversion_goes_short_when_price_is_overbought_at_the_upper_band():
    df = make_candles([100.0] * 30 + [109.0])
    snapshot = make_snapshot(last_close=109.0, bb_upper=108.0, bb_middle=100.0, rsi_14=78.0)

    signal = MeanReversionStrategy().generate_signal(df, snapshot)

    assert signal is not None
    assert signal.direction is Direction.SHORT


def test_mean_reversion_is_silent_inside_the_bands():
    df = make_candles([100.0] * 31)
    snapshot = make_snapshot(last_close=100.0, rsi_14=50.0)

    assert MeanReversionStrategy().generate_signal(df, snapshot) is None


def test_vwap_bounce_goes_long_when_price_reclaims_vwap_in_an_uptrend():
    df = make_candles([100.0] * 30 + [99.2])
    snapshot = make_snapshot(last_close=99.2, vwap=99.0, sma_20=95.0, sma_50=92.0, rsi_14=52.0)

    signal = VWAPBounceStrategy().generate_signal(df, snapshot)

    assert signal is not None
    assert signal.direction is Direction.LONG


def test_vwap_bounce_is_silent_when_price_is_far_from_vwap():
    df = make_candles([100.0] * 30 + [130.0])
    snapshot = make_snapshot(last_close=130.0, vwap=99.0, sma_20=95.0, sma_50=92.0)

    assert VWAPBounceStrategy().generate_signal(df, snapshot) is None


def test_orb_goes_long_when_price_breaks_the_opening_range_high():
    closes = [100.0, 101.0, 100.5, 100.8] + [103.0]
    df = make_candles(closes, spread=0.5)
    snapshot = make_snapshot(last_close=103.0)

    signal = ORBStrategy().generate_signal(df, snapshot)

    assert signal is not None
    assert signal.direction is Direction.LONG


def test_orb_goes_short_when_price_breaks_the_opening_range_low():
    closes = [100.0, 101.0, 100.5, 100.8] + [97.0]
    df = make_candles(closes, spread=0.5)
    snapshot = make_snapshot(last_close=97.0)

    signal = ORBStrategy().generate_signal(df, snapshot)

    assert signal is not None
    assert signal.direction is Direction.SHORT


def test_orb_needs_more_candles_than_the_opening_range():
    df = make_candles([100.0, 101.0])

    assert ORBStrategy().generate_signal(df, make_snapshot()) is None
```

- [ ] **Step 2: Run the strategy tests to verify they fail**

Run: `pytest tests/strategy/test_strategies.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.strategy.strategies'`

- [ ] **Step 3: Implement the strategy base**

Create `tradingbot/strategy/strategies/base.py`:

```python
"""Contract every strategy implements, plus the shared ATR risk geometry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd

from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName

STOP_ATR_MULTIPLE = 1.0
TARGET_1_ATR_MULTIPLE = 2.0
TARGET_2_ATR_MULTIPLE = 3.0


@dataclass(frozen=True)
class Signal:
    """A strategy's raw opinion, before risk sizing or LLM review."""

    direction: Direction
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    strength: float


def build_signal(
    direction: Direction,
    entry_price: float,
    atr: float,
    strength: float,
) -> Signal:
    """Place the stop at 1 ATR and the targets at 2 and 3 ATR from entry."""
    sign = 1.0 if direction is Direction.LONG else -1.0
    return Signal(
        direction=direction,
        entry_price=entry_price,
        stop_loss=entry_price - sign * STOP_ATR_MULTIPLE * atr,
        target_1=entry_price + sign * TARGET_1_ATR_MULTIPLE * atr,
        target_2=entry_price + sign * TARGET_2_ATR_MULTIPLE * atr,
        strength=max(0.0, min(1.0, strength)),
    )


class Strategy(ABC):
    """A strategy reads candles plus indicators and either speaks or stays silent."""

    name: StrategyName

    @abstractmethod
    def generate_signal(
        self,
        df: pd.DataFrame,
        snapshot: IndicatorSnapshot,
    ) -> Signal | None:
        """Return a Signal when this strategy has an opinion, else None."""
```

- [ ] **Step 4: Implement the five strategies**

Create `tradingbot/strategy/strategies/breakout.py`:

```python
"""Price clearing a clustered resistance or support level on expanding volume."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal

VOLUME_LOOKBACK = 20
VOLUME_SURGE_MULTIPLE = 1.5
RSI_LONG_FLOOR = 50.0
RSI_SHORT_CEILING = 50.0


class BreakoutStrategy(Strategy):
    name = StrategyName.BREAKOUT

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        if len(df) < VOLUME_LOOKBACK + 1:
            return None

        recent_volume = float(df["volume"].iloc[-1])
        average_volume = float(df["volume"].iloc[-VOLUME_LOOKBACK - 1 : -1].mean())
        if average_volume <= 0:
            return None
        volume_ratio = recent_volume / average_volume

        price = snapshot.last_close

        nearest_resistance = min(
            (level for level in snapshot.resistance_levels if level < price),
            default=None,
            key=lambda level: price - level,
        )
        if (
            nearest_resistance is not None
            and volume_ratio >= VOLUME_SURGE_MULTIPLE
            and snapshot.rsi_14 >= RSI_LONG_FLOOR
        ):
            return build_signal(
                Direction.LONG,
                entry_price=price,
                atr=snapshot.atr_14,
                strength=min(1.0, volume_ratio / (VOLUME_SURGE_MULTIPLE * 2)),
            )

        nearest_support = min(
            (level for level in snapshot.support_levels if level > price),
            default=None,
            key=lambda level: level - price,
        )
        if (
            nearest_support is not None
            and volume_ratio >= VOLUME_SURGE_MULTIPLE
            and snapshot.rsi_14 <= RSI_SHORT_CEILING
        ):
            return build_signal(
                Direction.SHORT,
                entry_price=price,
                atr=snapshot.atr_14,
                strength=min(1.0, volume_ratio / (VOLUME_SURGE_MULTIPLE * 2)),
            )

        return None
```

Create `tradingbot/strategy/strategies/momentum.py`:

```python
"""Trend continuation: moving averages stacked and MACD confirming, not yet extended."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal

RSI_OVERBOUGHT = 75.0
RSI_OVERSOLD = 25.0
RSI_LONG_FLOOR = 55.0
RSI_SHORT_CEILING = 45.0


class MomentumStrategy(Strategy):
    name = StrategyName.MOMENTUM

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        price = snapshot.last_close
        macd_above_signal = snapshot.macd > snapshot.macd_signal

        uptrend = price > snapshot.sma_20 > snapshot.sma_50
        if uptrend and macd_above_signal and RSI_LONG_FLOOR <= snapshot.rsi_14 < RSI_OVERBOUGHT:
            return build_signal(
                Direction.LONG,
                entry_price=price,
                atr=snapshot.atr_14,
                strength=min(1.0, (snapshot.rsi_14 - RSI_LONG_FLOOR) / (RSI_OVERBOUGHT - RSI_LONG_FLOOR)),
            )

        downtrend = price < snapshot.sma_20 < snapshot.sma_50
        if downtrend and not macd_above_signal and RSI_OVERSOLD < snapshot.rsi_14 <= RSI_SHORT_CEILING:
            return build_signal(
                Direction.SHORT,
                entry_price=price,
                atr=snapshot.atr_14,
                strength=min(1.0, (RSI_SHORT_CEILING - snapshot.rsi_14) / (RSI_SHORT_CEILING - RSI_OVERSOLD)),
            )

        return None
```

Create `tradingbot/strategy/strategies/mean_reversion.py`:

```python
"""Fade an extreme: price outside a Bollinger band with RSI confirming exhaustion."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal

RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0


class MeanReversionStrategy(Strategy):
    name = StrategyName.MEAN_REVERSION

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        price = snapshot.last_close

        if price <= snapshot.bb_lower and snapshot.rsi_14 <= RSI_OVERSOLD:
            return build_signal(
                Direction.LONG,
                entry_price=price,
                atr=snapshot.atr_14,
                strength=min(1.0, (RSI_OVERSOLD - snapshot.rsi_14) / RSI_OVERSOLD + 0.5),
            )

        if price >= snapshot.bb_upper and snapshot.rsi_14 >= RSI_OVERBOUGHT:
            return build_signal(
                Direction.SHORT,
                entry_price=price,
                atr=snapshot.atr_14,
                strength=min(1.0, (snapshot.rsi_14 - RSI_OVERBOUGHT) / (100.0 - RSI_OVERBOUGHT) + 0.5),
            )

        return None
```

Create `tradingbot/strategy/strategies/vwap_bounce.py`:

```python
"""Trade the first pullback into VWAP in the direction of the prevailing trend."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal

MAX_VWAP_DISTANCE_PCT = 0.5


class VWAPBounceStrategy(Strategy):
    name = StrategyName.VWAP_BOUNCE

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        if snapshot.vwap <= 0:
            return None

        price = snapshot.last_close
        distance_pct = abs(price - snapshot.vwap) / snapshot.vwap * 100.0
        if distance_pct > MAX_VWAP_DISTANCE_PCT:
            return None

        strength = 1.0 - (distance_pct / MAX_VWAP_DISTANCE_PCT)

        if snapshot.sma_20 > snapshot.sma_50 and price >= snapshot.vwap:
            return build_signal(
                Direction.LONG, entry_price=price, atr=snapshot.atr_14, strength=strength
            )

        if snapshot.sma_20 < snapshot.sma_50 and price <= snapshot.vwap:
            return build_signal(
                Direction.SHORT, entry_price=price, atr=snapshot.atr_14, strength=strength
            )

        return None
```

Create `tradingbot/strategy/strategies/orb.py`:

```python
"""Opening range breakout: the first hour sets the range, a close outside it trades."""

from __future__ import annotations

import pandas as pd

from tradingbot.core.models import Direction, IndicatorSnapshot, StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy, build_signal

OPENING_RANGE_CANDLES = 4  # four 15-minute candles = the first hour


class ORBStrategy(Strategy):
    name = StrategyName.ORB

    def generate_signal(self, df: pd.DataFrame, snapshot: IndicatorSnapshot) -> Signal | None:
        if len(df) <= OPENING_RANGE_CANDLES:
            return None

        opening = df.iloc[:OPENING_RANGE_CANDLES]
        range_high = float(opening["high"].max())
        range_low = float(opening["low"].min())
        range_width = range_high - range_low
        if range_width <= 0:
            return None

        price = snapshot.last_close

        if price > range_high:
            return build_signal(
                Direction.LONG,
                entry_price=price,
                atr=snapshot.atr_14,
                strength=min(1.0, (price - range_high) / range_width),
            )

        if price < range_low:
            return build_signal(
                Direction.SHORT,
                entry_price=price,
                atr=snapshot.atr_14,
                strength=min(1.0, (range_low - price) / range_width),
            )

        return None
```

Create `tradingbot/strategy/strategies/__init__.py`:

```python
"""Strategy registry. Adding a strategy means adding one file and one entry here."""

from __future__ import annotations

from tradingbot.core.models import StrategyName
from tradingbot.strategy.strategies.base import Signal, Strategy
from tradingbot.strategy.strategies.breakout import BreakoutStrategy
from tradingbot.strategy.strategies.mean_reversion import MeanReversionStrategy
from tradingbot.strategy.strategies.momentum import MomentumStrategy
from tradingbot.strategy.strategies.orb import ORBStrategy
from tradingbot.strategy.strategies.vwap_bounce import VWAPBounceStrategy

STRATEGY_REGISTRY: dict[StrategyName, Strategy] = {
    StrategyName.BREAKOUT: BreakoutStrategy(),
    StrategyName.MOMENTUM: MomentumStrategy(),
    StrategyName.MEAN_REVERSION: MeanReversionStrategy(),
    StrategyName.VWAP_BOUNCE: VWAPBounceStrategy(),
    StrategyName.ORB: ORBStrategy(),
}


def all_strategies() -> list[Strategy]:
    """Every registered strategy, in registry order."""
    return list(STRATEGY_REGISTRY.values())


__all__ = [
    "STRATEGY_REGISTRY",
    "BreakoutStrategy",
    "MeanReversionStrategy",
    "MomentumStrategy",
    "ORBStrategy",
    "Signal",
    "Strategy",
    "VWAPBounceStrategy",
    "all_strategies",
]
```

- [ ] **Step 5: Run the strategy tests to verify they pass**

Run: `pytest tests/strategy/test_strategies.py -v`
Expected: PASS — 26 tests (the two parametrized cases expand to five each).

- [ ] **Step 6: Commit**

```bash
git add tradingbot/strategy/strategies/ tests/strategy/test_strategies.py
git commit -m "feat: add pluggable strategy library with shared ATR risk geometry"
```

---

## Task 9: Backtester, Strategy Selector, Plan Generator

**Files:**
- Create: `tradingbot/strategy/backtester.py`
- Create: `tradingbot/strategy/strategy_selector.py`
- Create: `tradingbot/strategy/plan_generator.py`
- Test: `tests/strategy/test_backtester.py`, `tests/strategy/test_strategy_selector.py`, `tests/strategy/test_plan_generator.py`

**Interfaces:**
- Consumes: `BacktestResult`, `IndicatorSnapshot`, `TradeSetup`, `TradePlan`, `MarketContext`, `ShortlistedStock`, `StrategyName`, `Direction`, `EntryType` (Task 1); `RiskManager` (Task 7); `Strategy`, `Signal`, `all_strategies` (Task 8); `compute_snapshot` (Task 4); `LLMProvider` (Task 3); `PlanStore` (Task 2).
- Produces:
  - `Backtester(strategies: list[Strategy] | None = None)` with `run(symbol, df, strategy) -> BacktestResult` and `run_all(symbol, df) -> list[BacktestResult]`.
  - `StrategySelector(provider, strategy_config)` with `async design_setups(shortlist, snapshots, backtests, context) -> list[TradeSetup]` and `SETUP_SCHEMA`.
  - `PlanGenerator(scanner, fetcher, selector, risk_manager, plan_store, strategy_config, capital, backtester=None, max_entry_wait=time(11, 0), exit_before=time(15, 10))` with `async generate(trade_date: date) -> TradePlan`.

- [ ] **Step 1: Write the failing test for the backtester**

Create `tests/strategy/test_backtester.py`:

```python
import numpy as np
import pandas as pd
import pytest

from tradingbot.core.models import Direction, StrategyName
from tradingbot.strategy.backtester import Backtester
from tradingbot.strategy.strategies.base import Signal, Strategy


def make_candles(closes, spread=1.0):
    index = pd.date_range("2026-08-01 09:15", periods=len(closes), freq="15min", tz="Asia/Kolkata")
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes + spread,
            "low": closes - spread,
            "close": closes,
            "volume": np.full(len(closes), 10000.0),
        },
        index=index,
    )


class AlwaysLongStrategy(Strategy):
    """Fires on every bar with a fixed 10 point stop and 20 point first target."""

    name = StrategyName.BREAKOUT

    def generate_signal(self, df, snapshot):
        price = float(df["close"].iloc[-1])
        return Signal(
            direction=Direction.LONG,
            entry_price=price,
            stop_loss=price - 10.0,
            target_1=price + 20.0,
            target_2=price + 30.0,
            strength=0.8,
        )


class NeverFiresStrategy(Strategy):
    name = StrategyName.ORB

    def generate_signal(self, df, snapshot):
        return None


def test_a_relentless_uptrend_produces_a_perfect_win_rate():
    df = make_candles(np.arange(100, 500, dtype=float))

    result = Backtester().run("RELIANCE", df, AlwaysLongStrategy())

    assert result.trades > 0
    assert result.wins == result.trades
    assert result.win_rate == pytest.approx(1.0)


def test_a_relentless_downtrend_produces_a_zero_win_rate():
    df = make_candles(np.arange(500, 100, -1, dtype=float))

    result = Backtester().run("RELIANCE", df, AlwaysLongStrategy())

    assert result.trades > 0
    assert result.wins == 0
    assert result.win_rate == pytest.approx(0.0)


def test_a_strategy_that_never_fires_reports_zero_trades():
    df = make_candles(np.arange(100, 300, dtype=float))

    result = Backtester().run("RELIANCE", df, NeverFiresStrategy())

    assert result.trades == 0
    assert result.wins == 0
    assert result.win_rate == pytest.approx(0.0)
    assert result.avg_reward_risk == pytest.approx(0.0)


def test_the_result_carries_the_symbol_and_strategy_name():
    df = make_candles(np.arange(100, 400, dtype=float))

    result = Backtester().run("TCS", df, AlwaysLongStrategy())

    assert result.symbol == "TCS"
    assert result.strategy is StrategyName.BREAKOUT


def test_avg_reward_risk_reflects_the_configured_geometry():
    df = make_candles(np.arange(100, 500, dtype=float))

    result = Backtester().run("RELIANCE", df, AlwaysLongStrategy())

    # 20 points of reward against 10 points of risk.
    assert result.avg_reward_risk == pytest.approx(2.0)


def test_too_few_candles_yields_an_empty_result_rather_than_raising():
    df = make_candles([100.0, 101.0])

    result = Backtester().run("RELIANCE", df, AlwaysLongStrategy())

    assert result.trades == 0


def test_run_all_returns_one_result_per_registered_strategy():
    df = make_candles(np.arange(100, 400, dtype=float))

    results = Backtester().run_all("RELIANCE", df)

    assert len(results) == len(set(StrategyName))
    assert {result.strategy for result in results} == set(StrategyName)


def test_backtesting_never_mutates_the_candle_frame():
    df = make_candles(np.arange(100, 400, dtype=float))
    before = df.copy(deep=True)

    Backtester().run("RELIANCE", df, AlwaysLongStrategy())

    pd.testing.assert_frame_equal(df, before)
```

- [ ] **Step 2: Run the backtester tests to verify they fail**

Run: `pytest tests/strategy/test_backtester.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.strategy.backtester'`

- [ ] **Step 3: Implement the backtester**

Create `tradingbot/strategy/backtester.py`:

```python
"""Walk-forward backtest: replay candles, let the strategy speak, score the outcome.

This exists to give the LLM evidence about which strategy has been working on a
given symbol recently. It is deliberately simple: one position at a time, exit on
whichever of stop or target 1 is touched first, no pyramiding and no costs model.
"""

from __future__ import annotations

import logging

import pandas as pd

from tradingbot.core.models import BacktestResult, Direction, StrategyName
from tradingbot.strategy.indicators import InsufficientDataError, compute_snapshot
from tradingbot.strategy.strategies import Strategy, all_strategies

logger = logging.getLogger(__name__)

WARMUP_CANDLES = 50
MAX_HOLD_CANDLES = 26  # roughly one session of 15 minute bars


class Backtester:
    """Replays history one candle at a time and records simulated outcomes."""

    def __init__(self, strategies: list[Strategy] | None = None) -> None:
        self.strategies = strategies if strategies is not None else all_strategies()

    def run(self, symbol: str, df: pd.DataFrame, strategy: Strategy) -> BacktestResult:
        """Score one strategy on one symbol over the supplied candles."""
        if len(df) <= WARMUP_CANDLES:
            return BacktestResult(
                symbol=symbol,
                strategy=strategy.name,
                trades=0,
                wins=0,
                win_rate=0.0,
                avg_reward_risk=0.0,
            )

        trades = 0
        wins = 0
        reward_risks: list[float] = []
        index = WARMUP_CANDLES

        while index < len(df):
            window = df.iloc[:index]
            try:
                snapshot = compute_snapshot(symbol, window)
            except InsufficientDataError:
                snapshot = self._lenient_snapshot(symbol, window)

            signal = strategy.generate_signal(window, snapshot)
            if signal is None:
                index += 1
                continue

            outcome, exit_index = self._resolve(df, index, signal)
            if outcome is None:
                break

            trades += 1
            wins += 1 if outcome else 0
            risk = abs(signal.entry_price - signal.stop_loss)
            if risk > 0:
                reward_risks.append(abs(signal.target_1 - signal.entry_price) / risk)

            index = exit_index + 1

        return BacktestResult(
            symbol=symbol,
            strategy=strategy.name,
            trades=trades,
            wins=wins,
            win_rate=wins / trades if trades else 0.0,
            avg_reward_risk=sum(reward_risks) / len(reward_risks) if reward_risks else 0.0,
        )

    def run_all(self, symbol: str, df: pd.DataFrame) -> list[BacktestResult]:
        """Score every registered strategy on one symbol."""
        return [self.run(symbol, df, strategy) for strategy in self.strategies]

    @staticmethod
    def _resolve(df: pd.DataFrame, entry_index: int, signal) -> tuple[bool | None, int]:
        """Walk forward until stop or target 1 is touched. True means the target won."""
        end = min(entry_index + MAX_HOLD_CANDLES, len(df))

        for position in range(entry_index, end):
            candle = df.iloc[position]
            high, low = float(candle["high"]), float(candle["low"])

            if signal.direction is Direction.LONG:
                if low <= signal.stop_loss:
                    return False, position
                if high >= signal.target_1:
                    return True, position
            else:
                if high >= signal.stop_loss:
                    return False, position
                if low <= signal.target_1:
                    return True, position

        if end <= entry_index:
            return None, entry_index

        # Ran out of holding time: score on where the close finished.
        final_close = float(df.iloc[end - 1]["close"])
        if signal.direction is Direction.LONG:
            return final_close > signal.entry_price, end - 1
        return final_close < signal.entry_price, end - 1

    @staticmethod
    def _lenient_snapshot(symbol: str, window: pd.DataFrame):
        """A reduced snapshot for early windows, so warmup does not abort the run."""
        from tradingbot.core.models import IndicatorSnapshot
        from tradingbot.strategy.indicators import (
            atr,
            bollinger_bands,
            ema,
            macd,
            pivot_points,
            rsi,
            sma,
            vwap,
        )

        close = window["close"]
        macd_line, signal_line = macd(close)
        upper, middle, lower = bollinger_bands(close)

        def last(series: pd.Series, fallback: float) -> float:
            value = series.iloc[-1]
            return float(value) if pd.notna(value) else fallback

        last_close = float(close.iloc[-1])
        return IndicatorSnapshot(
            symbol=symbol,
            last_close=last_close,
            rsi_14=last(rsi(close), 50.0),
            macd=last(macd_line, 0.0),
            macd_signal=last(signal_line, 0.0),
            bb_upper=last(upper, last_close),
            bb_middle=last(middle, last_close),
            bb_lower=last(lower, last_close),
            atr_14=last(atr(window), 1.0),
            sma_20=last(sma(close, 20), last_close),
            sma_50=last(sma(close, 50), last_close),
            sma_200=last(sma(close, 200), last_close),
            ema_12=last(ema(close, 12), last_close),
            ema_26=last(ema(close, 26), last_close),
            vwap=last(vwap(window), last_close),
            pivot=float(pivot_points(window)["pivot"]),
            support_levels=[],
            resistance_levels=[],
        )
```

- [ ] **Step 4: Run the backtester tests to verify they pass**

Run: `pytest tests/strategy/test_backtester.py -v`
Expected: PASS — 8 tests.

- [ ] **Step 5: Write the failing test for the strategy selector (covers Review Focus item 2)**

Create `tests/strategy/test_strategy_selector.py`:

```python
from datetime import time

import pytest

from tradingbot.core.config import StrategyConfig
from tradingbot.core.llm.provider import LLMProvider
from tradingbot.core.models import (
    BacktestResult,
    Direction,
    EntryType,
    IndicatorSnapshot,
    MarketContext,
    MarketRegime,
    ShortlistedStock,
    StrategyName,
)
from tradingbot.strategy.strategy_selector import StrategySelector


class StubProvider(LLMProvider):
    def __init__(self, payload):
        self.payload = payload
        self.last_user_prompt = None
        self.call_count = 0

    async def analyze(self, system_prompt, user_prompt, tool_name, tool_description, input_schema):
        self.call_count += 1
        self.last_user_prompt = user_prompt
        return self.payload

    async def health_check(self):
        return True


def make_config() -> StrategyConfig:
    return StrategyConfig(
        backtest_days=30,
        candle_interval="15minute",
        min_confidence=0.5,
        min_reward_risk=1.5,
        max_trades_per_day=2,
    )


def make_context() -> MarketContext:
    return MarketContext(
        nifty_level=25400.0,
        nifty_trend="bullish",
        banknifty_trend="bullish",
        india_vix=12.5,
        fii_net_cr=2300.0,
        dii_net_cr=-800.0,
        global_cues="US flat",
        sector_leaders=["IT"],
        sector_laggards=["FMCG"],
        regime=MarketRegime.TRENDING,
    )


def make_shortlist(*symbols):
    return [
        ShortlistedStock(
            symbol=symbol,
            reasoning="Candidate.",
            suggested_strategy=StrategyName.BREAKOUT,
            direction_bias="long",
            key_levels=[100.0],
        )
        for symbol in symbols
    ]


def make_snapshot(symbol) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        symbol=symbol,
        last_close=100.0,
        rsi_14=58.0,
        macd=0.5,
        macd_signal=0.2,
        bb_upper=108.0,
        bb_middle=100.0,
        bb_lower=92.0,
        atr_14=2.0,
        sma_20=98.0,
        sma_50=95.0,
        sma_200=90.0,
        ema_12=99.0,
        ema_26=97.0,
        vwap=99.0,
        pivot=100.0,
        support_levels=[95.0],
        resistance_levels=[105.0],
    )


def make_backtests(symbol):
    return [
        BacktestResult(
            symbol=symbol,
            strategy=StrategyName.BREAKOUT,
            trades=20,
            wins=12,
            win_rate=0.6,
            avg_reward_risk=2.0,
        )
    ]


def setup_payload(symbol, **overrides):
    item = {
        "symbol": symbol,
        "strategy": "breakout",
        "direction": "long",
        "entry_price": 100.0,
        "entry_type": "limit",
        "stop_loss": 98.0,
        "target_1": 104.0,
        "target_2": 106.0,
        "entry_window_start": "09:30",
        "entry_window_end": "10:30",
        "confidence": 0.72,
        "reasoning": "Clean breakout setup.",
    }
    item.update(overrides)
    return item


async def test_design_setups_maps_the_payload_to_trade_setups():
    provider = StubProvider({"setups": [setup_payload("RELIANCE")]})
    selector = StrategySelector(provider, make_config())

    setups = await selector.design_setups(
        make_shortlist("RELIANCE"),
        {"RELIANCE": make_snapshot("RELIANCE")},
        {"RELIANCE": make_backtests("RELIANCE")},
        make_context(),
    )

    assert len(setups) == 1
    setup = setups[0]
    assert setup.symbol == "RELIANCE"
    assert setup.strategy is StrategyName.BREAKOUT
    assert setup.direction is Direction.LONG
    assert setup.entry_type is EntryType.LIMIT
    assert setup.entry_window_start == time(9, 30)
    assert setup.confidence == pytest.approx(0.72)


async def test_all_shortlisted_stocks_go_out_in_a_single_llm_call():
    provider = StubProvider({"setups": []})
    selector = StrategySelector(provider, make_config())

    await selector.design_setups(
        make_shortlist("RELIANCE", "TCS", "INFY"),
        {symbol: make_snapshot(symbol) for symbol in ("RELIANCE", "TCS", "INFY")},
        {symbol: make_backtests(symbol) for symbol in ("RELIANCE", "TCS", "INFY")},
        make_context(),
    )

    assert provider.call_count == 1
    assert "RELIANCE" in provider.last_user_prompt
    assert "TCS" in provider.last_user_prompt
    assert "INFY" in provider.last_user_prompt


async def test_a_setup_for_a_symbol_outside_the_shortlist_is_dropped():
    provider = StubProvider(
        {"setups": [setup_payload("RELIANCE"), setup_payload("HALLUCINATED")]}
    )
    selector = StrategySelector(provider, make_config())

    setups = await selector.design_setups(
        make_shortlist("RELIANCE"),
        {"RELIANCE": make_snapshot("RELIANCE")},
        {"RELIANCE": make_backtests("RELIANCE")},
        make_context(),
    )

    assert [setup.symbol for setup in setups] == ["RELIANCE"]


async def test_a_setup_with_an_unknown_strategy_is_dropped():
    provider = StubProvider({"setups": [setup_payload("RELIANCE", strategy="astrology")]})
    selector = StrategySelector(provider, make_config())

    setups = await selector.design_setups(
        make_shortlist("RELIANCE"),
        {"RELIANCE": make_snapshot("RELIANCE")},
        {"RELIANCE": make_backtests("RELIANCE")},
        make_context(),
    )

    assert setups == []


async def test_a_setup_with_a_malformed_time_window_is_dropped():
    provider = StubProvider({"setups": [setup_payload("RELIANCE", entry_window_start="morning")]})
    selector = StrategySelector(provider, make_config())

    setups = await selector.design_setups(
        make_shortlist("RELIANCE"),
        {"RELIANCE": make_snapshot("RELIANCE")},
        {"RELIANCE": make_backtests("RELIANCE")},
        make_context(),
    )

    assert setups == []


async def test_a_setup_with_a_non_numeric_price_is_dropped():
    provider = StubProvider({"setups": [setup_payload("RELIANCE", entry_price="about a hundred")]})
    selector = StrategySelector(provider, make_config())

    setups = await selector.design_setups(
        make_shortlist("RELIANCE"),
        {"RELIANCE": make_snapshot("RELIANCE")},
        {"RELIANCE": make_backtests("RELIANCE")},
        make_context(),
    )

    assert setups == []


async def test_the_prompt_carries_indicator_values_and_backtest_evidence():
    provider = StubProvider({"setups": []})
    selector = StrategySelector(provider, make_config())

    await selector.design_setups(
        make_shortlist("RELIANCE"),
        {"RELIANCE": make_snapshot("RELIANCE")},
        {"RELIANCE": make_backtests("RELIANCE")},
        make_context(),
    )

    prompt = provider.last_user_prompt
    assert "RSI" in prompt
    assert "58" in prompt
    assert "breakout" in prompt
    assert "60" in prompt  # the 60% backtest win rate


async def test_an_empty_shortlist_skips_the_llm_call():
    provider = StubProvider({"setups": [setup_payload("GHOST")]})
    selector = StrategySelector(provider, make_config())

    setups = await selector.design_setups([], {}, {}, make_context())

    assert setups == []
    assert provider.call_count == 0
```

- [ ] **Step 6: Run the selector tests to verify they fail**

Run: `pytest tests/strategy/test_strategy_selector.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.strategy.strategy_selector'`

- [ ] **Step 7: Implement the strategy selector**

Create `tradingbot/strategy/strategy_selector.py`:

```python
"""LLM call 2: turn shortlisted stocks plus evidence into concrete trade setups.

One batched call covers every shortlisted symbol, which keeps a full analysis run
at two LLM calls total.
"""

from __future__ import annotations

import logging
from datetime import time

from tradingbot.core.config import StrategyConfig
from tradingbot.core.llm.provider import LLMProvider
from tradingbot.core.models import (
    BacktestResult,
    Direction,
    EntryType,
    IndicatorSnapshot,
    MarketContext,
    ShortlistedStock,
    StrategyName,
    TradeSetup,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an expert intraday trading strategist working the Indian equity market. "
    "You design precise trade setups with exact entry, stop loss, and target levels, "
    "based only on the technical readings, backtest evidence, and market regime you "
    "are given. Do NOT guess or fabricate numbers, and do NOT reference data you were "
    "not shown. Every level you return must be justifiable from the supplied support, "
    "resistance, ATR, and price values. If a symbol has no good setup, omit it; "
    "returning fewer setups is always better than returning a weak one."
)

SETUP_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "setups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "strategy": {
                        "type": "string",
                        "enum": ["breakout", "momentum", "mean_reversion", "vwap_bounce", "orb"],
                    },
                    "direction": {"type": "string", "enum": ["long", "short"]},
                    "entry_price": {"type": "number"},
                    "entry_type": {"type": "string", "enum": ["limit", "stop"]},
                    "stop_loss": {"type": "number"},
                    "target_1": {"type": "number"},
                    "target_2": {"type": "number"},
                    "entry_window_start": {"type": "string"},
                    "entry_window_end": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reasoning": {"type": "string"},
                },
                "required": [
                    "symbol",
                    "strategy",
                    "direction",
                    "entry_price",
                    "entry_type",
                    "stop_loss",
                    "target_1",
                    "target_2",
                    "entry_window_start",
                    "entry_window_end",
                    "confidence",
                    "reasoning",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["setups"],
    "additionalProperties": False,
}


class StrategySelector:
    """Asks Claude to design setups, then validates every field it returns."""

    def __init__(self, provider: LLMProvider, strategy_config: StrategyConfig) -> None:
        self.provider = provider
        self.config = strategy_config

    async def design_setups(
        self,
        shortlist: list[ShortlistedStock],
        snapshots: dict[str, IndicatorSnapshot],
        backtests: dict[str, list[BacktestResult]],
        context: MarketContext,
    ) -> list[TradeSetup]:
        if not shortlist:
            logger.warning("shortlist is empty; skipping the setup design call")
            return []

        payload = await self.provider.analyze(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=self._build_prompt(shortlist, snapshots, backtests, context),
            tool_name="submit_setups",
            tool_description="Return one intraday trade setup per stock you want to trade.",
            input_schema=SETUP_SCHEMA,
        )

        allowed = {stock.symbol for stock in shortlist}
        setups: list[TradeSetup] = []

        for raw in payload.get("setups", []):
            setup = self._parse_setup(raw, allowed)
            if setup is not None:
                setups.append(setup)

        return setups

    @staticmethod
    def _parse_setup(raw: dict, allowed: set[str]) -> TradeSetup | None:
        symbol = str(raw.get("symbol", "")).upper()
        if symbol not in allowed:
            logger.warning("dropping setup for %s: not in the shortlist", symbol or "<blank>")
            return None

        try:
            return TradeSetup(
                symbol=symbol,
                strategy=StrategyName(raw["strategy"]),
                direction=Direction(raw["direction"]),
                entry_price=float(raw["entry_price"]),
                entry_type=EntryType(raw["entry_type"]),
                stop_loss=float(raw["stop_loss"]),
                target_1=float(raw["target_1"]),
                target_2=float(raw["target_2"]),
                entry_window_start=_parse_clock(raw["entry_window_start"]),
                entry_window_end=_parse_clock(raw["entry_window_end"]),
                confidence=float(raw["confidence"]),
                reasoning=str(raw["reasoning"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("dropping setup for %s: malformed field (%s)", symbol, exc)
            return None

    def _build_prompt(
        self,
        shortlist: list[ShortlistedStock],
        snapshots: dict[str, IndicatorSnapshot],
        backtests: dict[str, list[BacktestResult]],
        context: MarketContext,
    ) -> str:
        blocks: list[str] = [
            "MARKET REGIME\n"
            f"Regime: {context.regime.value}\n"
            f"Nifty: {context.nifty_level:.0f} ({context.nifty_trend})\n"
            f"India VIX: {context.india_vix:.2f}\n"
        ]

        for stock in shortlist:
            snapshot = snapshots.get(stock.symbol)
            if snapshot is None:
                continue

            results = backtests.get(stock.symbol, [])
            backtest_lines = (
                "\n".join(
                    f"  - {result.strategy.value}: {result.win_rate * 100:.0f}% win rate "
                    f"over {result.trades} trades, avg R:R {result.avg_reward_risk:.2f}"
                    for result in results
                )
                or "  - no backtest data"
            )

            blocks.append(
                f"=== {stock.symbol} ===\n"
                f"Scanner note: {stock.reasoning}\n"
                f"Scanner bias: {stock.direction_bias}, suggested {stock.suggested_strategy.value}\n"
                f"Last close: {snapshot.last_close:.2f}\n"
                f"RSI(14): {snapshot.rsi_14:.1f} | MACD: {snapshot.macd:.3f} "
                f"vs signal {snapshot.macd_signal:.3f}\n"
                f"ATR(14): {snapshot.atr_14:.2f} | VWAP: {snapshot.vwap:.2f} | "
                f"Pivot: {snapshot.pivot:.2f}\n"
                f"Bollinger: {snapshot.bb_lower:.2f} / {snapshot.bb_middle:.2f} / {snapshot.bb_upper:.2f}\n"
                f"SMA 20/50/200: {snapshot.sma_20:.2f} / {snapshot.sma_50:.2f} / {snapshot.sma_200:.2f}\n"
                f"Support: {', '.join(f'{level:.2f}' for level in snapshot.support_levels) or 'none'}\n"
                f"Resistance: {', '.join(f'{level:.2f}' for level in snapshot.resistance_levels) or 'none'}\n"
                f"Backtest (last {self.config.backtest_days} days):\n{backtest_lines}"
            )

        blocks.append(
            "TASK\n"
            "For each stock where you see a genuinely good intraday setup, return a trade "
            f"setup. Require at least {self.config.min_reward_risk:.1f}:1 reward to risk "
            f"measured to target 1, and at least {self.config.min_confidence:.2f} confidence. "
            "Entry windows must fall between 09:30 and 14:00 and use HH:MM. Place stops "
            "beyond a real technical level, not at a round number."
        )

        return "\n\n".join(blocks)


def _parse_clock(raw: str) -> time:
    hour, minute = str(raw).split(":")
    return time(int(hour), int(minute))
```

- [ ] **Step 8: Write the failing test for the plan generator**

Create `tests/strategy/test_plan_generator.py`:

```python
from datetime import date, datetime, time

import numpy as np
import pandas as pd
import pytest

from tradingbot.core.config import RiskConfig, StrategyConfig
from tradingbot.core.models import (
    IST,
    Direction,
    EntryType,
    MarketContext,
    MarketRegime,
    ShortlistedStock,
    StrategyName,
    TradeSetup,
)
from tradingbot.core.plan_store import PlanStore
from tradingbot.core.risk_manager import RiskManager
from tradingbot.scanner.scanner import ScanResult
from tradingbot.scanner.filters import FilterResult
from tradingbot.strategy.plan_generator import PlanGenerator


def make_candles(rows=300):
    closes = 100 + np.cumsum(np.random.default_rng(11).normal(0, 1, rows))
    index = pd.date_range("2026-08-01 09:15", periods=rows, freq="15min", tz="Asia/Kolkata")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes + 1.0,
            "low": closes - 1.0,
            "close": closes,
            "volume": np.full(rows, 10000.0),
        },
        index=index,
    )


class StubScanner:
    def __init__(self, shortlist):
        self.shortlist = shortlist

    async def scan(self, trade_date):
        return ScanResult(
            trade_date=trade_date,
            context=MarketContext(
                nifty_level=25400.0,
                nifty_trend="bullish",
                banknifty_trend="bullish",
                india_vix=12.5,
                fii_net_cr=2300.0,
                dii_net_cr=-800.0,
                global_cues="US flat",
                sector_leaders=["IT"],
                sector_laggards=["FMCG"],
                regime=MarketRegime.TRENDING,
            ),
            shortlist=self.shortlist,
            filter_result=FilterResult(passed=[], rejected={}),
        )


class StubFetcher:
    def __init__(self, failing: set[str] | None = None):
        self.failing = failing or set()

    def fetch_candles(self, symbol, days, interval):
        if symbol in self.failing:
            raise RuntimeError(f"no data for {symbol}")
        return make_candles()


class StubSelector:
    def __init__(self, setups):
        self.setups = setups
        self.seen_symbols = None

    async def design_setups(self, shortlist, snapshots, backtests, context):
        self.seen_symbols = [stock.symbol for stock in shortlist]
        return self.setups


def make_shortlist(*symbols):
    return [
        ShortlistedStock(
            symbol=symbol,
            reasoning="Candidate.",
            suggested_strategy=StrategyName.BREAKOUT,
            direction_bias="long",
            key_levels=[100.0],
        )
        for symbol in symbols
    ]


def make_setup(symbol, confidence=0.8) -> TradeSetup:
    return TradeSetup(
        symbol=symbol,
        strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG,
        entry_price=100.0,
        entry_type=EntryType.LIMIT,
        stop_loss=98.0,
        target_1=104.0,
        target_2=106.0,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        confidence=confidence,
        reasoning="Clean setup.",
    )


def make_generator(tmp_path, shortlist, setups, failing=None):
    strategy_config = StrategyConfig(
        backtest_days=30,
        candle_interval="15minute",
        min_confidence=0.5,
        min_reward_risk=1.5,
        max_trades_per_day=2,
    )
    risk_config = RiskConfig(
        max_risk_per_trade_pct=0.01,
        max_daily_loss_pct=0.02,
        max_capital_deployed_pct=0.50,
        max_concurrent_positions=2,
    )
    selector = StubSelector(setups)
    generator = PlanGenerator(
        scanner=StubScanner(shortlist),
        fetcher=StubFetcher(failing),
        selector=selector,
        risk_manager=RiskManager(risk_config, strategy_config, capital=400000.0),
        plan_store=PlanStore(tmp_path),
        strategy_config=strategy_config,
        capital=400000.0,
    )
    return generator, selector


async def test_generate_writes_a_plan_file(tmp_path):
    generator, _ = make_generator(tmp_path, make_shortlist("RELIANCE"), [make_setup("RELIANCE")])

    plan = await generator.generate(date(2026, 9, 24))

    assert plan.trade_date == "2026-09-24"
    assert (tmp_path / "2026-09-24.json").exists()


async def test_the_plan_carries_sized_legs(tmp_path):
    generator, _ = make_generator(tmp_path, make_shortlist("RELIANCE"), [make_setup("RELIANCE")])

    plan = await generator.generate(date(2026, 9, 24))

    assert len(plan.legs) == 1
    assert plan.legs[0].quantity > 0
    assert plan.legs[0].risk_amount > 0


async def test_the_plan_never_exceeds_max_trades_per_day(tmp_path):
    setups = [make_setup(symbol, confidence=0.9) for symbol in ("A", "B", "C", "D")]
    generator, _ = make_generator(tmp_path, make_shortlist("A", "B", "C", "D"), setups)

    plan = await generator.generate(date(2026, 9, 24))

    assert len(plan.legs) <= 2


async def test_setups_that_fail_risk_vetting_are_excluded(tmp_path):
    setups = [make_setup("GOOD", confidence=0.9), make_setup("WEAK", confidence=0.1)]
    generator, _ = make_generator(tmp_path, make_shortlist("GOOD", "WEAK"), setups)

    plan = await generator.generate(date(2026, 9, 24))

    assert [leg.symbol for leg in plan.legs] == ["GOOD"]


async def test_a_symbol_whose_candles_fail_to_load_is_skipped(tmp_path):
    generator, selector = make_generator(
        tmp_path,
        make_shortlist("RELIANCE", "BROKEN"),
        [make_setup("RELIANCE")],
        failing={"BROKEN"},
    )

    await generator.generate(date(2026, 9, 24))

    assert selector.seen_symbols == ["RELIANCE"]


async def test_an_empty_shortlist_produces_a_plan_with_no_legs(tmp_path):
    generator, _ = make_generator(tmp_path, [], [])

    plan = await generator.generate(date(2026, 9, 24))

    assert plan.legs == []
    assert (tmp_path / "2026-09-24.json").exists()


async def test_the_plan_records_the_market_regime_and_capital(tmp_path):
    generator, _ = make_generator(tmp_path, make_shortlist("RELIANCE"), [make_setup("RELIANCE")])

    plan = await generator.generate(date(2026, 9, 24))

    assert plan.market_regime is MarketRegime.TRENDING
    assert plan.capital == pytest.approx(400000.0)


async def test_the_written_plan_reloads_identically(tmp_path):
    generator, _ = make_generator(tmp_path, make_shortlist("RELIANCE"), [make_setup("RELIANCE")])

    plan = await generator.generate(date(2026, 9, 24))

    assert PlanStore(tmp_path).load("2026-09-24") == plan
```

- [ ] **Step 9: Run the plan generator tests to verify they fail**

Run: `pytest tests/strategy/test_plan_generator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.strategy.plan_generator'`

- [ ] **Step 10: Implement the plan generator**

Create `tradingbot/strategy/plan_generator.py`:

```python
"""Ties the analysis phase together and writes the TradePlan artifact."""

from __future__ import annotations

import logging
from datetime import date, time

from tradingbot.core.config import StrategyConfig
from tradingbot.core.models import (
    BacktestResult,
    IndicatorSnapshot,
    TradePlan,
    now_ist,
)
from tradingbot.core.plan_store import PlanStore
from tradingbot.core.risk_manager import RiskManager
from tradingbot.strategy.backtester import Backtester
from tradingbot.strategy.indicators import compute_snapshot

logger = logging.getLogger(__name__)

DEFAULT_MAX_ENTRY_WAIT = time(11, 0)
DEFAULT_EXIT_BEFORE = time(15, 10)

INTERVAL_TO_YFINANCE = {
    "5minute": "5m",
    "15minute": "15m",
    "30minute": "30m",
    "60minute": "60m",
}


class PlanGenerator:
    """Scan, analyse, size, and persist the plan for one trade date."""

    def __init__(
        self,
        scanner,
        fetcher,
        selector,
        risk_manager: RiskManager,
        plan_store: PlanStore,
        strategy_config: StrategyConfig,
        capital: float,
        backtester: Backtester | None = None,
        max_entry_wait: time = DEFAULT_MAX_ENTRY_WAIT,
        exit_before: time = DEFAULT_EXIT_BEFORE,
    ) -> None:
        self.scanner = scanner
        self.fetcher = fetcher
        self.selector = selector
        self.risk_manager = risk_manager
        self.plan_store = plan_store
        self.config = strategy_config
        self.capital = capital
        self.backtester = backtester or Backtester()
        self.max_entry_wait = max_entry_wait
        self.exit_before = exit_before

    async def generate(self, trade_date: date) -> TradePlan:
        scan = await self.scanner.scan(trade_date)

        snapshots: dict[str, IndicatorSnapshot] = {}
        backtests: dict[str, list[BacktestResult]] = {}
        usable = []

        interval = INTERVAL_TO_YFINANCE.get(self.config.candle_interval, "15m")

        for stock in scan.shortlist:
            try:
                candles = self.fetcher.fetch_candles(
                    stock.symbol, days=self.config.backtest_days, interval=interval
                )
                snapshots[stock.symbol] = compute_snapshot(stock.symbol, candles)
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the run
                logger.warning("skipping %s: %s", stock.symbol, exc)
                continue

            backtests[stock.symbol] = self.backtester.run_all(stock.symbol, candles)
            usable.append(stock)

        setups = await self.selector.design_setups(usable, snapshots, backtests, scan.context)
        logger.info("LLM returned %d setups for %d usable symbols", len(setups), len(usable))

        legs = self.risk_manager.select_legs(
            setups, max_entry_wait=self.max_entry_wait, exit_before=self.exit_before
        )
        logger.info("risk manager approved %d legs", len(legs))

        plan = TradePlan(
            trade_date=trade_date.isoformat(),
            generated_at=now_ist(),
            capital=self.capital,
            max_risk_per_trade_pct=self.risk_manager.risk.max_risk_per_trade_pct,
            max_daily_loss_pct=self.risk_manager.risk.max_daily_loss_pct,
            market_regime=scan.context.regime,
            market_summary=(
                f"Nifty {scan.context.nifty_level:.0f} ({scan.context.nifty_trend}), "
                f"VIX {scan.context.india_vix:.2f}, "
                f"FII {scan.context.fii_net_cr:+.0f} Cr, DII {scan.context.dii_net_cr:+.0f} Cr"
            ),
            legs=legs,
        )

        self.plan_store.save(plan)
        return plan
```

- [ ] **Step 11: Run the full test suite to verify it passes**

Run: `pytest tests/ -v`
Expected: PASS — 173 tests.

- [ ] **Step 12: Commit**

```bash
git add tradingbot/strategy/backtester.py tradingbot/strategy/strategy_selector.py tradingbot/strategy/plan_generator.py tests/strategy/
git commit -m "feat: add backtester, LLM strategy selector, and trade plan generator"
```

---

## Task 10: Broker Interface, Kite Client, Virtual Broker

**Files:**
- Create: `tradingbot/core/broker.py`
- Create: `tradingbot/core/kite_client.py`
- Create: `tradingbot/paper/__init__.py`
- Create: `tradingbot/paper/virtual_broker.py`
- Test: `tests/core/test_broker.py`, `tests/paper/test_virtual_broker.py`

**Interfaces:**
- Consumes: `Direction`, `Position`, `IST`, `now_ist` (Task 1); `PaperConfig`, `Secrets` (Task 1).
- Produces:
  - `OrderSide` (`BUY`/`SELL`), `OrderType` (`MARKET`/`LIMIT`/`SL`), `OrderStatus` (`OPEN`/`COMPLETE`/`CANCELLED`/`REJECTED`).
  - `Order` dataclass: `order_id`, `symbol`, `side`, `order_type`, `quantity`, `price`, `trigger_price`, `status`, `filled_price`, `placed_at`.
  - `BrokerInterface` ABC: `place_order`, `cancel_order`, `get_order(order_id)`, `get_positions`, `get_ltp(symbol)`, `available_margin`, `square_off(symbol)`.
  - `BrokerError`.
  - `KiteClient(api_key, api_secret, access_token, kite=None)` implementing `BrokerInterface`.
  - `VirtualBroker(config: PaperConfig, price_feed)` implementing `BrokerInterface`, plus `advance()` to process resting orders against the current price.

- [ ] **Step 1: Write the failing test for the broker contract**

Create `tests/core/test_broker.py`:

```python
import inspect

import pytest

from tradingbot.core.broker import (
    BrokerError,
    BrokerInterface,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)


def test_broker_interface_cannot_be_instantiated():
    with pytest.raises(TypeError):
        BrokerInterface()


def test_broker_interface_declares_every_required_method():
    required = {
        "place_order",
        "cancel_order",
        "get_order",
        "get_positions",
        "get_ltp",
        "available_margin",
        "square_off",
    }

    assert required <= set(BrokerInterface.__abstractmethods__)


def test_place_order_signature_is_stable():
    params = list(inspect.signature(BrokerInterface.place_order).parameters)

    assert params == ["self", "symbol", "side", "order_type", "quantity", "price", "trigger_price"]


def test_order_side_and_type_values_are_stable_strings():
    assert OrderSide.BUY.value == "BUY"
    assert OrderSide.SELL.value == "SELL"
    assert OrderType.MARKET.value == "MARKET"
    assert OrderType.LIMIT.value == "LIMIT"
    assert OrderType.SL.value == "SL"


def test_order_status_values_are_stable_strings():
    assert OrderStatus.OPEN.value == "OPEN"
    assert OrderStatus.COMPLETE.value == "COMPLETE"
    assert OrderStatus.CANCELLED.value == "CANCELLED"
    assert OrderStatus.REJECTED.value == "REJECTED"


def test_order_is_terminal_only_once_it_stops_resting():
    from tradingbot.core.models import now_ist

    def make(status):
        return Order(
            order_id="1",
            symbol="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            price=100.0,
            trigger_price=None,
            status=status,
            filled_price=None,
            placed_at=now_ist(),
        )

    assert make(OrderStatus.OPEN).is_terminal is False
    assert make(OrderStatus.COMPLETE).is_terminal is True
    assert make(OrderStatus.CANCELLED).is_terminal is True
    assert make(OrderStatus.REJECTED).is_terminal is True


def test_broker_error_is_an_exception():
    assert issubclass(BrokerError, Exception)


def test_a_concrete_broker_can_be_instantiated():
    class StubBroker(BrokerInterface):
        def place_order(self, symbol, side, order_type, quantity, price=None, trigger_price=None):
            return "order-1"

        def cancel_order(self, order_id):
            return None

        def get_order(self, order_id):
            return None

        def get_positions(self):
            return []

        def get_ltp(self, symbol):
            return 100.0

        def available_margin(self):
            return 400000.0

        def square_off(self, symbol):
            return None

    assert isinstance(StubBroker(), BrokerInterface)
```

- [ ] **Step 2: Run the broker tests to verify they fail**

Run: `pytest tests/core/test_broker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.core.broker'`

- [ ] **Step 3: Implement the broker interface**

Create `tradingbot/core/broker.py`:

```python
"""The single broker contract. Paper and live trading differ only in the implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from tradingbot.core.models import Position


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class BrokerError(Exception):
    """Raised when the broker rejects a request or cannot be reached."""


@dataclass
class Order:
    """One order as the broker sees it."""

    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: float | None
    trigger_price: float | None
    status: OrderStatus
    filled_price: float | None
    placed_at: datetime

    @property
    def is_terminal(self) -> bool:
        """True once the order can no longer fill."""
        return self.status is not OrderStatus.OPEN


class BrokerInterface(ABC):
    """Every method the executor is allowed to call on a broker."""

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: int,
        price: float | None = None,
        trigger_price: float | None = None,
    ) -> str:
        """Submit an order and return its broker order id."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> None:
        """Cancel a resting order. Cancelling a filled order is a no-op."""

    @abstractmethod
    def get_order(self, order_id: str) -> Order | None:
        """Return the current state of an order, or None when it is unknown."""

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Return every open intraday position."""

    @abstractmethod
    def get_ltp(self, symbol: str) -> float:
        """Return the last traded price for one symbol."""

    @abstractmethod
    def available_margin(self) -> float:
        """Return the cash available to deploy."""

    @abstractmethod
    def square_off(self, symbol: str) -> None:
        """Close any open position in this symbol at market."""
```

- [ ] **Step 4: Implement the Kite client**

Create `tradingbot/core/kite_client.py`:

```python
"""Zerodha Kite Connect implementation of BrokerInterface."""

from __future__ import annotations

import logging

from tradingbot.core.broker import (
    BrokerError,
    BrokerInterface,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)
from tradingbot.core.models import Direction, Position, now_ist

logger = logging.getLogger(__name__)

EXCHANGE = "NSE"
PRODUCT_INTRADAY = "MIS"
VARIETY_REGULAR = "regular"

KITE_STATUS_MAP = {
    "COMPLETE": OrderStatus.COMPLETE,
    "CANCELLED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
}


class KiteClient(BrokerInterface):
    """Wraps kiteconnect. All orders are intraday (MIS) on NSE."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        access_token: str | None = None,
        kite=None,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        if kite is not None:
            self.kite = kite
        else:
            from kiteconnect import KiteConnect

            self.kite = KiteConnect(api_key=api_key)
            if access_token:
                self.kite.set_access_token(access_token)

    def login_url(self) -> str:
        """The URL the user opens to authorise this app."""
        return self.kite.login_url()

    def complete_login(self, request_token: str) -> str:
        """Exchange a request token for an access token and return it."""
        session = self.kite.generate_session(request_token, api_secret=self.api_secret)
        access_token = session["access_token"]
        self.kite.set_access_token(access_token)
        return access_token

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: int,
        price: float | None = None,
        trigger_price: float | None = None,
    ) -> str:
        try:
            return str(
                self.kite.place_order(
                    variety=VARIETY_REGULAR,
                    exchange=EXCHANGE,
                    tradingsymbol=symbol,
                    transaction_type=side.value,
                    quantity=quantity,
                    product=PRODUCT_INTRADAY,
                    order_type=order_type.value,
                    price=price,
                    trigger_price=trigger_price,
                )
            )
        except Exception as exc:  # noqa: BLE001 - normalised into BrokerError
            raise BrokerError(f"failed to place {side.value} order for {symbol}: {exc}") from exc

    def cancel_order(self, order_id: str) -> None:
        try:
            self.kite.cancel_order(variety=VARIETY_REGULAR, order_id=order_id)
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"failed to cancel order {order_id}: {exc}") from exc

    def get_order(self, order_id: str) -> Order | None:
        try:
            history = self.kite.order_history(order_id=order_id)
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"failed to fetch order {order_id}: {exc}") from exc

        if not history:
            return None

        latest = history[-1]
        return Order(
            order_id=str(latest["order_id"]),
            symbol=latest["tradingsymbol"],
            side=OrderSide(latest["transaction_type"]),
            order_type=OrderType(latest["order_type"]),
            quantity=int(latest["quantity"]),
            price=float(latest.get("price") or 0.0) or None,
            trigger_price=float(latest.get("trigger_price") or 0.0) or None,
            status=KITE_STATUS_MAP.get(latest["status"], OrderStatus.OPEN),
            filled_price=float(latest.get("average_price") or 0.0) or None,
            placed_at=now_ist(),
        )

    def get_positions(self) -> list[Position]:
        try:
            payload = self.kite.positions()
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"failed to fetch positions: {exc}") from exc

        positions: list[Position] = []
        for row in payload.get("day", []):
            quantity = int(row["quantity"])
            if quantity == 0:
                continue
            positions.append(
                Position(
                    symbol=row["tradingsymbol"],
                    direction=Direction.LONG if quantity > 0 else Direction.SHORT,
                    quantity=abs(quantity),
                    entry_price=float(row["average_price"]),
                    stop_loss=0.0,
                    target_1=0.0,
                    target_2=0.0,
                    entered_at=now_ist(),
                )
            )
        return positions

    def get_ltp(self, symbol: str) -> float:
        key = f"{EXCHANGE}:{symbol}"
        try:
            quote = self.kite.ltp([key])
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"failed to fetch LTP for {symbol}: {exc}") from exc

        if key not in quote:
            raise BrokerError(f"no LTP returned for {symbol}")
        return float(quote[key]["last_price"])

    def available_margin(self) -> float:
        try:
            margins = self.kite.margins(segment="equity")
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(f"failed to fetch margins: {exc}") from exc
        return float(margins["available"]["live_balance"])

    def square_off(self, symbol: str) -> None:
        for position in self.get_positions():
            if position.symbol != symbol:
                continue
            side = OrderSide.SELL if position.direction is Direction.LONG else OrderSide.BUY
            self.place_order(
                symbol=symbol,
                side=side,
                order_type=OrderType.MARKET,
                quantity=position.quantity,
            )
```

- [ ] **Step 5: Write the failing test for the virtual broker**

Create `tests/paper/__init__.py` (empty) and `tests/paper/test_virtual_broker.py`:

```python
import pytest

from tradingbot.core.broker import OrderSide, OrderStatus, OrderType
from tradingbot.core.config import PaperConfig
from tradingbot.core.models import Direction
from tradingbot.paper.virtual_broker import VirtualBroker


class PriceFeed:
    """A mutable price source the test drives by hand."""

    def __init__(self, prices):
        self.prices = dict(prices)

    def set(self, symbol, price):
        self.prices[symbol] = price

    def __call__(self, symbol):
        return self.prices[symbol]


def make_broker(prices=None, slippage_pct=0.05, capital=400000.0):
    feed = PriceFeed(prices or {"RELIANCE": 100.0})
    config = PaperConfig(slippage_pct=slippage_pct, initial_capital=capital)
    return VirtualBroker(config, price_feed=feed), feed


def test_a_market_buy_fills_immediately_with_slippage():
    broker, _ = make_broker({"RELIANCE": 100.0})

    order_id = broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)
    order = broker.get_order(order_id)

    assert order.status is OrderStatus.COMPLETE
    assert order.filled_price == pytest.approx(100.05)


def test_a_market_sell_fills_immediately_with_slippage_in_the_other_direction():
    broker, _ = make_broker({"RELIANCE": 100.0})

    order_id = broker.place_order("RELIANCE", OrderSide.SELL, OrderType.MARKET, 10)

    assert broker.get_order(order_id).filled_price == pytest.approx(99.95)


def test_a_limit_buy_rests_until_the_price_trades_down_to_it():
    broker, feed = make_broker({"RELIANCE": 105.0})

    order_id = broker.place_order("RELIANCE", OrderSide.BUY, OrderType.LIMIT, 10, price=100.0)
    assert broker.get_order(order_id).status is OrderStatus.OPEN

    feed.set("RELIANCE", 99.5)
    broker.advance()

    order = broker.get_order(order_id)
    assert order.status is OrderStatus.COMPLETE
    assert order.filled_price == pytest.approx(100.0)


def test_a_limit_sell_rests_until_the_price_trades_up_to_it():
    broker, feed = make_broker({"RELIANCE": 95.0})

    order_id = broker.place_order("RELIANCE", OrderSide.SELL, OrderType.LIMIT, 10, price=100.0)
    assert broker.get_order(order_id).status is OrderStatus.OPEN

    feed.set("RELIANCE", 101.0)
    broker.advance()

    assert broker.get_order(order_id).status is OrderStatus.COMPLETE


def test_a_stop_loss_sell_triggers_when_the_price_falls_through_it():
    broker, feed = make_broker({"RELIANCE": 100.0})
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    stop_id = broker.place_order(
        "RELIANCE", OrderSide.SELL, OrderType.SL, 10, trigger_price=95.0
    )
    feed.set("RELIANCE", 94.0)
    broker.advance()

    assert broker.get_order(stop_id).status is OrderStatus.COMPLETE
    assert broker.get_positions() == []


def test_a_filled_buy_creates_a_long_position():
    broker, _ = make_broker({"RELIANCE": 100.0})

    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)
    positions = broker.get_positions()

    assert len(positions) == 1
    assert positions[0].direction is Direction.LONG
    assert positions[0].quantity == 10


def test_selling_the_full_quantity_closes_the_position():
    broker, _ = make_broker({"RELIANCE": 100.0})
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    broker.place_order("RELIANCE", OrderSide.SELL, OrderType.MARKET, 10)

    assert broker.get_positions() == []


def test_selling_part_of_the_quantity_leaves_the_remainder_open():
    broker, _ = make_broker({"RELIANCE": 100.0})
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    broker.place_order("RELIANCE", OrderSide.SELL, OrderType.MARKET, 4)

    assert broker.get_positions()[0].quantity == 6


def test_cancelling_a_resting_order_stops_it_from_filling():
    broker, feed = make_broker({"RELIANCE": 105.0})
    order_id = broker.place_order("RELIANCE", OrderSide.BUY, OrderType.LIMIT, 10, price=100.0)

    broker.cancel_order(order_id)
    feed.set("RELIANCE", 99.0)
    broker.advance()

    assert broker.get_order(order_id).status is OrderStatus.CANCELLED
    assert broker.get_positions() == []


def test_cancelling_an_already_filled_order_is_a_no_op():
    broker, _ = make_broker({"RELIANCE": 100.0})
    order_id = broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    broker.cancel_order(order_id)

    assert broker.get_order(order_id).status is OrderStatus.COMPLETE


def test_buying_reduces_the_available_margin():
    broker, _ = make_broker({"RELIANCE": 100.0}, capital=400000.0)

    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 100)

    assert broker.available_margin() < 400000.0


def test_realised_pnl_is_recorded_when_a_position_closes_at_a_profit():
    broker, feed = make_broker({"RELIANCE": 100.0}, slippage_pct=0.0)
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    feed.set("RELIANCE", 110.0)
    broker.place_order("RELIANCE", OrderSide.SELL, OrderType.MARKET, 10)

    assert broker.realised_pnl == pytest.approx(100.0)


def test_realised_pnl_is_negative_when_a_position_closes_at_a_loss():
    broker, feed = make_broker({"RELIANCE": 100.0}, slippage_pct=0.0)
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    feed.set("RELIANCE", 90.0)
    broker.place_order("RELIANCE", OrderSide.SELL, OrderType.MARKET, 10)

    assert broker.realised_pnl == pytest.approx(-100.0)


def test_square_off_closes_a_long_at_market():
    broker, _ = make_broker({"RELIANCE": 100.0})
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    broker.square_off("RELIANCE")

    assert broker.get_positions() == []


def test_square_off_closes_a_short_at_market():
    broker, _ = make_broker({"RELIANCE": 100.0})
    broker.place_order("RELIANCE", OrderSide.SELL, OrderType.MARKET, 10)
    assert broker.get_positions()[0].direction is Direction.SHORT

    broker.square_off("RELIANCE")

    assert broker.get_positions() == []


def test_square_off_on_a_symbol_with_no_position_is_a_no_op():
    broker, _ = make_broker({"RELIANCE": 100.0})

    broker.square_off("RELIANCE")

    assert broker.get_positions() == []


def test_get_ltp_returns_the_feed_price():
    broker, feed = make_broker({"RELIANCE": 100.0})

    feed.set("RELIANCE", 123.45)

    assert broker.get_ltp("RELIANCE") == pytest.approx(123.45)


def test_get_order_for_an_unknown_id_returns_none():
    broker, _ = make_broker()

    assert broker.get_order("does-not-exist") is None
```

- [ ] **Step 6: Run the virtual broker tests to verify they fail**

Run: `pytest tests/paper/test_virtual_broker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.paper'`

- [ ] **Step 7: Implement the virtual broker**

Create `tradingbot/paper/__init__.py` (empty) and `tradingbot/paper/virtual_broker.py`:

```python
"""Simulated broker. Same contract as KiteClient, so the executor cannot tell them apart.

Prices come from an injected callable, which lets paper trading run either against a
live tick feed or against replayed historical candles.
"""

from __future__ import annotations

import itertools
import logging
from typing import Callable

from tradingbot.core.broker import (
    BrokerInterface,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)
from tradingbot.core.config import PaperConfig
from tradingbot.core.models import Direction, Position, now_ist

logger = logging.getLogger(__name__)


class VirtualBroker(BrokerInterface):
    """Fills orders against a price feed, applying a fixed slippage assumption."""

    def __init__(self, config: PaperConfig, price_feed: Callable[[str], float]) -> None:
        self.config = config
        self.price_feed = price_feed
        self.cash = config.initial_capital
        self.realised_pnl = 0.0
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}
        self._ids = itertools.count(1)

    # ----- BrokerInterface --------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: int,
        price: float | None = None,
        trigger_price: float | None = None,
    ) -> str:
        order = Order(
            order_id=f"paper-{next(self._ids)}",
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
            status=OrderStatus.OPEN,
            filled_price=None,
            placed_at=now_ist(),
        )
        self._orders[order.order_id] = order

        if order_type is OrderType.MARKET:
            self._fill(order, self._slipped(self.price_feed(symbol), side))
        else:
            self._try_fill(order)

        return order.order_id

    def cancel_order(self, order_id: str) -> None:
        order = self._orders.get(order_id)
        if order is None or order.is_terminal:
            return
        order.status = OrderStatus.CANCELLED

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    def get_ltp(self, symbol: str) -> float:
        return float(self.price_feed(symbol))

    def available_margin(self) -> float:
        return self.cash

    def square_off(self, symbol: str) -> None:
        position = self._positions.get(symbol)
        if position is None:
            return
        side = OrderSide.SELL if position.direction is Direction.LONG else OrderSide.BUY
        self.place_order(symbol, side, OrderType.MARKET, position.quantity)

    # ----- Simulation control -----------------------------------------------------

    def advance(self) -> None:
        """Re-evaluate every resting order against the current price."""
        for order in list(self._orders.values()):
            if not order.is_terminal:
                self._try_fill(order)

    # ----- Internals --------------------------------------------------------------

    def _slipped(self, price: float, side: OrderSide) -> float:
        adjustment = price * (self.config.slippage_pct / 100.0)
        return price + adjustment if side is OrderSide.BUY else price - adjustment

    def _try_fill(self, order: Order) -> None:
        price = self.price_feed(order.symbol)

        if order.order_type is OrderType.LIMIT:
            if order.side is OrderSide.BUY and price <= order.price:
                self._fill(order, order.price)
            elif order.side is OrderSide.SELL and price >= order.price:
                self._fill(order, order.price)
            return

        if order.order_type is OrderType.SL:
            triggered = (
                price <= order.trigger_price
                if order.side is OrderSide.SELL
                else price >= order.trigger_price
            )
            if triggered:
                self._fill(order, self._slipped(price, order.side))

    def _fill(self, order: Order, fill_price: float) -> None:
        order.status = OrderStatus.COMPLETE
        order.filled_price = fill_price
        self._apply_to_position(order, fill_price)

    def _apply_to_position(self, order: Order, fill_price: float) -> None:
        symbol = order.symbol
        existing = self._positions.get(symbol)
        signed = order.quantity if order.side is OrderSide.BUY else -order.quantity

        if existing is None:
            self._positions[symbol] = Position(
                symbol=symbol,
                direction=Direction.LONG if signed > 0 else Direction.SHORT,
                quantity=abs(signed),
                entry_price=fill_price,
                stop_loss=0.0,
                target_1=0.0,
                target_2=0.0,
                entered_at=now_ist(),
            )
            self.cash -= abs(signed) * fill_price
            return

        held = existing.quantity if existing.direction is Direction.LONG else -existing.quantity
        net = held + signed

        closing = (held > 0 and signed < 0) or (held < 0 and signed > 0)
        if closing:
            closed_quantity = min(abs(signed), abs(held))
            delta = fill_price - existing.entry_price
            if existing.direction is Direction.SHORT:
                delta = -delta
            self.realised_pnl += delta * closed_quantity
            self.cash += closed_quantity * fill_price

        if net == 0:
            del self._positions[symbol]
            return

        existing.quantity = abs(net)
        existing.direction = Direction.LONG if net > 0 else Direction.SHORT
        if not closing:
            self.cash -= abs(signed) * fill_price
```

- [ ] **Step 8: Run the full test suite to verify it passes**

Run: `pytest tests/ -v`
Expected: PASS — 199 tests.

- [ ] **Step 9: Commit**

```bash
git add tradingbot/core/broker.py tradingbot/core/kite_client.py tradingbot/paper/ tests/core/test_broker.py tests/paper/
git commit -m "feat: add broker interface with Kite and virtual broker implementations"
```

---

## Task 11: Executor

**Files:**
- Create: `tradingbot/executor/__init__.py`
- Create: `tradingbot/executor/order_manager.py`
- Create: `tradingbot/executor/position_monitor.py`
- Create: `tradingbot/executor/exit_manager.py`
- Create: `tradingbot/executor/executor.py`
- Test: `tests/executor/test_order_manager.py`, `tests/executor/test_exit_manager.py`, `tests/executor/test_executor.py`, `tests/executor/test_no_llm_imports.py`

**Interfaces:**
- Consumes: `TradeLeg`, `TradePlan`, `Position`, `Direction`, `ExecutedTrade`, `TradeStatus`, `Mode`, `IST` (Task 1); `BrokerInterface`, `OrderSide`, `OrderType`, `OrderStatus`, `Order` (Task 10); `RiskManager` (Task 7); `Database` (Task 2); `ExecutionConfig` (Task 1).
- Produces:
  - `LegState` dataclass tracking one leg through its lifecycle.
  - `OrderManager(broker)` with `submit_entry(leg) -> str`, `submit_stop(leg, quantity) -> str`, `cancel(order_id)`, `exit_at_market(leg, quantity)`, `order_status(order_id)`.
  - `PositionMonitor(broker)` with `snapshot() -> dict[str, Position]`, `unrealised_pnl(positions) -> float`.
  - `ExitDecision` enum: `HOLD`, `BOOK_TARGET_1`, `BOOK_TARGET_2`, `STOP_HIT`, `SQUARE_OFF`.
  - `ExitManager(square_off_time)` with `decide(state, price, now) -> ExitDecision` and `trail_stop(state) -> float`.
  - `Executor(broker, plan, risk_manager, database, execution_config, mode, clock=now_ist)` with `start() -> None`, `tick() -> None`, `adopt_existing_positions() -> None`, `is_done -> bool`.

**Architectural rule:** nothing under `tradingbot/executor/` may import `tradingbot.core.llm`. Step 1 pins this with a test.

- [ ] **Step 1: Write the failing test that forbids LLM imports in the executor**

Create `tests/executor/__init__.py` (empty) and `tests/executor/test_no_llm_imports.py`:

```python
from pathlib import Path

EXECUTOR_DIR = Path(__file__).resolve().parents[2] / "tradingbot" / "executor"


def test_executor_package_exists():
    assert EXECUTOR_DIR.is_dir()


def test_no_executor_module_imports_the_llm_package():
    offenders = []

    for path in EXECUTOR_DIR.rglob("*.py"):
        source = path.read_text()
        if "tradingbot.core.llm" in source or "from anthropic" in source or "import anthropic" in source:
            offenders.append(path.name)

    assert offenders == [], (
        f"the executor must never depend on an LLM, but these files do: {offenders}"
    )
```

- [ ] **Step 2: Run the import guard test to verify it fails**

Run: `pytest tests/executor/test_no_llm_imports.py -v`
Expected: FAIL on `test_executor_package_exists` because the directory does not exist yet.

- [ ] **Step 3: Write the failing test for the order manager**

Create `tests/executor/test_order_manager.py`:

```python
from datetime import time

import pytest

from tradingbot.core.broker import OrderSide, OrderStatus, OrderType
from tradingbot.core.config import PaperConfig
from tradingbot.core.models import Direction, EntryType, StrategyName, TradeLeg
from tradingbot.executor.order_manager import OrderManager
from tradingbot.paper.virtual_broker import VirtualBroker


def make_leg(direction=Direction.LONG, entry_type=EntryType.LIMIT, quantity=10) -> TradeLeg:
    return TradeLeg(
        symbol="RELIANCE",
        exchange="NSE",
        strategy=StrategyName.BREAKOUT,
        direction=direction,
        entry_price=100.0,
        entry_type=entry_type,
        stop_loss=95.0 if direction is Direction.LONG else 105.0,
        target_1=110.0 if direction is Direction.LONG else 90.0,
        target_2=115.0 if direction is Direction.LONG else 85.0,
        quantity=quantity,
        risk_amount=50.0,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        max_entry_wait=time(11, 0),
        exit_before=time(15, 10),
        confidence=0.8,
        reasoning="Test leg.",
    )


def make_manager(price=100.0):
    prices = {"RELIANCE": price}
    broker = VirtualBroker(PaperConfig(slippage_pct=0.0, initial_capital=400000.0), lambda s: prices[s])
    return OrderManager(broker), broker, prices


def test_a_long_entry_is_submitted_as_a_buy():
    manager, broker, _ = make_manager()

    order_id = manager.submit_entry(make_leg(Direction.LONG))

    assert broker.get_order(order_id).side is OrderSide.BUY


def test_a_short_entry_is_submitted_as_a_sell():
    manager, broker, _ = make_manager()

    order_id = manager.submit_entry(make_leg(Direction.SHORT))

    assert broker.get_order(order_id).side is OrderSide.SELL


def test_a_limit_entry_uses_the_planned_entry_price():
    manager, broker, _ = make_manager(price=105.0)

    order_id = manager.submit_entry(make_leg(entry_type=EntryType.LIMIT))
    order = broker.get_order(order_id)

    assert order.order_type is OrderType.LIMIT
    assert order.price == pytest.approx(100.0)


def test_a_stop_entry_is_submitted_with_a_trigger_price():
    manager, broker, _ = make_manager(price=95.0)

    order_id = manager.submit_entry(make_leg(entry_type=EntryType.STOP))
    order = broker.get_order(order_id)

    assert order.order_type is OrderType.SL
    assert order.trigger_price == pytest.approx(100.0)


def test_a_stop_for_a_long_position_is_a_sell_with_the_stop_trigger():
    manager, broker, _ = make_manager()

    order_id = manager.submit_stop(make_leg(Direction.LONG), quantity=10)
    order = broker.get_order(order_id)

    assert order.side is OrderSide.SELL
    assert order.order_type is OrderType.SL
    assert order.trigger_price == pytest.approx(95.0)


def test_a_stop_for_a_short_position_is_a_buy():
    manager, broker, _ = make_manager()

    order_id = manager.submit_stop(make_leg(Direction.SHORT), quantity=10)

    assert broker.get_order(order_id).side is OrderSide.BUY


def test_exit_at_market_closes_a_long_with_a_sell():
    manager, broker, _ = make_manager()
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    order_id = manager.exit_at_market(make_leg(Direction.LONG), quantity=10)
    order = broker.get_order(order_id)

    assert order.side is OrderSide.SELL
    assert order.order_type is OrderType.MARKET
    assert broker.get_positions() == []


def test_exit_at_market_can_close_part_of_a_position():
    manager, broker, _ = make_manager()
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    manager.exit_at_market(make_leg(Direction.LONG), quantity=5)

    assert broker.get_positions()[0].quantity == 5


def test_cancel_marks_a_resting_order_cancelled():
    manager, broker, _ = make_manager(price=105.0)
    order_id = manager.submit_entry(make_leg())

    manager.cancel(order_id)

    assert broker.get_order(order_id).status is OrderStatus.CANCELLED


def test_order_status_reports_the_current_status():
    manager, broker, prices = make_manager(price=105.0)
    order_id = manager.submit_entry(make_leg())

    assert manager.order_status(order_id) is OrderStatus.OPEN

    prices["RELIANCE"] = 99.0
    broker.advance()

    assert manager.order_status(order_id) is OrderStatus.COMPLETE


def test_order_status_for_an_unknown_id_is_none():
    manager, _, _ = make_manager()

    assert manager.order_status("nope") is None
```

- [ ] **Step 4: Write the failing test for the exit manager**

Create `tests/executor/test_exit_manager.py`:

```python
from datetime import datetime, time

import pytest

from tradingbot.core.models import IST, Direction, EntryType, StrategyName, TradeLeg
from tradingbot.executor.exit_manager import ExitDecision, ExitManager
from tradingbot.executor.executor import LegState


def make_leg(direction=Direction.LONG) -> TradeLeg:
    long_side = direction is Direction.LONG
    return TradeLeg(
        symbol="RELIANCE",
        exchange="NSE",
        strategy=StrategyName.BREAKOUT,
        direction=direction,
        entry_price=100.0,
        entry_type=EntryType.LIMIT,
        stop_loss=95.0 if long_side else 105.0,
        target_1=110.0 if long_side else 90.0,
        target_2=115.0 if long_side else 85.0,
        quantity=10,
        risk_amount=50.0,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        max_entry_wait=time(11, 0),
        exit_before=time(15, 10),
        confidence=0.8,
        reasoning="Test leg.",
    )


def make_state(direction=Direction.LONG, target_1_booked=False, current_stop=None) -> LegState:
    leg = make_leg(direction)
    state = LegState(leg=leg)
    state.filled_quantity = 10
    state.entry_fill_price = 100.0
    state.target_1_booked = target_1_booked
    state.current_stop = current_stop if current_stop is not None else leg.stop_loss
    return state


def at(hour, minute):
    return datetime(2026, 9, 24, hour, minute, tzinfo=IST)


def make_manager():
    return ExitManager(square_off_time=time(15, 10))


def test_a_long_holds_between_stop_and_target():
    assert make_manager().decide(make_state(), price=103.0, now=at(11, 0)) is ExitDecision.HOLD


def test_a_long_books_target_1_when_it_is_reached():
    decision = make_manager().decide(make_state(), price=110.0, now=at(11, 0))

    assert decision is ExitDecision.BOOK_TARGET_1


def test_a_long_books_target_2_only_after_target_1():
    state = make_state(target_1_booked=True)

    assert make_manager().decide(state, price=115.0, now=at(11, 0)) is ExitDecision.BOOK_TARGET_2


def test_a_long_stops_out_when_price_falls_through_the_stop():
    assert make_manager().decide(make_state(), price=94.0, now=at(11, 0)) is ExitDecision.STOP_HIT


def test_a_long_stops_out_on_the_trailed_stop_not_the_original():
    state = make_state(target_1_booked=True, current_stop=100.0)

    assert make_manager().decide(state, price=99.0, now=at(11, 0)) is ExitDecision.STOP_HIT


def test_a_short_books_target_1_when_price_falls_to_it():
    state = make_state(Direction.SHORT)

    assert make_manager().decide(state, price=90.0, now=at(11, 0)) is ExitDecision.BOOK_TARGET_1


def test_a_short_stops_out_when_price_rises_through_the_stop():
    state = make_state(Direction.SHORT)

    assert make_manager().decide(state, price=106.0, now=at(11, 0)) is ExitDecision.STOP_HIT


def test_a_short_holds_between_its_levels():
    state = make_state(Direction.SHORT)

    assert make_manager().decide(state, price=98.0, now=at(11, 0)) is ExitDecision.HOLD


def test_square_off_time_overrides_a_perfectly_healthy_position():
    assert make_manager().decide(make_state(), price=103.0, now=at(15, 10)) is ExitDecision.SQUARE_OFF


def test_square_off_applies_after_the_cutoff_too():
    assert make_manager().decide(make_state(), price=103.0, now=at(15, 25)) is ExitDecision.SQUARE_OFF


def test_square_off_takes_priority_over_a_target():
    assert make_manager().decide(make_state(), price=120.0, now=at(15, 12)) is ExitDecision.SQUARE_OFF


def test_a_position_with_no_fill_always_holds():
    state = make_state()
    state.filled_quantity = 0

    assert make_manager().decide(state, price=94.0, now=at(11, 0)) is ExitDecision.HOLD


def test_trailing_a_long_stop_moves_it_to_the_entry_fill():
    state = make_state()

    assert make_manager().trail_stop(state) == pytest.approx(100.0)


def test_trailing_never_moves_a_long_stop_backwards():
    state = make_state(current_stop=102.0)

    assert make_manager().trail_stop(state) == pytest.approx(102.0)


def test_trailing_a_short_stop_moves_it_down_to_the_entry_fill():
    state = make_state(Direction.SHORT)

    assert make_manager().trail_stop(state) == pytest.approx(100.0)


def test_trailing_never_moves_a_short_stop_backwards():
    state = make_state(Direction.SHORT, current_stop=98.0)

    assert make_manager().trail_stop(state) == pytest.approx(98.0)
```

- [ ] **Step 5: Run the executor component tests to verify they fail**

Run: `pytest tests/executor/ -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.executor'`

- [ ] **Step 6: Implement the order manager**

Create `tradingbot/executor/__init__.py` (empty) and `tradingbot/executor/order_manager.py`:

```python
"""Translates trade legs into broker orders. No decisions are made here."""

from __future__ import annotations

import logging

from tradingbot.core.broker import BrokerInterface, OrderSide, OrderStatus, OrderType
from tradingbot.core.models import Direction, EntryType, TradeLeg

logger = logging.getLogger(__name__)


def entry_side(direction: Direction) -> OrderSide:
    return OrderSide.BUY if direction is Direction.LONG else OrderSide.SELL


def exit_side(direction: Direction) -> OrderSide:
    return OrderSide.SELL if direction is Direction.LONG else OrderSide.BUY


class OrderManager:
    """A thin, mechanical layer between leg intent and broker calls."""

    def __init__(self, broker: BrokerInterface) -> None:
        self.broker = broker

    def submit_entry(self, leg: TradeLeg) -> str:
        side = entry_side(leg.direction)

        if leg.entry_type is EntryType.LIMIT:
            order_id = self.broker.place_order(
                symbol=leg.symbol,
                side=side,
                order_type=OrderType.LIMIT,
                quantity=leg.quantity,
                price=leg.entry_price,
            )
        else:
            order_id = self.broker.place_order(
                symbol=leg.symbol,
                side=side,
                order_type=OrderType.SL,
                quantity=leg.quantity,
                trigger_price=leg.entry_price,
            )

        logger.info(
            "submitted %s entry for %s x%d at %.2f (order %s)",
            side.value,
            leg.symbol,
            leg.quantity,
            leg.entry_price,
            order_id,
        )
        return order_id

    def submit_stop(self, leg: TradeLeg, quantity: int, trigger_price: float | None = None) -> str:
        trigger = leg.stop_loss if trigger_price is None else trigger_price
        order_id = self.broker.place_order(
            symbol=leg.symbol,
            side=exit_side(leg.direction),
            order_type=OrderType.SL,
            quantity=quantity,
            trigger_price=trigger,
        )
        logger.info("submitted stop for %s x%d at %.2f (order %s)", leg.symbol, quantity, trigger, order_id)
        return order_id

    def exit_at_market(self, leg: TradeLeg, quantity: int) -> str:
        order_id = self.broker.place_order(
            symbol=leg.symbol,
            side=exit_side(leg.direction),
            order_type=OrderType.MARKET,
            quantity=quantity,
        )
        logger.info("market exit for %s x%d (order %s)", leg.symbol, quantity, order_id)
        return order_id

    def cancel(self, order_id: str) -> None:
        self.broker.cancel_order(order_id)
        logger.info("cancelled order %s", order_id)

    def order_status(self, order_id: str) -> OrderStatus | None:
        order = self.broker.get_order(order_id)
        return order.status if order is not None else None
```

- [ ] **Step 7: Implement the position monitor and exit manager**

Create `tradingbot/executor/position_monitor.py`:

```python
"""Reads live position state from the broker."""

from __future__ import annotations

from tradingbot.core.broker import BrokerInterface
from tradingbot.core.models import Position


class PositionMonitor:
    """Turns the broker's position list into something keyed by symbol."""

    def __init__(self, broker: BrokerInterface) -> None:
        self.broker = broker

    def snapshot(self) -> dict[str, Position]:
        return {position.symbol: position for position in self.broker.get_positions()}

    def unrealised_pnl(self, positions: dict[str, Position]) -> float:
        total = 0.0
        for symbol, position in positions.items():
            total += position.unrealised_pnl(self.broker.get_ltp(symbol))
        return total
```

Create `tradingbot/executor/exit_manager.py`:

```python
"""Exit rules. Deterministic, ordered, and independent of any model."""

from __future__ import annotations

from datetime import datetime, time
from enum import Enum

from tradingbot.core.models import Direction


class ExitDecision(str, Enum):
    HOLD = "hold"
    BOOK_TARGET_1 = "book_target_1"
    BOOK_TARGET_2 = "book_target_2"
    STOP_HIT = "stop_hit"
    SQUARE_OFF = "square_off"


class ExitManager:
    """Decides what to do with a filled leg at the current price and time."""

    def __init__(self, square_off_time: time) -> None:
        self.square_off_time = square_off_time

    def decide(self, state, price: float, now: datetime) -> ExitDecision:
        """Square-off beats everything; then the stop; then targets."""
        if state.filled_quantity <= 0:
            return ExitDecision.HOLD

        if now.timetz().replace(tzinfo=None) >= self.square_off_time:
            return ExitDecision.SQUARE_OFF

        leg = state.leg
        stop = state.current_stop

        if leg.direction is Direction.LONG:
            if price <= stop:
                return ExitDecision.STOP_HIT
            if state.target_1_booked:
                if price >= leg.target_2:
                    return ExitDecision.BOOK_TARGET_2
            elif price >= leg.target_1:
                return ExitDecision.BOOK_TARGET_1
        else:
            if price >= stop:
                return ExitDecision.STOP_HIT
            if state.target_1_booked:
                if price <= leg.target_2:
                    return ExitDecision.BOOK_TARGET_2
            elif price <= leg.target_1:
                return ExitDecision.BOOK_TARGET_1

        return ExitDecision.HOLD

    def trail_stop(self, state) -> float:
        """Ratchet the stop to breakeven. It may tighten, never loosen."""
        breakeven = state.entry_fill_price
        if state.leg.direction is Direction.LONG:
            return max(state.current_stop, breakeven)
        return min(state.current_stop, breakeven)
```

- [ ] **Step 8: Write the failing test for the executor (covers Review Focus item 3)**

Create `tests/executor/test_executor.py`:

```python
from datetime import date, datetime, time

import pytest

from tradingbot.core.broker import OrderSide, OrderType
from tradingbot.core.config import ExecutionConfig, PaperConfig, RiskConfig, StrategyConfig
from tradingbot.core.database import Database
from tradingbot.core.models import (
    IST,
    Direction,
    EntryType,
    MarketRegime,
    Mode,
    StrategyName,
    TradeLeg,
    TradePlan,
)
from tradingbot.core.risk_manager import RiskManager
from tradingbot.executor.executor import Executor
from tradingbot.paper.virtual_broker import VirtualBroker


def make_leg(symbol="RELIANCE", quantity=10) -> TradeLeg:
    return TradeLeg(
        symbol=symbol,
        exchange="NSE",
        strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG,
        entry_price=100.0,
        entry_type=EntryType.LIMIT,
        stop_loss=95.0,
        target_1=110.0,
        target_2=115.0,
        quantity=quantity,
        risk_amount=50.0,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        max_entry_wait=time(11, 0),
        exit_before=time(15, 10),
        confidence=0.8,
        reasoning="Test leg.",
    )


def make_plan(legs, generated_at=datetime(2026, 9, 24, 8, 0, tzinfo=IST)) -> TradePlan:
    return TradePlan(
        trade_date="2026-09-24",
        generated_at=generated_at,
        capital=400000.0,
        max_risk_per_trade_pct=0.01,
        max_daily_loss_pct=0.02,
        market_regime=MarketRegime.TRENDING,
        market_summary="Nifty bullish.",
        legs=legs,
    )


def make_execution_config() -> ExecutionConfig:
    return ExecutionConfig(
        entry_slippage_pct=0.05,
        square_off_time=time(15, 10),
        connection_timeout_sec=30,
        heartbeat_interval_sec=60,
        plan_max_age_hours=14.0,
        max_entry_price_drift_pct=2.0,
    )


class Clock:
    """A hand-cranked clock so tests control the session timeline."""

    def __init__(self, start=datetime(2026, 9, 24, 9, 30, tzinfo=IST)):
        self.now = start

    def __call__(self):
        return self.now

    def advance_to(self, hour, minute):
        self.now = datetime(2026, 9, 24, hour, minute, tzinfo=IST)


def build(tmp_path, legs, price=100.0, clock=None, plan=None):
    prices = {leg.symbol: price for leg in legs} or {"RELIANCE": price}
    broker = VirtualBroker(
        PaperConfig(slippage_pct=0.0, initial_capital=400000.0), lambda symbol: prices[symbol]
    )
    database = Database(tmp_path / "exec.db")
    database.initialise()
    risk_manager = RiskManager(
        RiskConfig(
            max_risk_per_trade_pct=0.01,
            max_daily_loss_pct=0.02,
            max_capital_deployed_pct=0.50,
            max_concurrent_positions=2,
        ),
        StrategyConfig(
            backtest_days=30,
            candle_interval="15minute",
            min_confidence=0.5,
            min_reward_risk=1.5,
            max_trades_per_day=2,
        ),
        capital=400000.0,
    )
    executor = Executor(
        broker=broker,
        plan=plan if plan is not None else make_plan(legs),
        risk_manager=risk_manager,
        database=database,
        execution_config=make_execution_config(),
        mode=Mode.PAPER,
        clock=clock or Clock(),
    )
    return executor, broker, prices, database


def test_start_places_an_entry_order_for_each_leg(tmp_path):
    executor, broker, _, _ = build(tmp_path, [make_leg()], price=105.0)

    executor.start()

    assert len(executor.states) == 1
    assert executor.states[0].entry_order_id is not None


def test_start_skips_a_leg_whose_price_has_gapped_away(tmp_path):
    executor, _, _, _ = build(tmp_path, [make_leg()], price=130.0)

    executor.start()

    assert executor.states[0].skipped_reason is not None
    assert executor.states[0].entry_order_id is None


def test_a_stale_plan_prevents_any_order(tmp_path):
    stale = make_plan([make_leg()], generated_at=datetime(2026, 9, 21, 8, 0, tzinfo=IST))
    executor, broker, _, _ = build(tmp_path, [make_leg()], plan=stale)

    executor.start()

    assert executor.blocked is True
    assert executor.states == []


def test_a_filled_entry_gets_a_protective_stop(tmp_path):
    executor, broker, prices, _ = build(tmp_path, [make_leg()], price=105.0)
    executor.start()

    prices["RELIANCE"] = 99.0
    broker.advance()
    executor.tick()

    state = executor.states[0]
    assert state.filled_quantity == 10
    assert state.stop_order_id is not None


def test_reaching_target_1_books_half_and_trails_the_stop(tmp_path):
    executor, broker, prices, _ = build(tmp_path, [make_leg()], price=100.0)
    executor.start()
    broker.advance()
    executor.tick()

    prices["RELIANCE"] = 110.0
    executor.tick()

    state = executor.states[0]
    assert state.target_1_booked is True
    assert state.filled_quantity == 5
    assert state.current_stop == pytest.approx(state.entry_fill_price)


def test_reaching_target_2_closes_the_remainder(tmp_path):
    executor, broker, prices, _ = build(tmp_path, [make_leg()], price=100.0)
    executor.start()
    broker.advance()
    executor.tick()

    prices["RELIANCE"] = 110.0
    executor.tick()
    prices["RELIANCE"] = 115.0
    executor.tick()

    assert executor.states[0].filled_quantity == 0
    assert broker.get_positions() == []


def test_hitting_the_stop_closes_the_whole_position(tmp_path):
    executor, broker, prices, _ = build(tmp_path, [make_leg()], price=100.0)
    executor.start()
    broker.advance()
    executor.tick()

    prices["RELIANCE"] = 94.0
    executor.tick()

    assert executor.states[0].filled_quantity == 0
    assert broker.get_positions() == []


def test_an_unfilled_entry_is_cancelled_after_max_entry_wait(tmp_path):
    clock = Clock()
    executor, broker, _, _ = build(tmp_path, [make_leg()], price=105.0, clock=clock)
    executor.start()

    clock.advance_to(11, 5)
    executor.tick()

    assert executor.states[0].cancelled is True


def test_square_off_time_closes_everything(tmp_path):
    clock = Clock()
    executor, broker, prices, _ = build(tmp_path, [make_leg()], price=100.0, clock=clock)
    executor.start()
    broker.advance()
    executor.tick()

    clock.advance_to(15, 10)
    executor.tick()

    assert broker.get_positions() == []
    assert executor.is_done is True


def test_the_daily_loss_kill_switch_stops_further_trading(tmp_path):
    executor, broker, prices, _ = build(tmp_path, [make_leg(quantity=2000)], price=100.0)
    executor.start()
    broker.advance()
    executor.tick()

    prices["RELIANCE"] = 94.0
    executor.tick()   # stop hit, realises a large loss
    executor.tick()   # next tick notices the breach

    assert executor.kill_switch_tripped is True


def test_a_closed_trade_is_written_to_the_database(tmp_path):
    executor, broker, prices, database = build(tmp_path, [make_leg()], price=100.0)
    executor.start()
    broker.advance()
    executor.tick()

    prices["RELIANCE"] = 94.0
    executor.tick()

    trades = database.trades_for_date("2026-09-24")
    assert len(trades) == 1
    assert trades[0].symbol == "RELIANCE"
    assert trades[0].exit_reason == "stop_hit"
    assert trades[0].mode is Mode.PAPER


def test_restarting_with_an_existing_position_adopts_it_instead_of_re_entering(tmp_path):
    executor, broker, prices, _ = build(tmp_path, [make_leg()], price=100.0)
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    executor.start()

    state = executor.states[0]
    assert state.adopted is True
    assert state.filled_quantity == 10
    assert state.entry_order_id is None


def test_an_adopted_position_gets_a_protective_stop(tmp_path):
    executor, broker, prices, _ = build(tmp_path, [make_leg()], price=100.0)
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    executor.start()

    assert executor.states[0].stop_order_id is not None


def test_adopting_does_not_place_a_second_entry_order(tmp_path):
    executor, broker, prices, _ = build(tmp_path, [make_leg()], price=100.0)
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    executor.start()

    assert broker.get_positions()[0].quantity == 10


def test_restarting_after_square_off_time_closes_the_adopted_position(tmp_path):
    clock = Clock(datetime(2026, 9, 24, 15, 20, tzinfo=IST))
    executor, broker, prices, _ = build(tmp_path, [make_leg()], price=100.0, clock=clock)
    broker.place_order("RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)

    executor.start()
    executor.tick()

    assert broker.get_positions() == []
```

- [ ] **Step 9: Implement the executor**

Create `tradingbot/executor/executor.py`:

```python
"""The executor agent: reads a plan and follows it. No model, no judgement calls."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from tradingbot.core.broker import BrokerInterface, OrderStatus
from tradingbot.core.config import ExecutionConfig
from tradingbot.core.database import Database
from tradingbot.core.models import (
    Direction,
    ExecutedTrade,
    Mode,
    TradeLeg,
    TradePlan,
    TradeStatus,
    now_ist,
)
from tradingbot.core.risk_manager import RiskManager
from tradingbot.executor.exit_manager import ExitDecision, ExitManager
from tradingbot.executor.order_manager import OrderManager
from tradingbot.executor.position_monitor import PositionMonitor

logger = logging.getLogger(__name__)


@dataclass
class LegState:
    """Everything the executor knows about one leg right now."""

    leg: TradeLeg
    entry_order_id: str | None = None
    stop_order_id: str | None = None
    filled_quantity: int = 0
    entry_fill_price: float = 0.0
    current_stop: float = 0.0
    target_1_booked: bool = False
    cancelled: bool = False
    adopted: bool = False
    skipped_reason: str | None = None
    entered_at: datetime | None = None
    realised_pnl: float = 0.0

    def __post_init__(self) -> None:
        if self.current_stop == 0.0:
            self.current_stop = self.leg.stop_loss

    @property
    def is_finished(self) -> bool:
        return self.cancelled or self.skipped_reason is not None or (
            self.entered_at is not None and self.filled_quantity == 0
        )


class Executor:
    """Runs one trading session against one plan."""

    def __init__(
        self,
        broker: BrokerInterface,
        plan: TradePlan,
        risk_manager: RiskManager,
        database: Database,
        execution_config: ExecutionConfig,
        mode: Mode,
        clock=now_ist,
    ) -> None:
        self.broker = broker
        self.plan = plan
        self.risk_manager = risk_manager
        self.database = database
        self.config = execution_config
        self.mode = mode
        self.clock = clock

        self.orders = OrderManager(broker)
        self.monitor = PositionMonitor(broker)
        self.exits = ExitManager(execution_config.square_off_time)

        self.states: list[LegState] = []
        self.blocked = False
        self.kill_switch_tripped = False

    # ----- Lifecycle --------------------------------------------------------------

    def start(self) -> None:
        """Vet the plan, adopt anything already open, then submit entries."""
        now = self.clock()
        blockers = self.risk_manager.vet_plan_for_execution(
            self.plan, now=now, available_capital=self.broker.available_margin()
        )
        if blockers:
            for reason in blockers:
                logger.error("refusing to execute: %s", reason)
            self.blocked = True
            return

        open_positions = self.monitor.snapshot()

        for leg in self.plan.legs:
            state = LegState(leg=leg)
            self.states.append(state)

            existing = open_positions.get(leg.symbol)
            if existing is not None:
                self._adopt(state, existing)
                continue

            price = self.broker.get_ltp(leg.symbol)
            drift = self.risk_manager.vet_leg_at_open(leg, price)
            if drift is not None:
                logger.warning("skipping %s: %s", leg.symbol, drift)
                state.skipped_reason = drift
                continue

            state.entry_order_id = self.orders.submit_entry(leg)

    def tick(self) -> None:
        """One pass of the event loop. Safe to call as often as you like."""
        if self.blocked:
            return

        now = self.clock()

        if not self.kill_switch_tripped:
            # _close() writes every exit to the database as it happens, so the
            # database is the single source of truth here. Adding an in-memory
            # tally on top would double count each loss.
            realised = self.database.realised_pnl_for_date(self.plan.trade_date)
            if self.risk_manager.daily_loss_breached(realised):
                logger.error("daily loss limit breached at %.2f; halting", realised)
                self.kill_switch_tripped = True
                self._halt_everything(now)
                return

        for state in self.states:
            if state.is_finished:
                continue

            if state.filled_quantity == 0:
                self._poll_entry(state, now)
                continue

            self._manage_open_leg(state, now)

    @property
    def is_done(self) -> bool:
        """True once no leg can do anything further today."""
        if self.blocked:
            return True
        return all(state.is_finished for state in self.states)

    # ----- Entry handling ---------------------------------------------------------

    def _poll_entry(self, state: LegState, now: datetime) -> None:
        if state.entry_order_id is None:
            return

        status = self.orders.order_status(state.entry_order_id)

        if status is OrderStatus.COMPLETE:
            order = self.broker.get_order(state.entry_order_id)
            state.filled_quantity = order.quantity
            state.entry_fill_price = float(order.filled_price)
            state.entered_at = now
            state.current_stop = state.leg.stop_loss
            state.stop_order_id = self.orders.submit_stop(state.leg, state.filled_quantity)
            logger.info(
                "%s filled x%d at %.2f", state.leg.symbol, state.filled_quantity, state.entry_fill_price
            )
            return

        if status in (OrderStatus.CANCELLED, OrderStatus.REJECTED):
            state.cancelled = True
            return

        cutoff = state.leg.max_entry_wait
        if now.timetz().replace(tzinfo=None) >= cutoff:
            logger.info("%s did not fill by %s; cancelling", state.leg.symbol, cutoff)
            self.orders.cancel(state.entry_order_id)
            state.cancelled = True

    # ----- Open position handling -------------------------------------------------

    def _manage_open_leg(self, state: LegState, now: datetime) -> None:
        price = self.broker.get_ltp(state.leg.symbol)
        decision = self.exits.decide(state, price, now)

        if decision is ExitDecision.HOLD:
            return

        if decision is ExitDecision.BOOK_TARGET_1:
            half = max(1, state.filled_quantity // 2)
            self._close(state, half, price, reason="target_1", now=now)
            state.target_1_booked = True
            state.current_stop = self.exits.trail_stop(state)
            self._replace_stop(state)
            return

        reason = {
            ExitDecision.BOOK_TARGET_2: "target_2",
            ExitDecision.STOP_HIT: "stop_hit",
            ExitDecision.SQUARE_OFF: "square_off",
        }[decision]
        self._close(state, state.filled_quantity, price, reason=reason, now=now)

    def _replace_stop(self, state: LegState) -> None:
        if state.stop_order_id is not None:
            self.orders.cancel(state.stop_order_id)
        state.stop_order_id = self.orders.submit_stop(
            state.leg, state.filled_quantity, trigger_price=state.current_stop
        )

    def _close(self, state: LegState, quantity: int, price: float, reason: str, now: datetime) -> None:
        if quantity <= 0:
            return

        if state.stop_order_id is not None:
            self.orders.cancel(state.stop_order_id)
            state.stop_order_id = None

        order_id = self.orders.exit_at_market(state.leg, quantity)
        order = self.broker.get_order(order_id)
        fill_price = float(order.filled_price) if order and order.filled_price else price

        delta = fill_price - state.entry_fill_price
        if state.leg.direction is Direction.SHORT:
            delta = -delta
        pnl = delta * quantity
        state.realised_pnl += pnl
        state.filled_quantity -= quantity

        logger.info(
            "closed %s x%d at %.2f (%s), pnl %.2f",
            state.leg.symbol,
            quantity,
            fill_price,
            reason,
            pnl,
        )

        self.database.record_trade(
            ExecutedTrade(
                trade_date=self.plan.trade_date,
                symbol=state.leg.symbol,
                strategy=state.leg.strategy,
                direction=state.leg.direction,
                quantity=quantity,
                entry_price=state.entry_fill_price,
                exit_price=fill_price,
                stop_loss=state.current_stop,
                target_1=state.leg.target_1,
                target_2=state.leg.target_2,
                entered_at=state.entered_at or now,
                exited_at=now,
                pnl=pnl,
                exit_reason=reason,
                status=TradeStatus.CLOSED,
                mode=self.mode,
            )
        )

        if state.filled_quantity > 0 and state.stop_order_id is None:
            self._replace_stop(state)

    # ----- Recovery and shutdown --------------------------------------------------

    def _adopt(self, state: LegState, position) -> None:
        """Take ownership of a position that already existed at startup."""
        state.adopted = True
        state.filled_quantity = position.quantity
        state.entry_fill_price = position.entry_price
        state.entered_at = position.entered_at
        state.current_stop = state.leg.stop_loss
        state.stop_order_id = self.orders.submit_stop(state.leg, state.filled_quantity)
        logger.warning(
            "adopted an existing %s position x%d at %.2f; no new entry will be placed",
            state.leg.symbol,
            state.filled_quantity,
            state.entry_fill_price,
        )

    def _halt_everything(self, now: datetime) -> None:
        for state in self.states:
            if state.entry_order_id is not None and state.filled_quantity == 0 and not state.cancelled:
                self.orders.cancel(state.entry_order_id)
                state.cancelled = True
            if state.filled_quantity > 0:
                price = self.broker.get_ltp(state.leg.symbol)
                self._close(state, state.filled_quantity, price, reason="kill_switch", now=now)
```

- [ ] **Step 10: Run the executor tests to verify they pass**

Run: `pytest tests/executor/ -v`
Expected: PASS — 45 tests, including the LLM import guard.

- [ ] **Step 11: Run the full test suite to verify it passes**

Run: `pytest tests/ -v`
Expected: PASS — 244 tests.

- [ ] **Step 12: Commit**

```bash
git add tradingbot/executor/ tests/executor/
git commit -m "feat: add deterministic executor with trailing stops and crash recovery"
```

---

## Task 12: CLI and Wiring

**Files:**
- Create: `tradingbot/cli.py`
- Create: `tradingbot/__main__.py`
- Create: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1-11.
- Produces:
  - `cli` — the click group.
  - Commands: `analyze`, `execute`, `status`, `history`, `plan show`, `backtest`, `auth`.
  - `build_analysis_stack(config, plan_dir, log_dir) -> PlanGenerator` and `build_broker(config, price_feed=None) -> BrokerInterface`.

- [ ] **Step 1: Write the failing test for the CLI**

Create `tests/test_cli.py`:

```python
import json
from datetime import datetime, time

from click.testing import CliRunner

from tradingbot.cli import cli
from tradingbot.core.database import Database
from tradingbot.core.models import (
    IST,
    Direction,
    EntryType,
    ExecutedTrade,
    MarketRegime,
    Mode,
    StrategyName,
    TradeLeg,
    TradePlan,
    TradeStatus,
)
from tradingbot.core.plan_store import PlanStore

CONFIG_TEXT = """
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
max_entry_price_drift_pct = 2.0

[llm]
provider = "anthropic"
model = "claude-sonnet-5"
timeout_sec = 60
max_retries = 1

[paper]
slippage_pct = 0.05
initial_capital = 400000
"""


def write_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("KITE_API_KEY", "kite-key")
    monkeypatch.setenv("KITE_API_SECRET", "kite-secret")


def write_config(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG_TEXT)
    return path


def make_plan() -> TradePlan:
    leg = TradeLeg(
        symbol="RELIANCE",
        exchange="NSE",
        strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG,
        entry_price=2855.0,
        entry_type=EntryType.LIMIT,
        stop_loss=2830.0,
        target_1=2890.0,
        target_2=2920.0,
        quantity=16,
        risk_amount=4000.0,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        max_entry_wait=time(11, 0),
        exit_before=time(15, 10),
        confidence=0.72,
        reasoning="Breaking out of consolidation.",
    )
    return TradePlan(
        trade_date="2026-09-24",
        generated_at=datetime(2026, 9, 23, 22, 30, tzinfo=IST),
        capital=400000.0,
        max_risk_per_trade_pct=0.01,
        max_daily_loss_pct=0.02,
        market_regime=MarketRegime.TRENDING,
        market_summary="Nifty bullish.",
        legs=[leg],
    )


def make_trade() -> ExecutedTrade:
    return ExecutedTrade(
        trade_date="2026-09-24",
        symbol="RELIANCE",
        strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG,
        quantity=16,
        entry_price=2855.0,
        exit_price=2890.0,
        stop_loss=2830.0,
        target_1=2890.0,
        target_2=2920.0,
        entered_at=datetime(2026, 9, 24, 9, 45, tzinfo=IST),
        exited_at=datetime(2026, 9, 24, 13, 15, tzinfo=IST),
        pnl=560.0,
        exit_reason="target_1",
        status=TradeStatus.CLOSED,
        mode=Mode.PAPER,
    )


def test_the_help_screen_lists_every_command():
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    for command in ("analyze", "execute", "status", "history", "plan", "backtest", "auth"):
        assert command in result.output


def test_plan_show_prints_the_stored_plan(tmp_path, monkeypatch):
    write_env(monkeypatch)
    config_path = write_config(tmp_path)
    PlanStore(tmp_path / "trade_plans").save(make_plan())

    result = CliRunner().invoke(
        cli,
        ["--config", str(config_path), "--data-dir", str(tmp_path), "plan", "show", "--date", "2026-09-24"],
    )

    assert result.exit_code == 0
    assert "RELIANCE" in result.output
    assert "2855" in result.output


def test_plan_show_reports_a_missing_plan_without_a_traceback(tmp_path, monkeypatch):
    write_env(monkeypatch)
    config_path = write_config(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["--config", str(config_path), "--data-dir", str(tmp_path), "plan", "show", "--date", "2026-09-24"],
    )

    assert result.exit_code != 0
    assert "no trade plan" in result.output.lower()
    assert "Traceback" not in result.output


def test_plan_show_reports_a_corrupt_plan_without_a_traceback(tmp_path, monkeypatch):
    write_env(monkeypatch)
    config_path = write_config(tmp_path)
    plan_dir = tmp_path / "trade_plans"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "2026-09-24.json").write_text("{broken")

    result = CliRunner().invoke(
        cli,
        ["--config", str(config_path), "--data-dir", str(tmp_path), "plan", "show", "--date", "2026-09-24"],
    )

    assert result.exit_code != 0
    assert "could not be parsed" in result.output
    assert "Traceback" not in result.output


def test_history_prints_recorded_trades(tmp_path, monkeypatch):
    write_env(monkeypatch)
    config_path = write_config(tmp_path)
    database = Database(tmp_path / "tradingbot.db")
    database.initialise()
    database.record_trade(make_trade())
    database.close()

    result = CliRunner().invoke(
        cli, ["--config", str(config_path), "--data-dir", str(tmp_path), "history"]
    )

    assert result.exit_code == 0
    assert "RELIANCE" in result.output
    assert "560" in result.output


def test_history_on_an_empty_database_says_so(tmp_path, monkeypatch):
    write_env(monkeypatch)
    config_path = write_config(tmp_path)

    result = CliRunner().invoke(
        cli, ["--config", str(config_path), "--data-dir", str(tmp_path), "history"]
    )

    assert result.exit_code == 0
    assert "no trades" in result.output.lower()


def test_status_reports_the_configured_mode(tmp_path, monkeypatch):
    write_env(monkeypatch)
    config_path = write_config(tmp_path)

    result = CliRunner().invoke(
        cli, ["--config", str(config_path), "--data-dir", str(tmp_path), "status"]
    )

    assert result.exit_code == 0
    assert "paper" in result.output.lower()


def test_a_missing_config_file_is_reported_cleanly(tmp_path, monkeypatch):
    write_env(monkeypatch)

    result = CliRunner().invoke(
        cli, ["--config", str(tmp_path / "nope.toml"), "--data-dir", str(tmp_path), "status"]
    )

    assert result.exit_code != 0
    assert "not found" in result.output
    assert "Traceback" not in result.output


def test_a_missing_api_key_is_reported_cleanly(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("KITE_API_KEY", "kite-key")
    monkeypatch.setenv("KITE_API_SECRET", "kite-secret")
    config_path = write_config(tmp_path)

    result = CliRunner().invoke(
        cli, ["--config", str(config_path), "--data-dir", str(tmp_path), "status"]
    )

    assert result.exit_code != 0
    assert "ANTHROPIC_API_KEY" in result.output
    assert "Traceback" not in result.output


def test_analyze_refuses_a_non_trading_day_without_a_traceback(tmp_path, monkeypatch):
    write_env(monkeypatch)
    config_path = write_config(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["--config", str(config_path), "--data-dir", str(tmp_path), "analyze", "--date", "2026-09-26"],
    )

    assert result.exit_code != 0
    assert "not an NSE trading day" in result.output
    assert "Traceback" not in result.output


def test_execute_without_a_plan_fails_cleanly(tmp_path, monkeypatch):
    write_env(monkeypatch)
    config_path = write_config(tmp_path)

    result = CliRunner().invoke(
        cli, ["--config", str(config_path), "--data-dir", str(tmp_path), "execute", "--paper", "--once"]
    )

    assert result.exit_code != 0
    assert "no trade plan" in result.output.lower()
    assert "Traceback" not in result.output
```

- [ ] **Step 2: Run the CLI tests to verify they fail**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingbot.cli'`

- [ ] **Step 3: Implement the CLI**

Create `tradingbot/cli.py`:

```python
"""Command line entry point. Every command is a thin wrapper over the agents."""

from __future__ import annotations

import asyncio
import logging
import sys
import time as time_module
from datetime import date, datetime
from pathlib import Path

import click

from tradingbot.core.broker import BrokerInterface
from tradingbot.core.config import Config, ConfigError, load_config
from tradingbot.core.database import Database
from tradingbot.core.llm.anthropic_provider import build_provider
from tradingbot.core.models import Mode, now_ist
from tradingbot.core.plan_store import PlanCorruptError, PlanNotFoundError, PlanStore
from tradingbot.core.risk_manager import RiskManager
from tradingbot.executor.executor import Executor
from tradingbot.paper.virtual_broker import VirtualBroker
from tradingbot.scanner.calendar import NotATradingDayError, next_trading_day
from tradingbot.scanner.data_fetcher import DataFetcher
from tradingbot.scanner.market_analyzer import MarketAnalyzer
from tradingbot.scanner.market_context import MarketContextFetcher
from tradingbot.scanner.scanner import Scanner
from tradingbot.strategy.backtester import Backtester
from tradingbot.strategy.plan_generator import PlanGenerator
from tradingbot.strategy.strategies import STRATEGY_REGISTRY
from tradingbot.strategy.strategy_selector import StrategySelector

TICK_SECONDS = 5


def _fail(message: str) -> None:
    """Print a readable error and exit non-zero. Never show a traceback."""
    raise click.ClickException(message)


def build_risk_manager(config: Config) -> RiskManager:
    return RiskManager(
        config.risk,
        config.strategy,
        capital=config.general.capital,
        plan_max_age_hours=config.execution.plan_max_age_hours,
        max_entry_price_drift_pct=config.execution.max_entry_price_drift_pct,
    )


def build_analysis_stack(config: Config, plan_dir: Path, log_dir: Path) -> PlanGenerator:
    provider = build_provider(config.llm, config.secrets, log_dir=log_dir / "llm")
    fetcher = DataFetcher()
    scanner = Scanner(
        fetcher=fetcher,
        context_fetcher=MarketContextFetcher(),
        analyzer=MarketAnalyzer(provider, config.scanner),
        config=config.scanner,
    )
    return PlanGenerator(
        scanner=scanner,
        fetcher=fetcher,
        selector=StrategySelector(provider, config.strategy),
        risk_manager=build_risk_manager(config),
        plan_store=PlanStore(plan_dir),
        strategy_config=config.strategy,
        capital=config.general.capital,
    )


def build_broker(config: Config, mode: Mode) -> BrokerInterface:
    if mode is Mode.PAPER:
        fetcher = DataFetcher()

        def price_feed(symbol: str) -> float:
            candles = fetcher.fetch_candles(symbol, days=1, interval="5m")
            return float(candles["close"].iloc[-1])

        return VirtualBroker(config.paper, price_feed=price_feed)

    from tradingbot.core.kite_client import KiteClient

    token_path = Path.home() / ".tradingbot" / "kite_token"
    if not token_path.exists():
        _fail("no Kite access token found. Run `tradingbot auth` first.")

    return KiteClient(
        api_key=config.secrets.kite_api_key,
        api_secret=config.secrets.kite_api_secret,
        access_token=token_path.read_text().strip(),
    )


@click.group()
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=Path("config.toml"))
@click.option("--data-dir", type=click.Path(path_type=Path), default=Path("."))
@click.pass_context
def cli(ctx: click.Context, config_path: Path, data_dir: Path) -> None:
    """Automated intraday equity trading bot for the Indian market."""
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        _fail(str(exc))

    logging.basicConfig(
        level=getattr(logging, config.general.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ctx.obj = {
        "config": config,
        "data_dir": Path(data_dir),
        "plan_dir": Path(data_dir) / "trade_plans",
        "log_dir": Path(data_dir) / "logs",
        "db_path": Path(data_dir) / "tradingbot.db",
    }


@cli.command()
@click.option("--date", "target", default=None, help="Trade date as YYYY-MM-DD. Defaults to the next session.")
@click.pass_obj
def analyze(obj: dict, target: str | None) -> None:
    """Scan the market and write a trade plan."""
    config: Config = obj["config"]
    trade_date = date.fromisoformat(target) if target else next_trading_day(now_ist().date())

    generator = build_analysis_stack(config, obj["plan_dir"], obj["log_dir"])

    try:
        plan = asyncio.run(generator.generate(trade_date))
    except NotATradingDayError as exc:
        _fail(str(exc))
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean CLI error
        _fail(f"analysis failed: {exc}")

    database = Database(obj["db_path"])
    database.initialise()
    database.save_plan_snapshot(plan)
    database.close()

    click.echo(f"Trade plan for {plan.trade_date} ({len(plan.legs)} legs)")
    click.echo(f"  Regime: {plan.market_regime.value} | {plan.market_summary}")
    for leg in plan.legs:
        click.echo(
            f"  {leg.symbol} {leg.direction.value.upper()} x{leg.quantity} "
            f"@ {leg.entry_price:.2f} | SL {leg.stop_loss:.2f} | "
            f"T1 {leg.target_1:.2f} | T2 {leg.target_2:.2f} | "
            f"R:R {leg.reward_risk:.2f} | confidence {leg.confidence:.2f}"
        )
        click.echo(f"    {leg.reasoning}")
    if not plan.legs:
        click.echo("  No setup met the risk criteria. No trading tomorrow.")


@cli.command()
@click.option("--paper", is_flag=True, help="Force paper mode regardless of config.")
@click.option("--date", "target", default=None, help="Plan date to execute. Defaults to the latest plan.")
@click.option("--once", is_flag=True, help="Run a single tick and exit. Used by tests and smoke checks.")
@click.pass_obj
def execute(obj: dict, paper: bool, target: str | None, once: bool) -> None:
    """Execute the trade plan during market hours."""
    config: Config = obj["config"]
    mode = Mode.PAPER if paper else config.general.mode

    store = PlanStore(obj["plan_dir"])
    try:
        plan = store.load(target) if target else store.load_latest()
    except (PlanNotFoundError, PlanCorruptError) as exc:
        _fail(str(exc))

    database = Database(obj["db_path"])
    database.initialise()

    executor = Executor(
        broker=build_broker(config, mode),
        plan=plan,
        risk_manager=build_risk_manager(config),
        database=database,
        execution_config=config.execution,
        mode=mode,
    )

    click.echo(f"Executing {plan.trade_date} in {mode.value} mode ({len(plan.legs)} legs)")
    executor.start()

    if executor.blocked:
        database.close()
        _fail("plan failed pre-execution checks; see the log above")

    try:
        while not executor.is_done:
            executor.tick()
            if once:
                break
            time_module.sleep(TICK_SECONDS)
    except KeyboardInterrupt:
        click.echo("\nInterrupted. Open positions are left untouched — square off manually if needed.")
    finally:
        database.close()

    click.echo("Session complete.")


@cli.command()
@click.pass_obj
def status(obj: dict) -> None:
    """Show today's mode, positions, and realised P&L."""
    config: Config = obj["config"]
    today = now_ist().date().isoformat()

    database = Database(obj["db_path"])
    database.initialise()
    realised = database.realised_pnl_for_date(today)
    trades = database.trades_for_date(today)
    database.close()

    click.echo(f"Mode: {config.general.mode.value}")
    click.echo(f"Capital: {config.general.capital:,.0f}")
    click.echo(f"Date: {today}")
    click.echo(f"Trades closed today: {len(trades)}")
    click.echo(f"Realised P&L: {realised:,.2f}")


@cli.command()
@click.option("--days", default=30, help="How far back to look.")
@click.option("--detailed", is_flag=True, help="Print every trade rather than a summary.")
@click.pass_obj
def history(obj: dict, days: int, detailed: bool) -> None:
    """Show recent trading performance."""
    database = Database(obj["db_path"])
    database.initialise()
    trades = database.recent_trades(days=days, today=now_ist().date())
    database.close()

    if not trades:
        click.echo(f"No trades in the last {days} days.")
        return

    wins = [trade for trade in trades if trade.pnl > 0]
    total = sum(trade.pnl for trade in trades)

    click.echo(f"Last {days} days: {len(trades)} trades")
    click.echo(f"  Win rate: {len(wins) / len(trades) * 100:.1f}%")
    click.echo(f"  Total P&L: {total:,.2f}")
    click.echo(f"  Average P&L: {total / len(trades):,.2f}")

    if detailed:
        click.echo("")
        for trade in trades:
            click.echo(
                f"  {trade.trade_date} {trade.symbol:<12} {trade.direction.value:<5} "
                f"x{trade.quantity:<5} {trade.entry_price:>9.2f} -> {trade.exit_price:>9.2f} "
                f"{trade.pnl:>10.2f}  {trade.exit_reason}"
            )


@cli.group("plan")
def plan_group() -> None:
    """Inspect stored trade plans."""


@plan_group.command("show")
@click.option("--date", "target", default=None, help="Plan date. Defaults to the latest plan.")
@click.pass_obj
def plan_show(obj: dict, target: str | None) -> None:
    """Print a stored trade plan."""
    store = PlanStore(obj["plan_dir"])
    try:
        plan = store.load(target) if target else store.load_latest()
    except (PlanNotFoundError, PlanCorruptError) as exc:
        _fail(str(exc))

    click.echo(f"Trade plan {plan.trade_date}")
    click.echo(f"  Generated: {plan.generated_at.isoformat()}")
    click.echo(f"  Capital: {plan.capital:,.0f}")
    click.echo(f"  Regime: {plan.market_regime.value}")
    click.echo(f"  Summary: {plan.market_summary}")
    for leg in plan.legs:
        click.echo("")
        click.echo(f"  {leg.symbol} ({leg.strategy.value}, {leg.direction.value})")
        click.echo(f"    Entry:   {leg.entry_price:.2f} ({leg.entry_type.value})")
        click.echo(f"    Stop:    {leg.stop_loss:.2f}")
        click.echo(f"    Targets: {leg.target_1:.2f} / {leg.target_2:.2f}")
        click.echo(f"    Size:    {leg.quantity} shares, risking {leg.risk_amount:,.0f}")
        click.echo(f"    Window:  {leg.entry_window_start}-{leg.entry_window_end}, give up at {leg.max_entry_wait}")
        click.echo(f"    Why:     {leg.reasoning}")
    if not plan.legs:
        click.echo("  (no legs)")


@cli.command()
@click.option("--strategy", "strategy_name", default="all", help="Strategy name, or 'all'.")
@click.option("--symbol", default="RELIANCE", help="Symbol to backtest.")
@click.option("--days", default=90, help="Days of history to replay.")
@click.pass_obj
def backtest(obj: dict, strategy_name: str, symbol: str, days: int) -> None:
    """Replay one or every strategy over recent history."""
    config: Config = obj["config"]
    fetcher = DataFetcher()

    try:
        candles = fetcher.fetch_candles(symbol, days=days, interval="15m")
    except Exception as exc:  # noqa: BLE001
        _fail(f"could not fetch candles for {symbol}: {exc}")

    runner = Backtester()

    if strategy_name == "all":
        results = runner.run_all(symbol, candles)
    else:
        matched = [
            strategy
            for name, strategy in STRATEGY_REGISTRY.items()
            if name.value == strategy_name
        ]
        if not matched:
            _fail(
                f"unknown strategy {strategy_name!r}. "
                f"Choose from: {', '.join(name.value for name in STRATEGY_REGISTRY)}, or 'all'."
            )
        results = [runner.run(symbol, candles, matched[0])]

    click.echo(f"Backtest {symbol} over {days} days ({config.strategy.candle_interval} candles)")
    for result in results:
        click.echo(
            f"  {result.strategy.value:<16} {result.trades:>4} trades  "
            f"{result.win_rate * 100:>5.1f}% wins  avg R:R {result.avg_reward_risk:.2f}"
        )


@cli.command()
@click.pass_obj
def auth(obj: dict) -> None:
    """Complete the Kite Connect login and store the access token."""
    config: Config = obj["config"]
    from tradingbot.core.kite_client import KiteClient

    client = KiteClient(config.secrets.kite_api_key, config.secrets.kite_api_secret)
    click.echo("Open this URL, log in, then copy the request_token from the redirect URL:")
    click.echo(f"  {client.login_url()}")
    request_token = click.prompt("request_token").strip()

    try:
        access_token = client.complete_login(request_token)
    except Exception as exc:  # noqa: BLE001
        _fail(f"login failed: {exc}")

    token_path = Path.home() / ".tradingbot" / "kite_token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(access_token)
    token_path.chmod(0o600)
    click.echo(f"Access token saved to {token_path}. It expires at the next market open.")
```

Create `tradingbot/__main__.py`:

```python
from tradingbot.cli import cli

if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: Run the CLI tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: PASS — 11 tests.

- [ ] **Step 5: Write the README**

Create `README.md`:

```markdown
# Intraday Trading Bot

Automated intraday equity trading for the Indian market (NSE). Claude picks the
setups before the open; a deterministic executor follows the plan during the session.

## How it works

1. `analyze` scans the NSE universe, filters it down to liquid and tradable names,
   asks Claude which are worth trading tomorrow, designs setups from the technicals
   and recent backtest results, sizes them against your risk limits, and writes
   `trade_plans/YYYY-MM-DD.json`.
2. `execute` reads that plan and trades it. No LLM runs during market hours.

Analysis and execution are fully decoupled — run the analysis the night before or
the morning of, it makes no difference to the executor.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env    # then fill in your keys
```

Edit `config.toml` to set your capital and risk limits. It starts in paper mode.

## Usage

```bash
tradingbot analyze                 # write tomorrow's plan
tradingbot plan show               # read it back before the open
tradingbot execute --paper         # trade it in simulation
tradingbot history --detailed      # review what happened
tradingbot backtest --symbol TCS --days 90
```

Going live is a deliberate act: run `tradingbot auth` to authorise Kite Connect,
then change `mode = "live"` in `config.toml`.

## Before you risk real money

Paper trade for at least 30 sessions and check that win rate is above 50%, average
reward:risk is above 1.5, and max drawdown stayed under 5% of capital. The bot will
not promote itself to live trading.

## Risk controls

- 1% of capital risked per trade, 2% daily loss kill switch
- At most 2 concurrent positions, at most 50% of capital deployed
- Every position is squared off at 15:10, no exceptions
- Restarting mid-session adopts open positions instead of double-entering

## Testing

```bash
pytest tests/ -v
```
```

- [ ] **Step 6: Run the full test suite to verify everything passes**

Run: `pytest tests/ -v`
Expected: PASS — 255 tests.

- [ ] **Step 7: Verify the CLI actually runs end to end**

Run: `python -m tradingbot --help`
Expected: the command list prints with no traceback.

Run: `python -m tradingbot backtest --symbol RELIANCE --days 30`
Expected: one line per strategy with trade counts and win rates. This makes a real
network call to fetch candles, so it needs connectivity.

- [ ] **Step 8: Commit**

```bash
git add tradingbot/cli.py tradingbot/__main__.py README.md tests/test_cli.py
git commit -m "feat: add CLI with analyze, execute, backtest, and history commands"
```

---

## Done

At this point the system is complete and every task's tests pass. The natural next
move is 30 sessions of paper trading, then reviewing `tradingbot history --detailed`
against the graduation criteria in the spec before switching `mode` to `live`.
