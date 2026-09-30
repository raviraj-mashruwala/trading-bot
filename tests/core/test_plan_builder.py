"""Tests for PlanBuilder — converts approved setups into a sized TradePlan."""

from __future__ import annotations

from datetime import date, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tradingbot.core.config import RiskConfig, StrategyConfig, auto_risk_config
from tradingbot.core.models import (
    Direction,
    EntryType,
    MarketRegime,
    StrategyName,
    TradePlan,
)
from tradingbot.core.plan_builder import PlanBuilder
from tradingbot.core.risk_manager import RiskManager
from tradingbot.persistence.setup_store import SetupStore

IST = ZoneInfo("Asia/Kolkata")


def _make_risk_manager(capital=400_000.0) -> RiskManager:
    return RiskManager(
        risk_config=auto_risk_config(capital),
        strategy_config=StrategyConfig(
            backtest_days=30, candle_interval="15minute",
            min_confidence=0.5, min_reward_risk=1.5, max_trades_per_day=2,
        ),
        capital=capital,
    )


@pytest.fixture
def setup_store(tmp_path):
    ss = SetupStore(tmp_path / "test.db")
    yield ss
    ss.close()


def _save_setup(ss, symbol="TCS", confidence=0.78, **overrides) -> int:
    base = {
        "run_id": "run_001", "trade_date": "2026-10-01", "symbol": symbol,
        "strategy": "breakout", "direction": "long", "entry_price": 3500.0,
        "stop_loss": 3450.0, "target_1": 3600.0, "target_2": 3680.0,
        "confidence": confidence, "status": "approved", "reasoning": "test",
    }
    base.update(overrides)
    return ss.save(base)


def test_build_creates_trade_plan_with_legs(setup_store):
    _save_setup(setup_store)
    rm = _make_risk_manager()
    builder = PlanBuilder(setup_store, rm)

    plan = builder.build(date(2026, 10, 1), regime=MarketRegime.TRENDING_UP)

    assert isinstance(plan, TradePlan)
    assert len(plan.legs) == 1
    assert plan.legs[0].symbol == "TCS"
    assert plan.legs[0].quantity > 0


def test_legs_carry_setup_id(setup_store):
    setup_id = _save_setup(setup_store)
    rm = _make_risk_manager()
    builder = PlanBuilder(setup_store, rm)

    plan = builder.build(date(2026, 10, 1), regime=MarketRegime.TRENDING_UP)

    assert plan.legs[0].setup_id == setup_id


def test_multiple_setups_ranked_by_confidence(setup_store):
    _save_setup(setup_store, symbol="INFY", confidence=0.6)
    _save_setup(setup_store, symbol="TCS", confidence=0.9)
    rm = _make_risk_manager()
    builder = PlanBuilder(setup_store, rm)

    plan = builder.build(date(2026, 10, 1), regime=MarketRegime.TRENDING_UP)

    assert plan.legs[0].symbol == "TCS"


def test_rejected_setups_excluded(setup_store):
    _save_setup(setup_store, symbol="TCS", status="rejected")
    rm = _make_risk_manager()
    builder = PlanBuilder(setup_store, rm)

    plan = builder.build(date(2026, 10, 1), regime=MarketRegime.TRENDING_UP)

    assert len(plan.legs) == 0


def test_empty_plan_when_no_approved_setups(setup_store):
    rm = _make_risk_manager()
    builder = PlanBuilder(setup_store, rm)

    plan = builder.build(date(2026, 10, 1), regime=MarketRegime.TRENDING_UP)

    assert len(plan.legs) == 0
    assert plan.trade_date == "2026-10-01"


def test_plan_respects_risk_manager_limits(setup_store):
    for i in range(5):
        _save_setup(setup_store, symbol=f"STOCK{i}", confidence=0.8 - i * 0.05)
    rm = _make_risk_manager()
    builder = PlanBuilder(setup_store, rm)

    plan = builder.build(date(2026, 10, 1), regime=MarketRegime.TRENDING_UP)

    assert len(plan.legs) <= rm.risk.max_concurrent_positions
