"""Verify all 5 database modules work through the connection factory."""
from datetime import datetime, date
from pathlib import Path

import pytest

from tradingbot.core.database import Database
from tradingbot.data.instrument_cache import InstrumentCache
from tradingbot.data.candle_store import CandleStore
from tradingbot.persistence.setup_store import SetupStore
from tradingbot.persistence.run_store import RunStore


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_TRADING_URL", raising=False)
    monkeypatch.delenv("TURSO_TRADING_TOKEN", raising=False)
    monkeypatch.delenv("TURSO_MARKET_URL", raising=False)
    monkeypatch.delenv("TURSO_MARKET_TOKEN", raising=False)
    return tmp_path


def test_all_modules_through_factory(data_dir):
    db = Database(data_dir / "tradingbot.db")
    db.initialise()

    cache = InstrumentCache(data_dir / "instruments.db")
    cache.refresh([{
        "instrument_token": 738561, "tradingsymbol": "RELIANCE",
        "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
        "instrument_type": "EQ", "segment": "NSE", "industry_type": "Refineries",
    }])

    candles = CandleStore(data_dir / "candles.db")
    candles.upsert("RELIANCE", "15minute", [{
        "date": datetime(2026, 9, 30, 9, 15),
        "open": 2450.0, "high": 2455.0, "low": 2448.0,
        "close": 2453.0, "volume": 1000,
    }])

    setups = SetupStore(data_dir / "analysis.db")
    runs = RunStore(data_dir / "analysis.db")

    assert cache.get_token("RELIANCE") == 738561
    result = candles.read("RELIANCE", "15minute", date(2026, 9, 29), date(2026, 10, 1))
    assert len(result) == 1

    db.close()
    cache.close()
    candles.close()
    setups.close()
    runs.close()


def test_factory_connections_independent(data_dir):
    from tradingbot.core.models import AnalysisRun, MarketRegime
    setups = SetupStore(data_dir / "analysis.db")
    runs = RunStore(data_dir / "analysis.db")
    run = AnalysisRun(
        run_id="r1", trade_date=date(2026, 9, 30),
        timestamp=datetime.now(),
        market_regime=MarketRegime.TRENDING_UP, regime_confidence=0.8,
        total_scanned=50, tier1_passed=10,
        tier2_shortlisted=5, setups_proposed=3,
        setups_approved=2, llm_calls=3,
        llm_cost_usd=0.03, duration_seconds=60.0,
    )
    runs.save(run)
    assert len(runs.list_for_date("2026-09-30")) == 1
    setups.close()
    runs.close()
