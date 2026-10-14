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
from tradingbot.core.models import Mode, now_ist
from tradingbot.core.plan_store import PlanCorruptError, PlanNotFoundError, PlanStore
from tradingbot.core.risk_manager import RiskManager
from tradingbot.data.ws_ticker import AsyncKiteTicker as LiveTickManager
from tradingbot.executor.execution_intelligence import ExecutionIntelligence
from tradingbot.executor.executor import Executor
from tradingbot.paper.virtual_broker import VirtualBroker
from tradingbot.scanner.calendar import NotATradingDayError, next_trading_day
from tradingbot.strategy.backtester import Backtester
from tradingbot.strategy.strategies import STRATEGY_REGISTRY

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


def build_broker(config: Config, mode: Mode) -> BrokerInterface:
    if mode is Mode.PAPER:
        from tradingbot.data.kite_client import KiteClient as DataKiteClient
        from kiteconnect import KiteConnect

        token_path = Path.home() / ".tradingbot" / "kite_token"
        kite = KiteConnect(api_key=config.secrets.kite_api_key)
        if token_path.exists():
            kite.set_access_token(token_path.read_text().strip())
        kite_client = DataKiteClient(kite, rate_limit_per_sec=config.kite.rate_limit_per_sec)

        def price_feed(symbol: str) -> float:
            ltp = kite_client.get_ltp([f"NSE:{symbol}"])
            return float(ltp[f"NSE:{symbol}"]["last_price"])

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
    """Scan the market and run the analysis pipeline (v2)."""
    click.echo(
        "The CLI analyze command has been retired. "
        "Use the web UI (tradingbot serve) and POST /api/analyze instead."
    )


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

    # Build execution intelligence (live tick feed + momentum scoring)
    from tradingbot.data.kite_client import KiteClient as DataKiteClient
    from tradingbot.data.instrument_cache import InstrumentCache
    from kiteconnect import KiteConnect

    token_path = Path.home() / ".tradingbot" / "kite_token"
    access_token = token_path.read_text().strip() if token_path.exists() else ""
    ticker = LiveTickManager(api_key=config.secrets.kite_api_key, access_token=access_token)

    data_dir = Path(obj["data_dir"])
    instrument_cache = InstrumentCache(data_dir / "instruments.db")
    kite = KiteConnect(api_key=config.secrets.kite_api_key)
    if access_token:
        kite.set_access_token(access_token)
    data_kite_client = DataKiteClient(kite, rate_limit_per_sec=config.kite.rate_limit_per_sec)

    intelligence = ExecutionIntelligence(
        ticker, config.execution,
        instrument_cache=instrument_cache,
        kite_client=data_kite_client,
        jev_config=config.jev,
    )

    executor = Executor(
        broker=build_broker(config, mode),
        plan=plan,
        risk_manager=build_risk_manager(config),
        database=database,
        execution_config=config.execution,
        mode=mode,
        intelligence=intelligence,
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
    from tradingbot.data.market_data_provider import MarketDataProvider

    provider = MarketDataProvider()

    _fail("backtest CLI requires CandleStore — use the web UI instead.")

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
    from tradingbot.execution.kite_auth import KiteAuth

    kite_auth = KiteAuth(
        api_key=config.secrets.kite_api_key,
        api_secret=config.secrets.kite_api_secret,
    )
    click.echo("Open this URL, log in, then copy the request_token from the redirect URL:")
    click.echo(f"  {kite_auth.get_login_url()}")
    request_token = click.prompt("request_token").strip()

    try:
        data = kite_auth.generate_session(request_token)
    except Exception as exc:  # noqa: BLE001
        _fail(f"login failed: {exc}")

    click.echo(f"Authenticated as {data.get('user_id', '?')}. Token saved. It expires at the next market open.")


@cli.command()
@click.option("--daily-days", default=365, type=int, help="Daily candle lookback in days.")
@click.option("--intraday-days", default=60, type=int, help="Intraday candle lookback in days.")
@click.pass_obj
def sync(obj: dict, daily_days: int, intraday_days: int) -> None:
    """Sync historical data from Kite into local DuckDB cache."""
    click.echo("Data sync is now handled via the web UI Settings page.")
    click.echo("Go to Settings → Data Cache → Start Initial Fill.")


@cli.command()
@click.option("--port", default=8000, type=int, help="Port to listen on.")
@click.option("--reload", "use_reload", is_flag=True, help="Enable auto-reload for development.")
@click.pass_obj
def serve(obj: dict, port: int, use_reload: bool) -> None:
    """Start the web API server."""
    import uvicorn

    click.echo(f"Starting API server on http://0.0.0.0:{port}")
    click.echo("Press Ctrl+C to stop.")

    # Suppress noisy access logs and Telegram polling logs
    import logging
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)

    uvicorn.run(
        "tradingbot.api.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=port,
        reload=use_reload,
        log_level="warning",
    )
