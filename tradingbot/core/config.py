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


@dataclass(frozen=True)
class ExecutionConfig:
    entry_slippage_pct: float
    square_off_time: time
    connection_timeout_sec: int
    heartbeat_interval_sec: int
    plan_max_age_hours: float
    max_entry_price_drift_pct: float
    mode: str = "paper"
    shadow_fraction: float = 0.1


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    timeout_sec: int
    max_retries: int
    base_url: str = ""


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
    screening: ScreeningConfig
    backtest: BacktestConfig
    kite: KiteConfig


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

    strategy_raw = _section(data, "strategy")
    risk_raw = _section(data, "risk")
    execution_raw = _section(data, "execution")
    llm_raw = _section(data, "llm")
    paper_raw = _section(data, "paper")

    # Optional sections — backward compatible with defaults
    scanner_raw = data.get("scanner", {})
    screening_raw = data.get("screening", {})
    backtest_raw = data.get("backtest", {})
    kite_raw = data.get("kite", {})

    return Config(
        general=GeneralConfig(
            mode=mode,
            capital=float(general_raw["capital"]),
            log_level=general_raw["log_level"],
        ),
        scanner=ScannerConfig(
            min_volume=int(scanner_raw.get("min_volume", 500000)),
            min_price=float(scanner_raw.get("min_price", 50)),
            max_price=float(scanner_raw.get("max_price", 5000)),
            min_market_cap_cr=float(scanner_raw.get("min_market_cap_cr", 5000)),
            min_atr_pct=float(scanner_raw.get("min_atr_pct", 0.5)),
            max_stocks_to_llm=int(scanner_raw.get("max_stocks_to_llm", 100)),
            llm_pick_count=int(scanner_raw.get("llm_pick_count", 15)),
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
            mode=execution_raw.get("mode", "paper"),
            shadow_fraction=float(execution_raw.get("shadow_fraction", 0.1)),
        ),
        llm=LLMConfig(
            provider=llm_raw["provider"],
            model=llm_raw["model"],
            timeout_sec=int(llm_raw["timeout_sec"]),
            max_retries=int(llm_raw["max_retries"]),
            base_url=llm_raw.get("base_url", ""),
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
        screening=ScreeningConfig(
            min_volume=int(screening_raw.get("min_volume", 500000)),
            min_price=float(screening_raw.get("min_price", 50)),
            max_price=float(screening_raw.get("max_price", 5000)),
            min_market_cap_cr=float(screening_raw.get("min_market_cap_cr", 1000)),
            min_atr_pct=float(screening_raw.get("min_atr_pct", 0.5)),
            min_trading_days=int(screening_raw.get("min_trading_days", 10)),
            max_per_sector=int(screening_raw.get("max_per_sector", 3)),
            volume_surge_weight=int(screening_raw.get("volume_surge_weight", 15)),
            relative_strength_weight=int(screening_raw.get("relative_strength_weight", 15)),
            atr_expansion_weight=int(screening_raw.get("atr_expansion_weight", 10)),
            price_structure_weight=int(screening_raw.get("price_structure_weight", 15)),
            delivery_pct_weight=int(screening_raw.get("delivery_pct_weight", 10)),
            sector_momentum_weight=int(screening_raw.get("sector_momentum_weight", 10)),
            gap_analysis_weight=int(screening_raw.get("gap_analysis_weight", 10)),
            candlestick_pattern_weight=int(screening_raw.get("candlestick_pattern_weight", 10)),
            volume_profile_weight=int(screening_raw.get("volume_profile_weight", 5)),
        ),
        backtest=BacktestConfig(
            lookback_days=int(backtest_raw.get("lookback_days", 365)),
            walk_forward_windows=int(backtest_raw.get("walk_forward_windows", 10)),
            train_pct=int(backtest_raw.get("train_pct", 70)),
            monte_carlo_simulations=int(backtest_raw.get("monte_carlo_simulations", 10000)),
            min_trades=int(backtest_raw.get("min_trades", 30)),
            min_win_rate=float(backtest_raw.get("min_win_rate", 0.45)),
            min_profit_factor=float(backtest_raw.get("min_profit_factor", 1.5)),
            min_expectancy_r=float(backtest_raw.get("min_expectancy_r", 0.3)),
            max_oos_degradation=float(backtest_raw.get("max_oos_degradation", 0.3)),
            max_risk_of_ruin=float(backtest_raw.get("max_risk_of_ruin", 0.05)),
            max_consecutive_losses=int(backtest_raw.get("max_consecutive_losses", 8)),
        ),
        kite=KiteConfig(
            api_key_env=kite_raw.get("api_key_env", "KITE_API_KEY"),
            api_secret_env=kite_raw.get("api_secret_env", "KITE_API_SECRET"),
            sync_hour=int(kite_raw.get("sync_hour", 6)),
            sync_minute=int(kite_raw.get("sync_minute", 0)),
            rate_limit_per_sec=int(kite_raw.get("rate_limit_per_sec", 3)),
        ),
    )
