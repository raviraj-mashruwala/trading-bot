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
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
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
