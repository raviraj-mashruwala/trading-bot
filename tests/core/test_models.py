from datetime import datetime, time

import pytest

from tradingbot.core.models import (
    IST,
    Direction,
    EntryType,
    MarketRegime,
    StrategyName,
    TradeLeg,
    TradePlan,
    TradeSetup,
    TradeStatus,
    now_ist,
)


def test_now_ist_is_timezone_aware_and_in_kolkata():
    ts = now_ist()
    assert ts.tzinfo is not None
    assert ts.utcoffset().total_seconds() == 5.5 * 3600


def test_trade_leg_round_trips_through_dict():
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
    restored = TradeLeg.from_dict(leg.to_dict())
    assert restored == leg


def test_trade_leg_reward_risk_uses_target_1():
    leg = TradeLeg(
        symbol="TCS",
        exchange="NSE",
        strategy=StrategyName.MOMENTUM,
        direction=Direction.LONG,
        entry_price=100.0,
        entry_type=EntryType.LIMIT,
        stop_loss=90.0,
        target_1=120.0,
        target_2=130.0,
        quantity=10,
        risk_amount=100.0,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        max_entry_wait=time(11, 0),
        exit_before=time(15, 10),
        confidence=0.6,
        reasoning="Momentum continuation.",
    )
    assert leg.reward_risk == pytest.approx(2.0)


def test_short_leg_reward_risk_uses_absolute_distances():
    leg = TradeLeg(
        symbol="INFY",
        exchange="NSE",
        strategy=StrategyName.MEAN_REVERSION,
        direction=Direction.SHORT,
        entry_price=100.0,
        entry_type=EntryType.LIMIT,
        stop_loss=110.0,
        target_1=85.0,
        target_2=80.0,
        quantity=10,
        risk_amount=100.0,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        max_entry_wait=time(11, 0),
        exit_before=time(15, 10),
        confidence=0.6,
        reasoning="Overextended, reverting to mean.",
    )
    assert leg.reward_risk == pytest.approx(1.5)


def test_trade_plan_round_trips_through_dict():
    setup = TradeSetup(
        symbol="RELIANCE",
        strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG,
        entry_price=2855.0,
        entry_type=EntryType.LIMIT,
        stop_loss=2830.0,
        target_1=2890.0,
        target_2=2920.0,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        confidence=0.72,
        reasoning="Breaking out of consolidation.",
    )
    leg = setup.to_leg(quantity=16, risk_amount=4000.0, max_entry_wait=time(11, 0), exit_before=time(15, 10))
    plan = TradePlan(
        trade_date="2026-09-24",
        generated_at=datetime(2026, 9, 23, 22, 30, tzinfo=IST),
        capital=400000.0,
        max_risk_per_trade_pct=0.01,
        max_daily_loss_pct=0.02,
        market_regime=MarketRegime.TRENDING,
        market_summary="Nifty bullish, IT leading.",
        legs=[leg],
    )
    restored = TradePlan.from_dict(plan.to_dict())
    assert restored == plan
    assert restored.legs[0].symbol == "RELIANCE"


def test_trade_plan_age_hours_measured_from_generated_at():
    plan = TradePlan(
        trade_date="2026-09-24",
        generated_at=datetime(2026, 9, 23, 22, 0, tzinfo=IST),
        capital=400000.0,
        max_risk_per_trade_pct=0.01,
        max_daily_loss_pct=0.02,
        market_regime=MarketRegime.TRENDING,
        market_summary="Nifty bullish.",
        legs=[],
    )
    reference = datetime(2026, 9, 24, 9, 0, tzinfo=IST)
    assert plan.age_hours(reference) == pytest.approx(11.0)


def test_trade_status_enum_values_are_stable_strings():
    assert TradeStatus.PENDING.value == "pending"
    assert TradeStatus.OPEN.value == "open"
    assert TradeStatus.CLOSED.value == "closed"
    assert TradeStatus.CANCELLED.value == "cancelled"
    assert TradeStatus.SKIPPED.value == "skipped"
