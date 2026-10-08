"""Tests for Executor + ExecutionIntelligence integration."""

from datetime import date, datetime, time
from unittest.mock import MagicMock, AsyncMock

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
from tradingbot.executor.executor import Executor, LegState
from tradingbot.executor.entry_guard import EntryVerdict
from tradingbot.executor.adaptive_exit_manager import ExitDecision
from tradingbot.executor.momentum_scorer import SymbolState
from tradingbot.paper.virtual_broker import VirtualBroker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state(**overrides) -> SymbolState:
    defaults = dict(
        symbol="RELIANCE", timestamp=datetime(2026, 9, 29, 10, 0),
        momentum_1m=30.0, momentum_5m=35.0,
        volume_ratio=1.2, volume_trend="stable",
        vwap=2450.0, vwap_position=0.2, price_vs_open=0.5,
        last_pattern_1m="none", last_pattern_5m="none",
        body_dominance=0.5, trend_alignment=True, strength="moderate",
    )
    defaults.update(overrides)
    return SymbolState(**defaults)


class MockIntelligence:
    """Lightweight stand-in for ExecutionIntelligence."""

    def __init__(self):
        self.aggregator = MagicMock()
        self.aggregator.last_price = MagicMock(return_value=100.0)
        self.aggregator.get_candles = MagicMock(return_value=[])
        self.scorer = MagicMock()
        self.scorer.get_state = MagicMock(return_value=_state())
        self.entry_guard = MagicMock()
        self.entry_guard.evaluate = MagicMock(
            return_value=EntryVerdict("ENTER", "Clean setup", 0.8, 0)
        )
        self.adaptive_exit = MagicMock()
        self.adaptive_exit.decide = MagicMock(return_value=ExitDecision.HOLD)
        self.adaptive_exit.compute_trail_price = MagicMock(return_value=None)
        self.escalator = MagicMock()
        self.health = MagicMock()
        self.is_degraded = False
        self._started_symbols = None

    def start(self, symbols):
        self._started_symbols = symbols

    def stop(self):
        pass


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
        market_regime=MarketRegime.TRENDING_UP,
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
    def __init__(self, start=datetime(2026, 9, 24, 9, 30, tzinfo=IST)):
        self.now = start

    def __call__(self):
        return self.now

    def advance_to(self, hour, minute):
        self.now = datetime(2026, 9, 24, hour, minute, tzinfo=IST)


def build(tmp_path, legs, price=100.0, clock=None, intel=None):
    """Build an Executor with optional intelligence wired in."""
    prices = {leg.symbol: price for leg in legs} or {"RELIANCE": price}
    broker = VirtualBroker(
        PaperConfig(slippage_pct=0.0, initial_capital=400000.0), lambda symbol: prices[symbol]
    )
    database = Database(tmp_path / "exec_intel.db")
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
    if intel is None:
        intel = MockIntelligence()
    # Set aggregator price to match broker price
    intel.aggregator.last_price.return_value = price
    executor = Executor(
        broker=broker,
        plan=make_plan(legs),
        risk_manager=risk_manager,
        database=database,
        execution_config=execution_config,
        mode=Mode.PAPER,
        clock=clock or Clock(),
        intelligence=intel,
    )
    return executor, broker, prices, database, intel


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

def test_executor_accepts_intelligence(tmp_path):
    executor, _, _, _, intel = build(tmp_path, [make_leg()])
    assert executor._intelligence is intel


def test_intelligence_start_called_with_symbols(tmp_path):
    intel = MockIntelligence()
    executor, _, _, _, _ = build(tmp_path, [make_leg()], intel=intel)
    executor.start()
    assert intel._started_symbols == ["RELIANCE"]


# ---------------------------------------------------------------------------
# Entry guard — ENTER
# ---------------------------------------------------------------------------

