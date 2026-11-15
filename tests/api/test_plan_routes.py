from datetime import datetime, time

import pytest

from tradingbot.core.models import (
    IST, Direction, EntryType, MarketRegime, StrategyName, TradeLeg, TradePlan,
)
from tradingbot.core.plan_store import PlanStore


def make_plan(trade_date="2026-09-28") -> TradePlan:
    leg = TradeLeg(
        symbol="RELIANCE", exchange="NSE", strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG, entry_price=2855.0, entry_type=EntryType.LIMIT,
        stop_loss=2830.0, target_1=2890.0, target_2=2920.0, quantity=16,
        risk_amount=4000.0, entry_window_start=time(9, 30),
        entry_window_end=time(10, 30), max_entry_wait=time(11, 0),
        exit_before=time(15, 10), confidence=0.72, reasoning="Breaking out.",
    )
    return TradePlan(
        trade_date=trade_date,
        generated_at=datetime(2026, 9, 27, 22, 30, tzinfo=IST),
        capital=400000.0, max_risk_per_trade_pct=0.01,
        max_daily_loss_pct=0.02, market_regime=MarketRegime.TRENDING_UP,
        market_summary="Nifty bullish.", legs=[leg],
    )


@pytest.fixture(autouse=True)
def seed_plans(api_client):
    tmp = api_client._tmp_path
    store = PlanStore(tmp / "trade_plans")
    store.save(make_plan("2026-09-28"))
    store.save(make_plan("2026-09-26"))


async def test_list_plans_returns_all_dates(api_client):
    response = await api_client.get("/api/plans")
    assert response.status_code == 200
    dates = [p["trade_date"] for p in response.json()]
    assert "2026-09-28" in dates
    assert "2026-09-26" in dates


async def test_list_plans_ignores_non_plan_json_in_same_directory(api_client):
    tmp = api_client._tmp_path
    scratch = tmp / "trade_plans" / "llm_dossiers.json"
    scratch.write_text("[]")

    response = await api_client.get("/api/plans")

    assert response.status_code == 200
    dates = [p["trade_date"] for p in response.json()]
    assert "2026-09-28" in dates
    assert "2026-09-26" in dates


async def test_get_plan_by_date(api_client):
    response = await api_client.get("/api/plans/2026-09-28")
    assert response.status_code == 200
    body = response.json()
    assert body["trade_date"] == "2026-09-28"
    assert len(body["legs"]) == 1
    assert body["legs"][0]["symbol"] == "RELIANCE"


async def test_get_missing_plan_returns_404(api_client):
    response = await api_client.get("/api/plans/2099-01-01")
    assert response.status_code == 404


async def test_delete_plan(api_client):
    response = await api_client.delete("/api/plans/2026-09-26")
    assert response.status_code == 200

    check = await api_client.get("/api/plans/2026-09-26")
    assert check.status_code == 404
