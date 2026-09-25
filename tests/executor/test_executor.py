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
        max_entry_price_drift_pct=10.0,
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
    execution_config = make_execution_config()
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
        max_entry_price_drift_pct=execution_config.max_entry_price_drift_pct,
    )
    executor = Executor(
        broker=broker,
        plan=plan if plan is not None else make_plan(legs),
        risk_manager=risk_manager,
        database=database,
        execution_config=execution_config,
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


from tradingbot.core.events import EventBus
import asyncio


async def test_executor_emits_events_when_event_bus_provided(tmp_path):
    bus = EventBus()
    events = []
    bus.subscribe(lambda e: events.append(e))

    flush_task = asyncio.create_task(bus.flush_loop())

    prices = {"RELIANCE": 100.0}
    broker = VirtualBroker(PaperConfig(slippage_pct=0.0, initial_capital=400000.0), lambda s: prices[s])
    database = Database(tmp_path / "exec_events.db")
    database.initialise()
    risk_manager = RiskManager(
        RiskConfig(max_risk_per_trade_pct=0.01, max_daily_loss_pct=0.02, max_capital_deployed_pct=0.50, max_concurrent_positions=2),
        StrategyConfig(backtest_days=30, candle_interval="15minute", min_confidence=0.5, min_reward_risk=1.5, max_trades_per_day=2),
        capital=400000.0,
    )
    executor = Executor(
        broker=broker,
        plan=make_plan([make_leg()]),
        risk_manager=risk_manager,
        database=database,
        execution_config=make_execution_config(),
        mode=Mode.PAPER,
        clock=Clock(),
        event_bus=bus,
    )

    executor.start()
    broker.advance()
    executor.tick()

    await asyncio.sleep(0.15)
    await bus.shutdown()
    flush_task.cancel()
    try:
        await flush_task
    except asyncio.CancelledError:
        pass

    types = [e["type"] for e in events]
    assert "exec.started" in types
    assert "exec.entry_filled" in types

    database.close()
