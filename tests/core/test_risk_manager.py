from datetime import datetime, time

import pytest

from tradingbot.core.config import RiskConfig, StrategyConfig
from tradingbot.core.models import (
    IST,
    Direction,
    EntryType,
    MarketRegime,
    StrategyName,
    TradePlan,
    TradeSetup,
)
from tradingbot.core.risk_manager import InvalidSetupError, RiskManager


def make_risk_config(**overrides) -> RiskConfig:
    defaults = {
        "max_risk_per_trade_pct": 0.01,
        "max_daily_loss_pct": 0.02,
        "max_capital_deployed_pct": 0.50,
        "max_concurrent_positions": 2,
    }
    defaults.update(overrides)
    return RiskConfig(**defaults)


def make_strategy_config(**overrides) -> StrategyConfig:
    defaults = {
        "backtest_days": 30,
        "candle_interval": "15minute",
        "min_confidence": 0.5,
        "min_reward_risk": 1.5,
        "max_trades_per_day": 2,
    }
    defaults.update(overrides)
    return StrategyConfig(**defaults)


def make_manager(capital=400000.0, **risk_overrides) -> RiskManager:
    return RiskManager(make_risk_config(**risk_overrides), make_strategy_config(), capital)


def make_setup(
    symbol="RELIANCE",
    entry=100.0,
    stop=90.0,
    target_1=120.0,
    target_2=130.0,
    confidence=0.72,
    direction=Direction.LONG,
) -> TradeSetup:
    return TradeSetup(
        symbol=symbol,
        strategy=StrategyName.BREAKOUT,
        direction=direction,
        entry_price=entry,
        entry_type=EntryType.LIMIT,
        stop_loss=stop,
        target_1=target_1,
        target_2=target_2,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        confidence=confidence,
        reasoning="Setup under test.",
    )


def make_plan(legs, generated_at=datetime(2026, 9, 23, 22, 0, tzinfo=IST)) -> TradePlan:
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


def test_position_size_uses_risk_divided_by_stop_distance():
    manager = make_manager()

    # 1% of 400000 = 4000 risk budget; 10 rupees of risk per share -> 400 shares.
    assert manager.position_size(make_setup()) == 400


def test_position_size_is_floored_not_rounded_up():
    manager = make_manager(max_risk_per_trade_pct=0.01)

    # 4000 / 30 = 133.33 -> 133 shares.
    assert manager.position_size(make_setup(entry=100.0, stop=70.0)) == 133


def test_position_size_is_capped_by_deployable_capital():
    manager = make_manager(max_capital_deployed_pct=0.10)

    # Risk sizing wants 4000/1 = 4000 shares, but 10% of 400000 at 100/share allows 400.
    assert manager.position_size(make_setup(entry=100.0, stop=99.0)) == 400


def test_stop_loss_equal_to_entry_raises_invalid_setup():
    manager = make_manager()

    with pytest.raises(InvalidSetupError, match="stop loss equals entry"):
        manager.position_size(make_setup(entry=100.0, stop=100.0))


def test_stop_loss_within_a_rounding_hair_of_entry_also_raises():
    manager = make_manager()

    with pytest.raises(InvalidSetupError, match="stop loss equals entry"):
        manager.position_size(make_setup(entry=100.0, stop=100.0000001))


def test_short_setups_size_on_the_absolute_stop_distance():
    manager = make_manager()

    setup = make_setup(direction=Direction.SHORT, entry=100.0, stop=110.0, target_1=85.0, target_2=80.0)

    assert manager.position_size(setup) == 400


def test_risk_amount_is_quantity_times_stop_distance():
    manager = make_manager()

    assert manager.risk_amount_for(make_setup(), quantity=400) == pytest.approx(4000.0)


def test_vet_setup_accepts_a_healthy_setup():
    assert make_manager().vet_setup(make_setup()) is None


def test_vet_setup_rejects_low_confidence():
    assert make_manager().vet_setup(make_setup(confidence=0.3)) == "confidence below minimum"


def test_vet_setup_rejects_poor_reward_to_risk():
    # 10 of risk against 5 of reward is 0.5, below the 1.5 minimum.
    assert make_manager().vet_setup(make_setup(target_1=105.0)) == "reward:risk below minimum"


def test_vet_setup_rejects_a_long_whose_stop_sits_above_entry():
    assert make_manager().vet_setup(make_setup(stop=110.0)) == "stop loss on the wrong side of entry"


def test_vet_setup_rejects_a_long_whose_target_sits_below_entry():
    assert make_manager().vet_setup(make_setup(target_1=80.0)) == "target on the wrong side of entry"


def test_vet_setup_rejects_a_zero_width_stop():
    assert make_manager().vet_setup(make_setup(stop=100.0)) == "stop loss equals entry price"


