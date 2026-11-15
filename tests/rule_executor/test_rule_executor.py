import sqlite3
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from tradingbot.core.broker import BrokerError, OrderSide, OrderStatus, OrderType
from tradingbot.core.config import PaperConfig
from tradingbot.core.models import Direction
from tradingbot.rule_executor.executor import RuleExecutor, tick_down, tick_up
from tradingbot.rule_executor.kec_rule import DailyBar, KecRuleConfig, evaluate_signal, quantity_for, stop_price
from tradingbot.rule_executor.paper_broker import RulePaperBroker
from tradingbot.rule_executor.store import RuleStore, intraday_charges

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 11, 17)


def bars(n=20, close=100.0, last=None):
    out = [DailyBar(DAY - timedelta(days=n - i), 99.0, 101.0, 99.0, close) for i in range(n)]  # ADR ~2%
    if last is not None:
        out[-1] = last
    return out


class Clock:
    def __init__(self, hh=9, mm=0):
        self.now = datetime(DAY.year, DAY.month, DAY.day, hh, mm, tzinfo=IST)

    def __call__(self):
        return self.now

    def at(self, hh, mm, ss=0):
        self.now = self.now.replace(hour=hh, minute=mm, second=ss)


class Market:
    def __init__(self, history, today_open):
        self.history, self.open, self.calls = history, today_open, 0

    def completed_daily_bars(self, symbol, before, count):
        self.calls += 1
        return self.history[-count:]

    def today_open(self, symbol):
        return self.open


class Price:
    def __init__(self, value):
        self.value = value

    def __call__(self, symbol):
        return self.value


@pytest.fixture()
def store():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return RuleStore(conn, "kec_short")


def make(store, history, today_open, price, mode="paper", clock=None):
    clock = clock or Clock()
    broker = RulePaperBroker(PaperConfig(slippage_pct=0.0, initial_capital=400_000), price_feed=price)
    ex = RuleExecutor(broker, Market(history, today_open), store, mode, KecRuleConfig(), clock=clock)
    return ex, broker, clock


# ----- rule -----------------------------------------------------------------------

def test_gap_up_of_one_percent_triggers_short():
    s = evaluate_signal(bars(), 101.0, KecRuleConfig())
    assert s.trade and "gap up" in s.reasons[0]


def test_weak_previous_close_triggers_short_without_gap():
    weak = DailyBar(DAY - timedelta(days=1), 105.0, 106.0, 100.0, 100.5)  # close at ~8% of range
    s = evaluate_signal(bars(last=weak), 100.4, KecRuleConfig())
    assert s.trade and "previous close" in s.reasons[0]


def test_no_condition_no_trade():
    strong = DailyBar(DAY - timedelta(days=1), 99.0, 101.0, 99.0, 100.8)
    s = evaluate_signal(bars(last=strong), 100.9, KecRuleConfig())
    assert not s.trade and s.note == "no condition met"


def test_insufficient_history_and_missing_open_do_not_trade():
    assert not evaluate_signal(bars(n=5), 105.0, KecRuleConfig()).trade
    assert not evaluate_signal(bars(), 0.0, KecRuleConfig()).trade


def test_huge_gap_is_treated_as_corporate_action():
    assert not evaluate_signal(bars(), 130.0, KecRuleConfig()).trade


def test_stop_is_one_adr_above_entry_rounded_up_to_tick():
    assert stop_price(350.0, 0.025, KecRuleConfig()) == 358.75
    assert stop_price(350.03, 0.02, KecRuleConfig()) == 357.05


def test_tick_rounding_and_quantity():
    assert tick_down(346.53) == 346.5 and tick_up(346.53) == 346.55
    assert quantity_for(345.0, KecRuleConfig()) == 289


# ----- paper broker ---------------------------------------------------------------

def test_marketable_limit_fills_at_market_not_at_limit():
    price = Price(100.0)
    broker = RulePaperBroker(PaperConfig(slippage_pct=0.05, initial_capital=1e6), price_feed=price)
    oid = broker.place_order("KEC", OrderSide.SELL, OrderType.LIMIT, 10, price=99.0)
    assert broker.get_order(oid).filled_price == pytest.approx(99.95)


# ----- executor -------------------------------------------------------------------

def test_full_day_gap_short_squares_off_and_records_net_pnl(store):
    price = Price(101.0)
    ex, broker, clock = make(store, bars(), 101.0, price)
    ex.start()
    clock.at(9, 16); ex.tick()
    assert ex.state.phase == "waiting_entry"
    clock.at(9, 20); ex.tick()
    assert ex.state.phase == "entry_pending"
    ex.tick()
    assert ex.state.phase == "in_position"
    assert ex.state.entry_price == 101.0 and ex.state.quantity == 990
    assert ex.state.stop == pytest.approx(103.05)
    stop_order = broker.get_order(ex.state.stop_order_id)
    assert stop_order.order_type is OrderType.SL and stop_order.trigger_price == pytest.approx(103.05)

    price.value = 100.0
    clock.at(12, 0); ex.tick()
    assert ex.state.phase == "in_position"
    clock.at(15, 15); ex.tick()
    assert ex.state.phase in ("exiting", "done")
    ex.tick()
    assert ex.state.phase == "done"
    trade = store.trades()[0]
    assert trade["status"] == "closed" and trade["exit_reason"] == "square_off"
    assert trade["gross_pnl"] == pytest.approx(990.0)
    assert trade["net_pnl"] == pytest.approx(990.0 - intraday_charges(101.0, 100.0, 990, True))
    assert broker.get_positions() == []
    assert broker.get_order(stop_order.order_id).status is OrderStatus.CANCELLED


