from datetime import datetime
from unittest.mock import MagicMock
import json
import pytest
from tradingbot.executor.decision_logger import DecisionLogger


def test_log_entry_decision():
    db = MagicMock()
    logger = DecisionLogger(db)
    logger.log_decision(
        trade_date="2026-09-29",
        symbol="RELIANCE",
        decision_type="ENTRY_VETO",
        reason="Strong 5m selling",
        momentum_snapshot={"momentum_1m": -45.0, "momentum_5m": -65.0},
        escalated=False,
    )
    db.log_execution_decision.assert_called_once()


def test_log_escalation():
    db = MagicMock()
    logger = DecisionLogger(db)
    logger.log_decision(
        trade_date="2026-09-29",
        symbol="RELIANCE",
        decision_type="ENTRY_ESCALATION",
        reason="Gray zone",
        momentum_snapshot={"momentum_1m": 10.0},
        escalated=True,
        llm_response={"action": "WAIT", "reasoning": "Volume declining"},
    )
    call_args = db.log_execution_decision.call_args
    assert call_args is not None


def test_recent_decisions():
    db = MagicMock()
    db.get_recent_execution_decisions.return_value = [
        {"type": "ENTRY_ENTER", "symbol": "RELIANCE", "time": "09:21:00"}
    ]
    logger = DecisionLogger(db)
    recent = logger.recent(limit=20)
    assert len(recent) == 1


def test_log_decision_swallows_db_error():
    """DecisionLogger should not propagate DB errors."""
    db = MagicMock()
    db.log_execution_decision.side_effect = RuntimeError("db locked")
    logger = DecisionLogger(db)
    # Should not raise
    logger.log_decision(
        trade_date="2026-09-29",
        symbol="RELIANCE",
        decision_type="EXIT",
        reason="trailing stop hit",
    )


def test_recent_returns_empty_on_error():
    """recent() should return [] on DB error, not propagate."""
    db = MagicMock()
    db.get_recent_execution_decisions.side_effect = RuntimeError("db locked")
    logger = DecisionLogger(db)
    assert logger.recent() == []