def test_select_legs_keeps_only_the_highest_confidence_setups():
    manager = make_manager()
    setups = [
        make_setup(symbol="A", confidence=0.6),
        make_setup(symbol="B", confidence=0.9),
        make_setup(symbol="C", confidence=0.75),
    ]

    legs = manager.select_legs(setups, max_entry_wait=time(11, 0), exit_before=time(15, 10))

    assert [leg.symbol for leg in legs] == ["B", "C"]


def test_select_legs_drops_setups_that_fail_vetting():
    manager = make_manager()
    setups = [make_setup(symbol="GOOD", confidence=0.9), make_setup(symbol="WEAK", confidence=0.2)]

    legs = manager.select_legs(setups, max_entry_wait=time(11, 0), exit_before=time(15, 10))

    assert [leg.symbol for leg in legs] == ["GOOD"]


def test_select_legs_drops_setups_that_would_size_to_zero_shares():
    manager = make_manager(max_risk_per_trade_pct=0.0001)
    setups = [make_setup(symbol="TOOBIG", entry=5000.0, stop=1000.0, target_1=12000.0, confidence=0.9)]

    assert manager.select_legs(setups, max_entry_wait=time(11, 0), exit_before=time(15, 10)) == []


def test_select_legs_stops_adding_once_total_exposure_is_reached():
    manager = make_manager(max_capital_deployed_pct=0.05, max_concurrent_positions=2)
    setups = [
        make_setup(symbol="A", entry=100.0, stop=95.0, target_1=115.0, confidence=0.9),
        make_setup(symbol="B", entry=100.0, stop=95.0, target_1=115.0, confidence=0.8),
    ]

    legs = manager.select_legs(setups, max_entry_wait=time(11, 0), exit_before=time(15, 10))

    total_notional = sum(leg.notional for leg in legs)
    assert total_notional <= 0.05 * 400000.0


def test_select_legs_carries_the_sized_quantity_and_risk_onto_the_leg():
    manager = make_manager()

    legs = manager.select_legs([make_setup()], max_entry_wait=time(11, 0), exit_before=time(15, 10))

    assert legs[0].quantity == 400
    assert legs[0].risk_amount == pytest.approx(4000.0)
    assert legs[0].max_entry_wait == time(11, 0)
    assert legs[0].exit_before == time(15, 10)


def test_a_fresh_plan_passes_pre_execution_vetting():
    manager = make_manager()
    legs = manager.select_legs([make_setup()], max_entry_wait=time(11, 0), exit_before=time(15, 10))
    plan = make_plan(legs)

    blockers = manager.vet_plan_for_execution(
        plan, now=datetime(2026, 9, 24, 9, 0, tzinfo=IST), available_capital=400000.0
    )

    assert blockers == []


def test_a_stale_plan_is_blocked():
    manager = make_manager()
    plan = make_plan([], generated_at=datetime(2026, 9, 22, 8, 0, tzinfo=IST))

    blockers = manager.vet_plan_for_execution(
        plan, now=datetime(2026, 9, 24, 9, 0, tzinfo=IST), available_capital=400000.0
    )

    assert any("stale" in reason for reason in blockers)


def test_insufficient_capital_blocks_the_plan():
    manager = make_manager()
    legs = manager.select_legs([make_setup()], max_entry_wait=time(11, 0), exit_before=time(15, 10))
    plan = make_plan(legs)

    blockers = manager.vet_plan_for_execution(
        plan, now=datetime(2026, 9, 24, 9, 0, tzinfo=IST), available_capital=100.0
    )

    assert any("capital" in reason for reason in blockers)


def test_vet_leg_at_open_accepts_a_price_that_has_barely_moved():
    manager = make_manager()
    leg = manager.select_legs([make_setup()], max_entry_wait=time(11, 0), exit_before=time(15, 10))[0]

    assert manager.vet_leg_at_open(leg, current_price=101.0) is None


def test_vet_leg_at_open_rejects_a_price_that_gapped_away():
    manager = make_manager()
    leg = manager.select_legs([make_setup()], max_entry_wait=time(11, 0), exit_before=time(15, 10))[0]

    reason = manager.vet_leg_at_open(leg, current_price=150.0)

    assert reason is not None
    assert "drifted" in reason


def test_daily_loss_kill_switch_trips_at_the_configured_threshold():
    manager = make_manager()

    assert manager.daily_loss_breached(-7999.0) is False
    assert manager.daily_loss_breached(-8000.0) is True
    assert manager.daily_loss_breached(-9000.0) is True


def test_daily_loss_kill_switch_ignores_profits():
    assert make_manager().daily_loss_breached(5000.0) is False
