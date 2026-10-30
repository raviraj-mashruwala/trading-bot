"""Tests for new config sections: screening, backtest, kite."""

import pytest

from tradingbot.core.config import ConfigError, load_config

# Full TOML including all new sections
FULL_CONFIG = """
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

# Minimal TOML without new sections — backward compat
MINIMAL_CONFIG = """
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
def full_config_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(FULL_CONFIG)
    return path


@pytest.fixture()
def minimal_config_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(MINIMAL_CONFIG)
    return path


def test_screening_config_loaded(full_config_file, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("KITE_API_KEY", "test-kite")
    monkeypatch.setenv("KITE_API_SECRET", "test-secret")

    cfg = load_config(full_config_file)

    assert cfg.screening.min_volume == 500000
    assert cfg.screening.max_per_sector == 3
    assert cfg.screening.volume_surge_weight == 15
    assert cfg.screening.relative_strength_weight == 15
    assert cfg.screening.atr_expansion_weight == 10
    assert cfg.screening.price_structure_weight == 15
    assert cfg.screening.delivery_pct_weight == 10
    assert cfg.screening.sector_momentum_weight == 10
    assert cfg.screening.gap_analysis_weight == 10
    assert cfg.screening.candlestick_pattern_weight == 10
    assert cfg.screening.volume_profile_weight == 5
    assert cfg.screening.min_market_cap_cr == 1000
    assert cfg.screening.min_trading_days == 10


def test_backtest_config_loaded(full_config_file, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("KITE_API_KEY", "test-kite")
    monkeypatch.setenv("KITE_API_SECRET", "test-secret")

    cfg = load_config(full_config_file)

    assert cfg.backtest.lookback_days == 365
    assert cfg.backtest.walk_forward_windows == 10
    assert cfg.backtest.train_pct == 70
    assert cfg.backtest.monte_carlo_simulations == 10000
    assert cfg.backtest.min_trades == 30
    assert cfg.backtest.min_win_rate == 0.45
    assert cfg.backtest.min_profit_factor == 1.5
    assert cfg.backtest.min_expectancy_r == 0.3
    assert cfg.backtest.max_oos_degradation == 0.3
    assert cfg.backtest.max_risk_of_ruin == 0.05
    assert cfg.backtest.max_consecutive_losses == 8


def test_kite_config_loaded(full_config_file, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("KITE_API_KEY", "test-kite")
    monkeypatch.setenv("KITE_API_SECRET", "test-secret")

    cfg = load_config(full_config_file)

    assert cfg.kite.api_key_env == "KITE_API_KEY"
    assert cfg.kite.api_secret_env == "KITE_API_SECRET"
    assert cfg.kite.sync_hour == 6
    assert cfg.kite.sync_minute == 0
    assert cfg.kite.rate_limit_per_sec == 3


def test_execution_new_fields(full_config_file, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("KITE_API_KEY", "test-kite")
    monkeypatch.setenv("KITE_API_SECRET", "test-secret")

    cfg = load_config(full_config_file)

    assert cfg.execution.mode == "paper"
    assert cfg.execution.shadow_fraction == 0.1


def test_backward_compat_no_new_sections(minimal_config_file, monkeypatch):
    """Config without screening/backtest/kite sections still loads with defaults."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("KITE_API_KEY", "test-kite")
    monkeypatch.setenv("KITE_API_SECRET", "test-secret")

    cfg = load_config(minimal_config_file)

    # Defaults populated
    assert cfg.screening.min_volume == 500000
    assert cfg.screening.max_per_sector == 3
    assert cfg.backtest.lookback_days == 365
    assert cfg.backtest.monte_carlo_simulations == 10000
    assert cfg.kite.api_key_env == "KITE_API_KEY"
    assert cfg.kite.rate_limit_per_sec == 3

    # execution defaults for new fields
    assert cfg.execution.mode == "paper"
    assert cfg.execution.shadow_fraction == 0.1


def test_screening_config_frozen(full_config_file, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("KITE_API_KEY", "test-kite")
    monkeypatch.setenv("KITE_API_SECRET", "test-secret")

    cfg = load_config(full_config_file)

    with pytest.raises(AttributeError):
        cfg.screening.min_volume = 999  # type: ignore[misc]


def test_backtest_config_frozen(full_config_file, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("KITE_API_KEY", "test-kite")
    monkeypatch.setenv("KITE_API_SECRET", "test-secret")

    cfg = load_config(full_config_file)

    with pytest.raises(AttributeError):
        cfg.backtest.lookback_days = 999  # type: ignore[misc]


def test_kite_config_frozen(full_config_file, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("KITE_API_KEY", "test-kite")
    monkeypatch.setenv("KITE_API_SECRET", "test-secret")

    cfg = load_config(full_config_file)

    with pytest.raises(AttributeError):
        cfg.kite.rate_limit_per_sec = 999  # type: ignore[misc]
