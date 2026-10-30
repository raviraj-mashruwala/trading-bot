"""Core data structures shared by every agent in the system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
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
    GAP_AND_GO = "gap_and_go"
    PIVOT_POINT = "pivot_point"
    RELATIVE_STRENGTH = "relative_strength"
    BOLLINGER_SQUEEZE = "bollinger_squeeze"
    SUPPLY_DEMAND = "supply_demand"


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


# Backward-compat mapping: old regime string values -> new enum values.
_REGIME_COMPAT: dict[str, str] = {
    "trending": "trending_up",
    "ranging": "range_bound",
    "low_vol": "low_vol_squeeze",
}


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
        regime_val = raw["regime"]
        regime_val = _REGIME_COMPAT.get(regime_val, regime_val)
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
            regime=MarketRegime(regime_val),
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
    pivot_r1: float = 0.0
    pivot_s1: float = 0.0
    last_session_high: float = 0.0
    last_session_low: float = 0.0
    last_session_close: float = 0.0
    high_5d: float = 0.0
    low_5d: float = 0.0
    high_20d: float = 0.0
    low_20d: float = 0.0

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
            "adx_14": self.adx_14,
            "supertrend": self.supertrend,
            "supertrend_direction": self.supertrend_direction,
            "bb_bandwidth": self.bb_bandwidth,
            "vwap_upper_1": self.vwap_upper_1,
            "vwap_lower_1": self.vwap_lower_1,
            "poc": self.poc,
            "vah": self.vah,
            "val": self.val,
            "ema_9": self.ema_9,
            "sma_9": self.sma_9,
            "pivot_r1": self.pivot_r1,
            "pivot_s1": self.pivot_s1,
            "last_session_high": self.last_session_high,
            "last_session_low": self.last_session_low,
            "last_session_close": self.last_session_close,
            "high_5d": self.high_5d,
            "low_5d": self.low_5d,
            "high_20d": self.high_20d,
            "low_20d": self.low_20d,
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
    setup_id: int | None = None

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
            setup_id=self.setup_id,
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
    setup_id: int | None = None

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
            "setup_id": self.setup_id,
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
            setup_id=raw.get("setup_id"),
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
        regime_val = raw["market_regime"]
        regime_val = _REGIME_COMPAT.get(regime_val, regime_val)
        return cls(
            schema_version=int(raw.get("schema_version", PLAN_SCHEMA_VERSION)),
            trade_date=raw["trade_date"],
            generated_at=datetime.fromisoformat(raw["generated_at"]),
            capital=float(raw["capital"]),
            max_risk_per_trade_pct=float(raw["max_risk_per_trade_pct"]),
            max_daily_loss_pct=float(raw["max_daily_loss_pct"]),
            market_regime=MarketRegime(regime_val),
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
    setup_id: int | None = None


# ---------------------------------------------------------------------------
# Post-trade review models
# ---------------------------------------------------------------------------

import re as _re


def _parse_invalidation_price(condition: str) -> float | None:
    """Extract the first numeric price from an invalidation condition string."""
    match = _re.search(r"(\d+(?:\.\d+)?)", condition)
    return float(match.group(1)) if match else None


@dataclass(frozen=True)
class TradeScorecard:
    """Per-trade comparison of predicted setup vs actual outcome."""

    trade_id: int
    setup_id: int | None
    symbol: str
    strategy: str
    direction: str
    trade_date: str

    predicted_entry: float
    predicted_stop: float
    predicted_target_1: float
    predicted_target_2: float | None
    confidence: float
    confluence_count: int
    regime_at_generation: str
    thesis: str
    invalidation_condition: str
    bear_case: str

    actual_entry: float
    actual_exit: float
    pnl: float
    exit_reason: str
    quantity: int

    @property
    def r_multiple(self) -> float:
        risk_per_share = abs(self.predicted_entry - self.predicted_stop)
        if risk_per_share == 0 or self.quantity == 0:
            return 0.0
        return self.pnl / (risk_per_share * self.quantity)

    @property
    def hit_target(self) -> bool:
        if self.direction == "long":
            return self.actual_exit >= self.predicted_target_1
        return self.actual_exit <= self.predicted_target_1

    @property
    def invalidation_fired(self) -> bool:
        price = _parse_invalidation_price(self.invalidation_condition)
        if price is None:
            return False
        if self.direction == "long":
            return self.actual_exit <= price
        return self.actual_exit >= price

    @property
    def entry_slippage(self) -> float:
        return self.actual_entry - self.predicted_entry

    @property
    def predicted_rr(self) -> float:
        risk = abs(self.predicted_entry - self.predicted_stop)
        if risk == 0:
            return 0.0
        return abs(self.predicted_target_1 - self.predicted_entry) / risk

    @property
    def actual_rr(self) -> float:
        risk = abs(self.predicted_entry - self.predicted_stop)
        if risk == 0 or self.quantity == 0:
            return 0.0
        return self.pnl / (risk * self.quantity)


@dataclass(frozen=True)
class StrategyStats:
    trades: int
    win_rate: float
    avg_r: float
    total_pnl: float


@dataclass(frozen=True)
class PerformanceStats:
    period_days: int
    total_trades: int
    win_rate: float
    avg_r_multiple: float
    total_pnl: float
    by_strategy: dict[str, StrategyStats]
    by_regime: dict[str, StrategyStats]
    by_strategy_regime: dict[str, StrategyStats]
    confluence_buckets: dict[str, float]
    confidence_calibration: dict[str, float]


# ---------------------------------------------------------------------------
# Extended models for analysis pipeline redesign
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoredStock:
    """A stock with composite screening score and factor breakdown."""

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
    """Metadata for one full pipeline execution."""

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
    """Detailed backtest statistics for one symbol+strategy pair."""

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
    regime_performance: dict[str, dict] = field(default_factory=dict)


@dataclass(frozen=True)
class MonteCarloResult:
    """Monte Carlo simulation summary for risk-of-ruin analysis."""

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
    """Pass/fail verdict from the quality gate with per-criterion flags."""

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
