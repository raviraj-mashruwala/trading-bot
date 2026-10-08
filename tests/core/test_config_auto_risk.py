"""Tests for auto-risk integration in load_config."""

import textwrap
from pathlib import Path

import pytest

from tradingbot.core.config import ConfigError, load_config


MINIMAL_TOML = textwrap.dedent("""\
    [general]
    mode = "paper"
    capital = 20000
    log_level = "INFO"

    [strategy]
    backtest_days = 30
    candle_interval = "15minute"
    min_confidence = 0.5
    min_reward_risk = 1.5
    max_trades_per_day = 2

    [execution]
    entry_slippage_pct = 0.05
    square_off_time = "15:10"
    connection_timeout_sec = 30
    heartbeat_interval_sec = 60
    plan_max_age_hours = 14
    max_entry_price_drift_pct = 2.0

    [llm]
    provider = "anthropic"
    model = "claude-sonnet-4-20250514"
    timeout_sec = 60
    max_retries = 1

    [paper]
    slippage_pct = 0.05
    initial_capital = 20000
""")


@pytest.fixture()
def env_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("KITE_API_KEY", "test-key")
    monkeypatch.setenv("KITE_API_SECRET", "test-secret")


def test_missing_risk_section_auto_derives_from_capital(tmp_path, env_secrets):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(MINIMAL_TOML)

    config = load_config(cfg_path)

    assert config.risk.max_risk_per_trade_pct == 0.015
    assert config.risk.max_daily_loss_pct == 0.03
    assert config.risk.max_capital_deployed_pct == 0.80
    assert config.risk.max_concurrent_positions == 3


def test_partial_risk_section_merges_with_auto(tmp_path, env_secrets):
    toml_with_partial_risk = MINIMAL_TOML + textwrap.dedent("""\

        [risk]
        max_concurrent_positions = 3
    """)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(toml_with_partial_risk)

    config = load_config(cfg_path)

    assert config.risk.max_concurrent_positions == 3
    assert config.risk.max_risk_per_trade_pct == 0.015


def test_full_risk_section_overrides_all_auto(tmp_path, env_secrets):
    toml_with_full_risk = MINIMAL_TOML + textwrap.dedent("""\

        [risk]
        max_risk_per_trade_pct = 0.005
        max_daily_loss_pct = 0.01
        max_capital_deployed_pct = 0.30
        max_concurrent_positions = 4
    """)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(toml_with_full_risk)

    config = load_config(cfg_path)

    assert config.risk.max_risk_per_trade_pct == 0.005
    assert config.risk.max_daily_loss_pct == 0.01
    assert config.risk.max_capital_deployed_pct == 0.30
    assert config.risk.max_concurrent_positions == 4


def test_large_capital_auto_derives_conservative_params(tmp_path, env_secrets):
    large_toml = MINIMAL_TOML.replace("capital = 20000", "capital = 2000000")
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(large_toml)

    config = load_config(cfg_path)

    assert config.risk.max_risk_per_trade_pct == 0.0075
    assert config.risk.max_concurrent_positions == 3