def test_entry_guard_enter_submits_order(tmp_path):
    """Guard returns ENTER -> order placed after tick evaluates entry."""
    intel = MockIntelligence()
    intel.entry_guard.evaluate.return_value = EntryVerdict("ENTER", "Clean", 0.8, 0)
    executor, broker, _, _, _ = build(tmp_path, [make_leg()], intel=intel)
    executor.start()
    executor.tick()

    state = executor.states[0]
    assert state.entry_order_id is not None
    assert not state.waiting
    assert not state.cancelled


# ---------------------------------------------------------------------------
# Entry guard — VETO
# ---------------------------------------------------------------------------

def test_entry_guard_veto_skips_leg(tmp_path):
    """Guard returns VETO -> leg marked skipped+cancelled, no order."""
    intel = MockIntelligence()
    intel.entry_guard.evaluate.return_value = EntryVerdict("VETO", "Strong selling", 0.9, 0)
    executor, broker, _, _, _ = build(tmp_path, [make_leg()], intel=intel)
    executor.start()
    executor.tick()

    state = executor.states[0]
    assert state.skipped_reason == "Strong selling"
    assert state.cancelled is True
    assert state.entry_order_id is None


# ---------------------------------------------------------------------------
# Entry guard — WAIT
# ---------------------------------------------------------------------------

def test_entry_guard_wait_queues_leg(tmp_path):
    """Guard returns WAIT -> leg marked waiting, no order placed yet."""
    intel = MockIntelligence()
    intel.entry_guard.evaluate.return_value = EntryVerdict("WAIT", "Low volume", 0.7, 60)
    executor, broker, _, _, _ = build(tmp_path, [make_leg()], intel=intel)
    executor.start()

    state = executor.states[0]
    assert state.waiting is True
    assert state.entry_order_id is None
    assert not state.cancelled


def test_wait_leg_re_evaluated_on_tick(tmp_path):
    """A WAIT leg gets re-evaluated each tick. When guard flips to ENTER, order placed."""
    intel = MockIntelligence()
    # First call (tick 1): WAIT. Second call (tick 2): ENTER.
    intel.entry_guard.evaluate.side_effect = [
        EntryVerdict("WAIT", "Low volume", 0.7, 60),
        EntryVerdict("ENTER", "Volume recovered", 0.8, 0),
    ]
    executor, broker, _, _, _ = build(tmp_path, [make_leg()], intel=intel)
    executor.start()

    state = executor.states[0]
    assert state.waiting is True
    assert state.entry_order_id is None

    executor.tick()  # evaluates → WAIT
    assert state.waiting is True

    executor.tick()  # evaluates → ENTER
    assert state.waiting is False
    assert state.entry_order_id is not None


# ---------------------------------------------------------------------------
# Price sourcing — aggregator primary, REST fallback
# ---------------------------------------------------------------------------

def test_aggregator_price_used_for_exit(tmp_path):
    """Adaptive exit should receive price from aggregator, not broker REST."""
    intel = MockIntelligence()
    intel.entry_guard.evaluate.return_value = EntryVerdict("ENTER", "Clean", 0.8, 0)
    intel.aggregator.last_price.return_value = 100.0
    intel.adaptive_exit.decide.return_value = ExitDecision.HOLD

    executor, broker, prices, _, _ = build(tmp_path, [make_leg()], intel=intel)
    executor.start()
    broker.advance()
    executor.tick()  # fills entry

    # Now change aggregator price for the exit tick
    intel.aggregator.last_price.return_value = 105.0
    executor.tick()

    # Verify adaptive_exit.decide was called with aggregator price (105.0)
    calls = intel.adaptive_exit.decide.call_args_list
    assert len(calls) >= 1
    price_arg = calls[-1][0][2]  # 3rd positional arg = price
    assert price_arg == 105.0


