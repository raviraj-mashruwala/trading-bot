"""Tests for setup_id threading through TradeSetup → TradeLeg → ExecutedTrade."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from tradingbot.core.models import (
    Direction,
    EntryType,
    ExecutedTrade,
    Mode,
    StrategyName,
    TradeLeg,
    TradeSetup,
    TradeStatus,
)

IST = ZoneInfo("Asia/Kolkata")


def _make_setup(setup_id: int | None = None) -> TradeSetup:
    return TradeSetup(
        symbol="TCS",
        strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG,
        entry_price=3500.0,
        entry_type=EntryType.LIMIT,
        stop_loss=3450.0,
        target_1=3600.0,
        target_2=3680.0,
        entry_window_start=time(9, 30),
        entry_window_end=time(10, 30),
        confidence=0.78,
        reasoning="test setup",
        setup_id=setup_id,
    )


def test_trade_setup_has_setup_id_default_none():
    setup = _make_setup()
    assert setup.setup_id is None


def test_trade_setup_carries_setup_id():
    setup = _make_setup(setup_id=42)
    assert setup.setup_id == 42


def test_to_leg_carries_setup_id():
    setup = _make_setup(setup_id=42)
    leg = setup.to_leg(
        quantity=100, risk_amount=5000.0,
        max_entry_wait=time(11, 0), exit_before=time(15, 10),
    )
    assert leg.setup_id == 42


def test_to_leg_carries_none_setup_id():
    setup = _make_setup(setup_id=None)
    leg = setup.to_leg(
        quantity=100, risk_amount=5000.0,
        max_entry_wait=time(11, 0), exit_before=time(15, 10),
    )
    assert leg.setup_id is None


def test_trade_leg_to_dict_includes_setup_id():
    setup = _make_setup(setup_id=42)
    leg = setup.to_leg(
        quantity=100, risk_amount=5000.0,
        max_entry_wait=time(11, 0), exit_before=time(15, 10),
    )
    d = leg.to_dict()
    assert d["setup_id"] == 42


def test_trade_leg_from_dict_restores_setup_id():
    setup = _make_setup(setup_id=42)
    leg = setup.to_leg(
        quantity=100, risk_amount=5000.0,
        max_entry_wait=time(11, 0), exit_before=time(15, 10),
    )
    restored = TradeLeg.from_dict(leg.to_dict())
    assert restored.setup_id == 42


def test_trade_leg_from_dict_handles_missing_setup_id():
    setup = _make_setup(setup_id=None)
    leg = setup.to_leg(
        quantity=100, risk_amount=5000.0,
        max_entry_wait=time(11, 0), exit_before=time(15, 10),
    )
    d = leg.to_dict()
    del d["setup_id"]
    restored = TradeLeg.from_dict(d)
    assert restored.setup_id is None


def test_executed_trade_has_setup_id():
    trade = ExecutedTrade(
        trade_date="2026-09-30",
        symbol="TCS",
        strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG,
        quantity=100,
        entry_price=3502.0,
        exit_price=3451.0,
        stop_loss=3450.0,
        target_1=3600.0,
        target_2=3680.0,
        entered_at=datetime(2026, 9, 30, 9, 35, tzinfo=IST),
        exited_at=datetime(2026, 9, 30, 10, 15, tzinfo=IST),
        pnl=-5100.0,
        exit_reason="stop_hit",
        status=TradeStatus.CLOSED,
        mode=Mode.PAPER,
        setup_id=42,
    )
    assert trade.setup_id == 42
