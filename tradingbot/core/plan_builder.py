"""Convert approved setups from SetupStore into a sized TradePlan."""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Any

from tradingbot.core.models import (
    Direction,
    EntryType,
    IST,
    MarketRegime,
    StrategyName,
    TradePlan,
    TradeSetup,
)
from tradingbot.core.risk_manager import RiskManager
from tradingbot.persistence.setup_store import SetupStore

log = logging.getLogger(__name__)

DEFAULT_ENTRY_WINDOW_START = time(9, 20)
DEFAULT_ENTRY_WINDOW_END = time(10, 30)
DEFAULT_MAX_ENTRY_WAIT = time(11, 0)
DEFAULT_EXIT_BEFORE = time(15, 10)


class PlanBuilder:
    """Bridge between analysis (SetupStore) and execution (TradePlan)."""

    def __init__(
        self,
        setup_store: SetupStore,
        risk_manager: RiskManager,
        max_entry_wait: time = DEFAULT_MAX_ENTRY_WAIT,
        exit_before: time = DEFAULT_EXIT_BEFORE,
    ) -> None:
        self._setups = setup_store
        self._rm = risk_manager
        self._max_entry_wait = max_entry_wait
        self._exit_before = exit_before

    def build(
        self,
        trade_date: date,
        regime: MarketRegime = MarketRegime.RANGE_BOUND,
        market_summary: str = "",
    ) -> TradePlan:
        """Read approved setups, size them, return a TradePlan ready for execution."""
        rows = self._setups.get_active(trade_date)
        if not rows:
            log.info("No approved setups for %s", trade_date)
            return self._empty_plan(trade_date, regime, market_summary)

        setups = []
        for row in rows:
            try:
                setup = self._row_to_setup(row)
                setups.append(setup)
            except (KeyError, ValueError) as exc:
                log.warning("Skipping setup %s: %s", row.get("id"), exc)

        if not setups:
            return self._empty_plan(trade_date, regime, market_summary)

        legs = self._rm.select_legs(
            setups,
            max_entry_wait=self._max_entry_wait,
            exit_before=self._exit_before,
        )

        log.info(
            "Built plan for %s: %d setups → %d legs",
            trade_date, len(setups), len(legs),
        )

        return TradePlan(
            trade_date=str(trade_date),
            generated_at=datetime.now(tz=IST),
            capital=self._rm.capital,
            max_risk_per_trade_pct=self._rm.risk.max_risk_per_trade_pct,
            max_daily_loss_pct=self._rm.risk.max_daily_loss_pct,
            market_regime=regime,
            market_summary=market_summary or f"Auto-generated plan for {trade_date}",
            legs=legs,
        )

    @staticmethod
    def _row_to_setup(row: dict[str, Any]) -> TradeSetup:
        """Convert a SetupStore dict row into a TradeSetup with setup_id."""
        return TradeSetup(
            symbol=row["symbol"],
            strategy=StrategyName(row["strategy"]),
            direction=Direction(row["direction"]),
            entry_price=float(row["entry_price"]),
            entry_type=EntryType.LIMIT,
            stop_loss=float(row["stop_loss"]),
            target_1=float(row["target_1"]),
            target_2=float(row.get("target_2") or 0),
            entry_window_start=DEFAULT_ENTRY_WINDOW_START,
            entry_window_end=DEFAULT_ENTRY_WINDOW_END,
            confidence=float(row["confidence"]),
            reasoning=row.get("reasoning", ""),
            setup_id=row.get("id"),
        )

    @staticmethod
    def _empty_plan(
        trade_date: date,
        regime: MarketRegime,
        market_summary: str,
    ) -> TradePlan:
        return TradePlan(
            trade_date=str(trade_date),
            generated_at=datetime.now(tz=IST),
            capital=0,
            max_risk_per_trade_pct=0,
            max_daily_loss_pct=0,
            market_regime=regime,
            market_summary=market_summary or "No approved setups",
            legs=[],
        )