def test_stop_fill_at_broker_is_recorded_without_a_second_exit(store):
    price = Price(101.0)
    ex, broker, clock = make(store, bars(), 101.0, price)
    ex.start()
    clock.at(9, 16); ex.tick()
    clock.at(9, 20); ex.tick(); ex.tick()
    price.value = 103.2
    clock.at(10, 0); ex.tick()
    assert ex.state.phase == "done"
    trade = store.trades()[0]
    assert trade["exit_reason"] == "stop" and trade["exit_price"] == pytest.approx(103.2)
    assert broker.get_positions() == []
    buys = [o for o in broker._orders.values() if o.side is OrderSide.BUY and o.status is OrderStatus.COMPLETE]
    assert len(buys) == 1


def test_no_signal_places_no_orders(store):
    strong = DailyBar(DAY - timedelta(days=1), 99.0, 101.0, 99.0, 100.8)
    ex, broker, clock = make(store, bars(last=strong), 100.9, Price(100.9))
    ex.start()
    clock.at(9, 16); ex.tick()
    assert ex.state.phase == "done" and broker._orders == {}


def test_starting_after_entry_window_does_nothing(store):
    ex, broker, clock = make(store, bars(), 101.0, Price(101.0), clock=Clock(10, 0))
    ex.start()
    assert ex.is_done and ex.market.calls == 0


def test_one_trade_per_day_per_mode(store):
    ex, _, clock = make(store, bars(), 101.0, Price(101.0))
    ex.start(); clock.at(9, 16); ex.tick(); clock.at(9, 20); ex.tick(); ex.tick()
    clock.at(15, 15); ex.tick(); ex.tick()
    again, _, _ = make(store, bars(), 101.0, Price(101.0), clock=Clock(9, 5))
    again.start()
    assert again.is_done and again.state.note == "already traded today"
    live, _, _ = make(store, bars(), 101.0, Price(101.0), mode="live", clock=Clock(9, 5))
    live.start()
    assert not live.is_done  # paper history does not block a live session


def test_paper_restart_resumes_open_short(store):
    price = Price(101.0)
    ex, _, clock = make(store, bars(), 101.0, price)
    ex.start(); clock.at(9, 16); ex.tick(); clock.at(9, 20); ex.tick(); ex.tick()
    ex.stop()
    resumed, broker2, clock2 = make(store, bars(), 101.0, price, clock=Clock(11, 0))
    resumed.start()
    assert resumed.state.phase == "in_position" and resumed.state.quantity == 990
    assert broker2.get_positions()[0].direction is Direction.SHORT
    clock2.at(15, 15); resumed.tick(); resumed.tick()
    assert store.trades()[0]["status"] == "closed"


def test_entry_rejection_ends_session_without_position(store):
    ex, broker, clock = make(store, bars(), 101.0, Price(101.0))

    def reject(*a, **k):
        raise BrokerError("IP not allowed")

    broker.place_order = reject
    ex.start(); clock.at(9, 16); ex.tick(); clock.at(9, 20); ex.tick()
    assert ex.state.phase == "done" and "rejected" in ex.state.note and store.trades() == []


def test_a_failing_tick_does_not_end_the_session(store):
    ex, _, clock = make(store, bars(), 101.0, Price(101.0))
    ex.start()

    def boom(*a, **k):
        raise ConnectionError("network down")

    ex.market.completed_daily_bars = boom
    clock.at(9, 16); ex.tick()
    assert ex.state.phase == "waiting_signal" and not ex.is_done
    assert any(e["kind"] == "TICK_ERROR" for e in store.events())


class SlowBroker(RulePaperBroker):
    """Exit limit orders rest (do not fill) until released, like a thin live book."""

    hold_exits = True

    def _try_fill(self, order):
        if order.order_type is OrderType.LIMIT and order.side is OrderSide.BUY and self.hold_exits:
            return
        super()._try_fill(order)


def test_resting_exit_is_cancelled_and_retried(store):
    clock = Clock()
    broker = SlowBroker(PaperConfig(slippage_pct=0.0, initial_capital=400_000), price_feed=Price(101.0))
    ex = RuleExecutor(broker, Market(bars(), 101.0), store, "paper", KecRuleConfig(), clock=clock)
    ex.start(); clock.at(9, 16); ex.tick(); clock.at(9, 20); ex.tick(); ex.tick()
    clock.at(15, 15); ex.tick()
    assert ex.state.phase == "exiting" and ex.state.exit_attempts == 1
    first = ex.state.exit_order_id
    clock.at(15, 15, 40); ex.tick()
    assert broker.get_order(first).status is OrderStatus.CANCELLED and ex.state.exit_attempts == 2
    broker.hold_exits = False
    ex.tick()
    assert ex.state.phase == "done" and store.trades()[0]["exit_reason"] == "square_off"
