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
    openai_api_key: str = field(default="", repr=False)

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
            openai_api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
        ),
    )
