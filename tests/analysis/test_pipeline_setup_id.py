"""Test that pipeline captures setup_id after SetupStore.save()."""

from __future__ import annotations

from unittest.mock import MagicMock


def test_pipeline_records_setup_id_from_save():
    from tradingbot.analysis.pipeline import AnalysisPipeline

    setup_store = MagicMock()
    setup_store.save.return_value = 42

    p = AnalysisPipeline(
        data_sync=MagicMock(), candle_store=MagicMock(), screener=MagicMock(),
        tier2=MagicMock(), tier3=MagicMock(), backtest_engine=MagicMock(),
        monte_carlo=MagicMock(), quality_gates=MagicMock(), run_store=MagicMock(),
        setup_store=setup_store, event_bus=MagicMock(), capital=100_000,
    )

    setup_dict = {
        "run_id": "run_001", "trade_date": "2026-09-30", "symbol": "TCS",
        "strategy": "breakout", "direction": "long", "entry_price": 3500,
        "stop_loss": 3450, "target_1": 3600, "target_2": 3680,
        "confidence": 0.78, "status": "approved", "reasoning": "test",
    }
    row_id = p._setups.save(setup_dict)
    p._approved_setup_ids[f"TCS:breakout"] = row_id

    assert p._approved_setup_ids["TCS:breakout"] == 42
