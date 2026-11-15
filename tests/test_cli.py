import json
from datetime import date, datetime, time, timedelta

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
        market_regime=MarketRegime.TRENDING_UP,
        market_summary="Nifty bullish.",
        legs=[leg],
    )


def make_trade() -> ExecutedTrade:
    # Recent, so the default history window never ages it out.
    return ExecutedTrade(
        trade_date=(date.today() - timedelta(days=1)).isoformat(),
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
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("KITE_API_KEY", "kite-key")
    monkeypatch.setenv("KITE_API_SECRET", "kite-secret")
    config_path = write_config(tmp_path)

    result = CliRunner().invoke(
        cli, ["--config", str(config_path), "--data-dir", str(tmp_path), "status"]
    )

    assert result.exit_code != 0
    assert "ANTHROPIC_API_KEY" in result.output
    assert "Traceback" not in result.output


def test_analyze_prints_retirement_message(tmp_path, monkeypatch):
    write_env(monkeypatch)
    config_path = write_config(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["--config", str(config_path), "--data-dir", str(tmp_path), "analyze"],
    )

    assert result.exit_code == 0
    assert "retired" in result.output.lower()


def test_execute_without_a_plan_fails_cleanly(tmp_path, monkeypatch):
    write_env(monkeypatch)
    config_path = write_config(tmp_path)

    result = CliRunner().invoke(
        cli, ["--config", str(config_path), "--data-dir", str(tmp_path), "execute", "--paper", "--once"]
    )

    assert result.exit_code != 0
    assert "no trade plan" in result.output.lower()
    assert "Traceback" not in result.output


def test_serve_command_is_listed_in_help():
    result = CliRunner().invoke(cli, ["--help"])
    assert "serve" in result.output


def test_serve_help_shows_port_option():
    result = CliRunner().invoke(cli, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.output
    assert "--reload" in result.output
