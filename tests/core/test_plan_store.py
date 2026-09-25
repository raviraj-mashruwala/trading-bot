import json
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
)
from tradingbot.core.plan_store import PlanCorruptError, PlanNotFoundError, PlanStore


def make_plan(trade_date: str = "2026-09-24") -> TradePlan:
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
        reasoning="Breaking out.",
    )
    return TradePlan(
        trade_date=trade_date,
        generated_at=datetime(2026, 9, 23, 22, 30, tzinfo=IST),
        capital=400000.0,
        max_risk_per_trade_pct=0.01,
        max_daily_loss_pct=0.02,
        market_regime=MarketRegime.TRENDING,
        market_summary="Nifty bullish.",
        legs=[leg],
    )


def test_save_then_load_returns_an_identical_plan(tmp_path):
    store = PlanStore(tmp_path)
    plan = make_plan()

    written = store.save(plan)

    assert written.name == "2026-09-24.json"
    assert store.load("2026-09-24") == plan


def test_load_latest_picks_the_newest_trade_date(tmp_path):
    store = PlanStore(tmp_path)
    store.save(make_plan("2026-09-22"))
    store.save(make_plan("2026-09-24"))
    store.save(make_plan("2026-09-23"))

    assert store.load_latest().trade_date == "2026-09-24"


def test_load_missing_plan_raises_plan_not_found(tmp_path):
    store = PlanStore(tmp_path)

    with pytest.raises(PlanNotFoundError, match="2026-09-24"):
        store.load("2026-09-24")


def test_load_latest_with_no_plans_raises_plan_not_found(tmp_path):
    store = PlanStore(tmp_path)

    with pytest.raises(PlanNotFoundError, match="no trade plans"):
        store.load_latest()


def test_malformed_json_raises_plan_corrupt(tmp_path):
    store = PlanStore(tmp_path)
    (tmp_path / "2026-09-24.json").write_text("{not valid json")

    with pytest.raises(PlanCorruptError, match="could not be parsed"):
        store.load("2026-09-24")


def test_plan_missing_required_field_raises_plan_corrupt(tmp_path):
    store = PlanStore(tmp_path)
    payload = make_plan().to_dict()
    del payload["capital"]
    (tmp_path / "2026-09-24.json").write_text(json.dumps(payload))

    with pytest.raises(PlanCorruptError, match="capital"):
        store.load("2026-09-24")


def test_plan_with_future_schema_version_raises_plan_corrupt(tmp_path):
    store = PlanStore(tmp_path)
    payload = make_plan().to_dict()
    payload["schema_version"] = 99
    (tmp_path / "2026-09-24.json").write_text(json.dumps(payload))

    with pytest.raises(PlanCorruptError, match="schema version 99"):
        store.load("2026-09-24")
