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
            def _safe_json(obj):
                if obj is None:
                    return None
                try:
                    return json.dumps(obj, default=str)
                except Exception:
                    return str(obj)

            self._db.log_execution_decision(
                trade_date=str(trade_date),
                timestamp=datetime.now().isoformat(),
                symbol=str(symbol),
                decision_type=str(decision_type),
                reason=str(reason) if reason is not None else None,
                momentum_snapshot=_safe_json(momentum_snapshot),
                candle_snapshot=_safe_json(candle_snapshot),
                escalated=escalated,
                llm_response=_safe_json(llm_response),
            )
        except Exception:
            pass

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
