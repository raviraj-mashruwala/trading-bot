from datetime import datetime, time

import pytest

from tradingbot.core.models import IST, Direction, EntryType, StrategyName, TradeLeg
from tradingbot.executor.exit_manager import ExitDecision, ExitManager
from tradingbot.executor.executor import LegState


def make_leg(direction=Direction.LONG) -> TradeLeg:
    long_side = direction is Direction.LONG
    return TradeLeg(
        symbol="RELIANCE",
        exchange="NSE",
        strategy=StrategyName.BREAKOUT,
        direction=direction,
        entry_price=100.0,
        entry_type=EntryType.LIMIT,
        stop_loss=95.0 if long_side else 105.0,
        target_1=110.0 if long_side else 90.0,
        target_2=115.0 if long_side else 85.0,
        quantity=10,
        risk_amount=50.0,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        max_entry_wait=time(11, 0),
        exit_before=time(15, 10),
        confidence=0.8,
        reasoning="Test leg.",
    )


def make_state(direction=Direction.LONG, target_1_booked=False, current_stop=None) -> LegState:
    leg = make_leg(direction)
    state = LegState(leg=leg)
    state.filled_quantity = 10
    state.entry_fill_price = 100.0
    state.target_1_booked = target_1_booked
    state.current_stop = current_stop if current_stop is not None else leg.stop_loss
    return state


def at(hour, minute):
    return datetime(2026, 9, 24, hour, minute, tzinfo=IST)


def make_manager():
    return ExitManager(square_off_time=time(15, 10))


def test_a_long_holds_between_stop_and_target():
    assert make_manager().decide(make_state(), price=103.0, now=at(11, 0)) is ExitDecision.HOLD


def test_a_long_books_target_1_when_it_is_reached():
    decision = make_manager().decide(make_state(), price=110.0, now=at(11, 0))

    assert decision is ExitDecision.BOOK_TARGET_1


def test_a_long_books_target_2_only_after_target_1():
    state = make_state(target_1_booked=True)

    assert make_manager().decide(state, price=115.0, now=at(11, 0)) is ExitDecision.BOOK_TARGET_2


def test_a_long_stops_out_when_price_falls_through_the_stop():
    assert make_manager().decide(make_state(), price=94.0, now=at(11, 0)) is ExitDecision.STOP_HIT


def test_a_long_stops_out_on_the_trailed_stop_not_the_original():
    state = make_state(target_1_booked=True, current_stop=100.0)

    assert make_manager().decide(state, price=99.0, now=at(11, 0)) is ExitDecision.STOP_HIT


def test_a_short_books_target_1_when_price_falls_to_it():
    state = make_state(Direction.SHORT)

    assert make_manager().decide(state, price=90.0, now=at(11, 0)) is ExitDecision.BOOK_TARGET_1


def test_a_short_stops_out_when_price_rises_through_the_stop():
    state = make_state(Direction.SHORT)

    assert make_manager().decide(state, price=106.0, now=at(11, 0)) is ExitDecision.STOP_HIT


def test_a_short_holds_between_its_levels():
    state = make_state(Direction.SHORT)

    assert make_manager().decide(state, price=98.0, now=at(11, 0)) is ExitDecision.HOLD


def test_square_off_time_overrides_a_perfectly_healthy_position():
    assert make_manager().decide(make_state(), price=103.0, now=at(15, 10)) is ExitDecision.SQUARE_OFF


def test_square_off_applies_after_the_cutoff_too():
    assert make_manager().decide(make_state(), price=103.0, now=at(15, 25)) is ExitDecision.SQUARE_OFF


def test_square_off_takes_priority_over_a_target():
    assert make_manager().decide(make_state(), price=120.0, now=at(15, 12)) is ExitDecision.SQUARE_OFF


def test_a_position_with_no_fill_always_holds():
    state = make_state()
    state.filled_quantity = 0

    assert make_manager().decide(state, price=94.0, now=at(11, 0)) is ExitDecision.HOLD


def test_trailing_a_long_stop_moves_it_to_the_entry_fill():
    state = make_state()

    assert make_manager().trail_stop(state) == pytest.approx(100.0)


def test_trailing_never_moves_a_long_stop_backwards():
    state = make_state(current_stop=102.0)

    assert make_manager().trail_stop(state) == pytest.approx(102.0)


def test_trailing_a_short_stop_moves_it_down_to_the_entry_fill():
    state = make_state(Direction.SHORT)

    assert make_manager().trail_stop(state) == pytest.approx(100.0)


def test_trailing_never_moves_a_short_stop_backwards():
    state = make_state(Direction.SHORT, current_stop=98.0)

    assert make_manager().trail_stop(state) == pytest.approx(98.0)