def test_rest_fallback_when_aggregator_returns_none(tmp_path):
    """When aggregator has no price, falls back to broker REST."""
    intel = MockIntelligence()
    intel.entry_guard.evaluate.return_value = EntryVerdict("ENTER", "Clean", 0.8, 0)
    intel.aggregator.last_price.return_value = None  # no tick data
    intel.adaptive_exit.decide.return_value = ExitDecision.HOLD

    executor, broker, prices, _, _ = build(tmp_path, [make_leg()], intel=intel)
    executor.start()
    broker.advance()
    executor.tick()  # fills entry

    executor.tick()  # manage open leg

    # Verify adaptive_exit.decide was called with broker price (100.0)
    calls = intel.adaptive_exit.decide.call_args_list
    assert len(calls) >= 1
    price_arg = calls[-1][0][2]
    assert price_arg == 100.0


# ---------------------------------------------------------------------------
# Adaptive exit — TRAIL_STOP
# ---------------------------------------------------------------------------

def test_trail_stop_replaces_stop_order(tmp_path):
    """TRAIL_STOP decision tightens the stop via _replace_stop."""
    intel = MockIntelligence()
    intel.entry_guard.evaluate.return_value = EntryVerdict("ENTER", "Clean", 0.8, 0)
    intel.adaptive_exit.decide.return_value = ExitDecision.TRAIL_STOP
    intel.adaptive_exit.compute_trail_price.return_value = 102.0

    executor, broker, prices, _, _ = build(tmp_path, [make_leg()], intel=intel)
    executor.start()
    broker.advance()
    executor.tick()  # fills entry

    state = executor.states[0]
    old_stop_id = state.stop_order_id

    executor.tick()  # should trigger TRAIL_STOP

    assert state.current_stop == 102.0
    assert state.stop_order_id is not None
    assert state.stop_order_id != old_stop_id


# ---------------------------------------------------------------------------
# Adaptive exit — MOMENTUM_EXIT
# ---------------------------------------------------------------------------

def test_momentum_exit_closes_position(tmp_path):
    """MOMENTUM_EXIT fully closes the position."""
    intel = MockIntelligence()
    intel.entry_guard.evaluate.return_value = EntryVerdict("ENTER", "Clean", 0.8, 0)
    intel.adaptive_exit.decide.return_value = ExitDecision.MOMENTUM_EXIT
    intel.aggregator.last_price.return_value = 105.0

    executor, broker, prices, database, _ = build(tmp_path, [make_leg()], intel=intel)
    executor.start()
    broker.advance()
    executor.tick()  # fills entry

    executor.tick()  # should trigger MOMENTUM_EXIT

    state = executor.states[0]
    assert state.filled_quantity == 0

    trades = database.trades_for_date("2026-09-24")
    assert len(trades) == 1
    assert trades[0].exit_reason == "momentum_exit"


# ---------------------------------------------------------------------------
# Adaptive exit — PATTERN_EXIT
# ---------------------------------------------------------------------------

def test_pattern_exit_closes_position(tmp_path):
    """PATTERN_EXIT fully closes the position."""
    intel = MockIntelligence()
    intel.entry_guard.evaluate.return_value = EntryVerdict("ENTER", "Clean", 0.8, 0)
    intel.adaptive_exit.decide.return_value = ExitDecision.PATTERN_EXIT
    intel.aggregator.last_price.return_value = 107.0

    executor, broker, prices, database, _ = build(tmp_path, [make_leg()], intel=intel)
    executor.start()
    broker.advance()
    executor.tick()  # fills entry

    executor.tick()  # should trigger PATTERN_EXIT

    state = executor.states[0]
    assert state.filled_quantity == 0

    trades = database.trades_for_date("2026-09-24")
    assert len(trades) == 1
    assert trades[0].exit_reason == "pattern_exit"


# ---------------------------------------------------------------------------
# Adaptive exit — SQUARE_OFF + STOP_HIT still work
# ---------------------------------------------------------------------------

def test_square_off_through_adaptive_exit(tmp_path):
    clock = Clock()
    intel = MockIntelligence()
    intel.entry_guard.evaluate.return_value = EntryVerdict("ENTER", "Clean", 0.8, 0)
    intel.adaptive_exit.decide.return_value = ExitDecision.SQUARE_OFF

    executor, broker, prices, _, _ = build(tmp_path, [make_leg()], clock=clock, intel=intel)
    executor.start()
    broker.advance()
    executor.tick()  # fills entry

    clock.advance_to(15, 10)
    executor.tick()  # square off

    assert executor.states[0].filled_quantity == 0


