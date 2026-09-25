"""Ties the analysis phase together and writes the TradePlan artifact."""

from __future__ import annotations

import logging
from datetime import date, time

from tradingbot.core.config import StrategyConfig
from tradingbot.core.models import (
    BacktestResult,
    IndicatorSnapshot,
    TradePlan,
    now_ist,
)
from tradingbot.core.plan_store import PlanStore
from tradingbot.core.risk_manager import RiskManager
from tradingbot.strategy.backtester import Backtester
from tradingbot.strategy.indicators import compute_snapshot

logger = logging.getLogger(__name__)

DEFAULT_MAX_ENTRY_WAIT = time(11, 0)
DEFAULT_EXIT_BEFORE = time(15, 10)

INTERVAL_TO_YFINANCE = {
    "5minute": "5m",
    "15minute": "15m",
    "30minute": "30m",
    "60minute": "60m",
}


class PlanGenerator:
    """Scan, analyse, size, and persist the plan for one trade date."""

    def __init__(
        self,
        scanner,
        fetcher,
        selector,
        risk_manager: RiskManager,
        plan_store: PlanStore,
        strategy_config: StrategyConfig,
        capital: float,
        backtester: Backtester | None = None,
        max_entry_wait: time = DEFAULT_MAX_ENTRY_WAIT,
        exit_before: time = DEFAULT_EXIT_BEFORE,
        event_bus=None,
    ) -> None:
        self.scanner = scanner
        self.fetcher = fetcher
        self.selector = selector
        self.risk_manager = risk_manager
        self.plan_store = plan_store
        self.config = strategy_config
        self.capital = capital
        self.backtester = backtester or Backtester()
        self.max_entry_wait = max_entry_wait
        self.exit_before = exit_before
        self.event_bus = event_bus

    async def generate(self, trade_date: date) -> TradePlan:
        scan = await self.scanner.scan(trade_date)

        snapshots: dict[str, IndicatorSnapshot] = {}
        backtests: dict[str, list[BacktestResult]] = {}
        usable = []

        interval = INTERVAL_TO_YFINANCE.get(self.config.candle_interval, "15m")

        for stock in scan.shortlist:
            try:
                candles = self.fetcher.fetch_candles(
                    stock.symbol, days=self.config.backtest_days, interval=interval
                )
                snapshots[stock.symbol] = compute_snapshot(stock.symbol, candles)
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the run
                logger.warning("skipping %s: %s", stock.symbol, exc)
                continue

            if self.event_bus:
                await self.event_bus.emit("strategy.indicators", snapshots[stock.symbol].to_dict())

            backtests[stock.symbol] = self.backtester.run_all(stock.symbol, candles)
            if self.event_bus:
                await self.event_bus.emit("strategy.backtest", {
                    "symbol": stock.symbol,
                    "results": [r.to_dict() for r in backtests[stock.symbol]],
                })
            usable.append(stock)

        setups = await self.selector.design_setups(usable, snapshots, backtests, scan.context)
        logger.info("LLM returned %d setups for %d usable symbols", len(setups), len(usable))
        if self.event_bus:
            await self.event_bus.emit("strategy.setups", {
                "count": len(setups),
                "setups": [{"symbol": s.symbol, "strategy": s.strategy.value, "direction": s.direction.value, "entry_price": s.entry_price, "stop_loss": s.stop_loss, "target_1": s.target_1, "confidence": s.confidence} for s in setups],
            })

        legs = self.risk_manager.select_legs(
            setups, max_entry_wait=self.max_entry_wait, exit_before=self.exit_before
        )
        logger.info("risk manager approved %d legs", len(legs))
        if self.event_bus:
            await self.event_bus.emit("strategy.sized", {
                "approved": [{"symbol": l.symbol, "quantity": l.quantity, "risk_amount": l.risk_amount} for l in legs],
                "dropped": [],
            })

        plan = TradePlan(
            trade_date=trade_date.isoformat(),
            generated_at=now_ist(),
            capital=self.capital,
            max_risk_per_trade_pct=self.risk_manager.risk.max_risk_per_trade_pct,
            max_daily_loss_pct=self.risk_manager.risk.max_daily_loss_pct,
            market_regime=scan.context.regime,
            market_summary=(
                f"Nifty {scan.context.nifty_level:.0f} ({scan.context.nifty_trend}), "
                f"VIX {scan.context.india_vix:.2f}, "
                f"FII {scan.context.fii_net_cr:+.0f} Cr, DII {scan.context.dii_net_cr:+.0f} Cr"
            ),
            legs=legs,
        )

        self.plan_store.save(plan)
        return plan
