import pytest
from datetime import date, datetime
from zoneinfo import ZoneInfo
from tradingbot.core.models import (
    AnalysisRun, MarketRegime, SetupStatus, StrategyName, Direction,
)
from tradingbot.persistence.run_store import RunStore
from tradingbot.persistence.setup_store import SetupStore

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def run_store(tmp_path):
    return RunStore(tmp_path / "analysis.db")


@pytest.fixture
def setup_store(tmp_path):
    return SetupStore(tmp_path / "analysis.db")


def _make_run(run_id="run_001", trade_date=date(2026, 9, 27)):
    return AnalysisRun(
        run_id=run_id, timestamp=datetime.now(tz=IST), trade_date=trade_date,
        market_regime=MarketRegime.TRENDING_UP, regime_confidence=0.82,
        total_scanned=1500, tier1_passed=80, tier2_shortlisted=12,
        setups_proposed=8, setups_approved=5, llm_calls=16,
        llm_cost_usd=0.18, duration_seconds=45.2,
    )


def test_save_and_list_runs(run_store):
    run = _make_run()
    run_store.save(run)
    runs = run_store.list_for_date(date(2026, 9, 27))
    assert len(runs) == 1
    assert runs[0]["run_id"] == "run_001"


def test_multiple_runs_same_date(run_store):
    run_store.save(_make_run("run_001"))
    run_store.save(_make_run("run_002"))
    runs = run_store.list_for_date(date(2026, 9, 27))
    assert len(runs) == 2


def test_setup_save_and_get(setup_store):
    setup = {
        "run_id": "run_001", "symbol": "RELIANCE", "strategy": "vwap_mean_reversion",
        "direction": "long", "entry_price": 2485.0, "stop_loss": 2468.0,
        "target_1": 2510.0, "target_2": 2530.0, "confidence": 0.82,
        "status": "approved", "trade_date": "2026-09-27",
        "reasoning": "VWAP support bounce",
    }
    setup_id = setup_store.save(setup)
    assert setup_id > 0
    active = setup_store.get_active(date(2026, 9, 27))
    assert len(active) == 1


def test_setup_update_status(setup_store):
    setup = {
        "run_id": "run_001", "symbol": "TCS", "strategy": "momentum",
        "direction": "long", "entry_price": 3500.0, "stop_loss": 3470.0,
        "target_1": 3550.0, "target_2": 3580.0, "confidence": 0.75,
        "status": "proposed", "trade_date": "2026-09-27", "reasoning": "test",
    }
    setup_id = setup_store.save(setup)
    setup_store.update_status(setup_id, "rejected", reason="too tight SL")
    result = setup_store.get_by_id(setup_id)
    assert result["status"] == "rejected"


def test_get_for_symbol(setup_store):
    for i, run_id in enumerate(["run_001", "run_002"]):
        setup_store.save({
            "run_id": run_id, "symbol": "RELIANCE", "strategy": "momentum",
            "direction": "long", "entry_price": 2500 + i * 10, "stop_loss": 2480,
            "target_1": 2540, "target_2": 2560, "confidence": 0.7 + i * 0.05,
            "status": "approved", "trade_date": "2026-09-27", "reasoning": f"run {i}",
        })
    setups = setup_store.get_for_symbol("RELIANCE", date(2026, 9, 27))
    assert len(setups) == 2


def test_get_all_for_date(setup_store):
    """get_all_for_date returns every setup regardless of status."""
    for status in ["approved", "proposed", "rejected"]:
        setup_store.save({
            "run_id": "run_001", "symbol": "TCS", "strategy": "momentum",
            "direction": "long", "entry_price": 3500, "stop_loss": 3470,
            "target_1": 3550, "target_2": 3580, "confidence": 0.75,
            "status": status, "trade_date": "2026-09-27", "reasoning": "test",
        })
    all_setups = setup_store.get_all_for_date(date(2026, 9, 27))
    assert len(all_setups) == 3
