import pytest
from datetime import date, datetime
from zoneinfo import ZoneInfo
from tradingbot.persistence.daily_plan import DailyPlanBuilder
from tradingbot.persistence.run_store import RunStore
from tradingbot.persistence.setup_store import SetupStore
from tradingbot.core.models import AnalysisRun, MarketRegime

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def stores(tmp_path):
    db = tmp_path / "test.db"
    return RunStore(db), SetupStore(db)


def _make_run(run_id, trade_date=date(2026, 9, 27)):
    return AnalysisRun(
        run_id=run_id, timestamp=datetime.now(tz=IST),
        trade_date=trade_date, market_regime=MarketRegime.TRENDING_UP,
        regime_confidence=0.82, total_scanned=1500, tier1_passed=80,
        tier2_shortlisted=12, setups_proposed=3, setups_approved=3,
        llm_calls=16, llm_cost_usd=0.18, duration_seconds=45,
    )


def test_build_daily_plan_ranks_by_confidence(stores):
    run_store, setup_store = stores
    run_store.save(_make_run("run_001"))
    for sym, conf in [("RELIANCE", 0.88), ("HDFCBANK", 0.75), ("TCS", 0.92)]:
        setup_store.save({
            "run_id": "run_001", "symbol": sym, "strategy": "momentum",
            "direction": "long", "entry_price": 1000, "stop_loss": 980,
            "target_1": 1030, "target_2": 1050, "confidence": conf,
            "status": "approved", "trade_date": "2026-09-27", "reasoning": "test",
        })

    builder = DailyPlanBuilder(run_store, setup_store)
    plan = builder.build(date(2026, 9, 27))
    assert plan["date"] == "2026-09-27"
    assert len(plan["ranked_suggestions"]) == 3
    assert plan["ranked_suggestions"][0]["symbol"] == "TCS"  # highest confidence


def test_cross_run_consistency(stores):
    run_store, setup_store = stores
    for rid in ["run_001", "run_002"]:
        run_store.save(_make_run(rid))
        setup_store.save({
            "run_id": rid, "symbol": "RELIANCE", "strategy": "momentum",
            "direction": "long", "entry_price": 2500, "stop_loss": 2480,
            "target_1": 2530, "target_2": 2550, "confidence": 0.8,
            "status": "approved", "trade_date": "2026-09-27", "reasoning": "test",
        })

    builder = DailyPlanBuilder(run_store, setup_store)
    plan = builder.build(date(2026, 9, 27))
    rel = [s for s in plan["ranked_suggestions"] if s["symbol"] == "RELIANCE"][0]
    assert rel["consistency"] == 1.0  # both runs agree


def test_conflicting_directions_flagged(stores):
    run_store, setup_store = stores
    run_store.save(_make_run("run_001"))
    run_store.save(_make_run("run_002"))
    setup_store.save({
        "run_id": "run_001", "symbol": "INFY", "strategy": "momentum",
        "direction": "long", "entry_price": 1800, "stop_loss": 1780,
        "target_1": 1830, "target_2": 1850, "confidence": 0.8,
        "status": "approved", "trade_date": "2026-09-27", "reasoning": "bull",
    })
    setup_store.save({
        "run_id": "run_002", "symbol": "INFY", "strategy": "mean_reversion",
        "direction": "short", "entry_price": 1810, "stop_loss": 1830,
        "target_1": 1780, "target_2": 1760, "confidence": 0.75,
        "status": "approved", "trade_date": "2026-09-27", "reasoning": "bear",
    })

    builder = DailyPlanBuilder(run_store, setup_store)
    plan = builder.build(date(2026, 9, 27))
    infy = [s for s in plan["ranked_suggestions"] if s["symbol"] == "INFY"][0]
    assert infy["recommendation"] == "conflicting"


def test_empty_plan(stores):
    run_store, setup_store = stores
    builder = DailyPlanBuilder(run_store, setup_store)
    plan = builder.build(date(2026, 9, 27))
    assert plan["ranked_suggestions"] == []
    assert plan["total_runs"] == 0
