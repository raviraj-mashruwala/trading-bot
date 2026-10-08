"""Logs execution decisions to the database for audit and replay."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class DecisionLogger:
    def __init__(self, database) -> None:
        self._db = database

    def log_decision(
        self,
        trade_date: str,
        symbol: str,
        decision_type: str,
        reason: str,
        momentum_snapshot: dict[str, Any] | None = None,
        candle_snapshot: dict[str, Any] | None = None,
        escalated: bool = False,
        llm_response: dict[str, Any] | None = None,
    ) -> None:
        try:
            self._db.log_execution_decision(
                trade_date=trade_date,
                timestamp=datetime.now().isoformat(),
                symbol=symbol,
                decision_type=decision_type,
                reason=reason,
                momentum_snapshot=json.dumps(momentum_snapshot) if momentum_snapshot else None,
                candle_snapshot=json.dumps(candle_snapshot) if candle_snapshot else None,
                escalated=escalated,
                llm_response=json.dumps(llm_response) if llm_response else None,
            )
        except Exception:
            logger.warning("Failed to log decision", exc_info=True)

    def update_outcome(self, trade_date: str, symbol: str, outcome: str) -> None:
        try:
            self._db.update_decision_outcome(trade_date, symbol, outcome)
        except Exception:
            logger.warning("Failed to update decision outcome", exc_info=True)

    def recent(self, limit: int = 20) -> list[dict]:
        try:
            return self._db.get_recent_execution_decisions(limit=limit)
        except Exception:
            return []