def test_stop_hit_through_adaptive_exit(tmp_path):
    intel = MockIntelligence()
    intel.entry_guard.evaluate.return_value = EntryVerdict("ENTER", "Clean", 0.8, 0)
    intel.adaptive_exit.decide.return_value = ExitDecision.STOP_HIT
    intel.aggregator.last_price.return_value = 93.0

    executor, broker, prices, _, _ = build(tmp_path, [make_leg()], intel=intel)
    executor.start()
    broker.advance()
    executor.tick()  # fills entry

    executor.tick()  # stop hit

    assert executor.states[0].filled_quantity == 0


# ---------------------------------------------------------------------------
# No scorer data falls back to classic
# ---------------------------------------------------------------------------

def test_no_symbol_state_falls_back_to_classic(tmp_path):
    """When scorer has no state, _manage_open_leg_smart falls back to classic."""
    intel = MockIntelligence()
    intel.entry_guard.evaluate.return_value = EntryVerdict("ENTER", "Clean", 0.8, 0)
    # Return state for entry evaluation, then None for exit (triggers classic fallback)
    intel.scorer.get_state.side_effect = [_state(), None, None]
    intel.aggregator.last_price.return_value = 100.0

    executor, broker, prices, _, _ = build(tmp_path, [make_leg()], intel=intel)
    executor.start()
    executor.tick()  # evaluates entry → ENTER → submits order
    broker.advance()
    executor.tick()  # fills entry

    # Price triggers stop in classic mode
    intel.aggregator.last_price.return_value = 93.0
    prices["RELIANCE"] = 93.0
    executor.tick()

    assert executor.states[0].filled_quantity == 0


# ---------------------------------------------------------------------------
# LegState.waiting field
# ---------------------------------------------------------------------------

def test_legstate_waiting_defaults_false():
    leg = make_leg()
    ls = LegState(leg=leg)
    assert ls.waiting is False


def test_legstate_waiting_not_finished():
    """A waiting leg is not finished — it can still be entered."""
    leg = make_leg()
    ls = LegState(leg=leg, waiting=True)
    assert ls.is_finished is False


# ---------------------------------------------------------------------------
# WAIT timeout
# ---------------------------------------------------------------------------

def test_wait_leg_times_out_at_max_entry_wait(tmp_path):
    """A WAIT leg that never clears gets cancelled at max_entry_wait."""
    clock = Clock()
    intel = MockIntelligence()
    # Always return WAIT so conditions never clear
    intel.entry_guard.evaluate.return_value = EntryVerdict("WAIT", "Low volume", 0.7, 60)
    executor, broker, _, _, _ = build(tmp_path, [make_leg()], clock=clock, intel=intel)
    executor.start()

    state = executor.states[0]
    assert state.waiting is True
    assert not state.cancelled

    # Advance past max_entry_wait (11:00)
    clock.advance_to(11, 5)
    executor.tick()

    assert state.cancelled is True
    assert state.skipped_reason == "Wait timeout — conditions never cleared"


def test_wait_leg_times_out_at_entry_window_end(tmp_path):
    """A WAIT leg that never clears gets cancelled at entry_window_end."""
    clock = Clock()
    intel = MockIntelligence()
    intel.entry_guard.evaluate.return_value = EntryVerdict("WAIT", "Choppy", 0.6, 60)
    executor, broker, _, _, _ = build(tmp_path, [make_leg()], clock=clock, intel=intel)
    executor.start()

    state = executor.states[0]
    assert state.waiting is True

    # Advance past entry_window_end (10:30)
    clock.advance_to(10, 35)
    executor.tick()

    assert state.cancelled is True
    assert "Wait timeout" in state.skipped_reason
