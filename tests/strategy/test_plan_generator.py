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
                regime=MarketRegime.TRENDING_UP,
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

    assert plan.market_regime is MarketRegime.TRENDING_UP
    assert plan.capital == pytest.approx(400000.0)


async def test_the_written_plan_reloads_identically(tmp_path):
    generator, _ = make_generator(tmp_path, make_shortlist("RELIANCE"), [make_setup("RELIANCE")])

    plan = await generator.generate(date(2026, 9, 24))

    assert PlanStore(tmp_path).load("2026-09-24") == plan


from tradingbot.core.events import EventBus


async def test_generate_emits_strategy_events(tmp_path):
    bus = EventBus()
    events = []
    bus.subscribe(lambda e: events.append(e))

    generator, _ = make_generator(tmp_path, make_shortlist("RELIANCE"), [make_setup("RELIANCE")])
    generator.event_bus = bus

    await generator.generate(date(2026, 9, 24))

    types = [e["type"] for e in events]
    assert "strategy.indicators" in types
    assert "strategy.setups" in types
    assert "strategy.sized" in types
