"""AnalysisPipeline: single entry point for the 3-tier analysis funnel.

Orchestrates: Tier1Screen -> Tier2 (regime+sector+shortlist) -> deep data fetch
-> backtest each shortlisted stock -> Tier3 (per-stock deep analysis + adversarial)
-> persist runs+setups -> emit events.

Does NOT replace TradePlan — creates AnalysisRun + approved setups.
The old plan_generator still works for backward compat.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from tradingbot.core.models import AnalysisRun, MarketRegime

IST = ZoneInfo("Asia/Kolkata")
log = logging.getLogger(__name__)


class AnalysisPipeline:
    """Single entry point replacing PlanGenerator for the redesigned pipeline.

    All dependencies injected via constructor — no global state.
    """

    def __init__(
        self,
        data_sync: Any,
        candle_store: Any,
        screener: Any,
        tier2: Any,
        tier3: Any,
        backtest_engine: Any,
        monte_carlo: Any,
        quality_gates: Any,
        run_store: Any,
        setup_store: Any,
        event_bus: Any,
        capital: float,
    ):
        self._sync = data_sync
        self._candles = candle_store
        self._screener = screener
        self._tier2 = tier2
        self._tier3 = tier3
        self._backtest = backtest_engine
        self._mc = monte_carlo
        self._gates = quality_gates
        self._runs = run_store
        self._setups = setup_store
        self._bus = event_bus
        self._capital = capital

    async def run(self, trade_date: date) -> AnalysisRun:
        """Execute full analysis pipeline for a given trade date.

        Returns an AnalysisRun with stats about the run.
        """
        start = time.monotonic()
        run_id = f"run_{trade_date:%Y%m%d}_{datetime.now(tz=IST):%H%M%S}_{uuid.uuid4().hex[:6]}"
        llm_calls = 0

        self._bus.emit("analysis.started", {"run_id": run_id})

        # --- Tier 1: Deterministic screen ---
        stock_metrics = self._build_stock_metrics()
        scored = self._screener.screen(stock_metrics)
        self._bus.emit("analysis.tier1_complete", {"candidates": len(scored)})

        # --- Tier 2: LLM market + sector + shortlist ---
        regime = await self._tier2.analyze_regime(
            nifty=0, banknifty=0, vix=0, nifty_5d_change=0,
            fii_5d_net=0, dii_5d_net=0, advance_decline=0, sector_data={},
        )
        llm_calls += 1

        sectors = await self._tier2.analyze_sectors(regime, {}, {})
        llm_calls += 1

        scored_dicts = [
            {
                "symbol": s.symbol,
                "composite_score": s.composite_score,
                "sector": s.sector,
                "last_price": s.last_price,
                "factor_scores": s.factor_scores,
            }
            for s in scored
        ]
        shortlist_result = await self._tier2.shortlist(regime, sectors, scored_dicts)
        llm_calls += 1
        shortlist = shortlist_result.get("shortlist", [])

        self._bus.emit("analysis.tier2_complete", {"shortlisted": len(shortlist)})

        # Sync deep data for shortlisted symbols
        symbols = [s["symbol"] for s in shortlist]
        if symbols and hasattr(self._sync, "deep_fetch"):
            self._sync.deep_fetch(symbols)

        # --- Backtest + Tier 3: per-stock deep analysis ---
        all_setups: list[dict[str, Any]] = []
        for pick in shortlist:
            sym = pick["symbol"]
            direction = pick.get("direction", "long")

            # Run backtest across all registered strategies
            bt_results: list[Any] = []
            self._run_backtests(sym, bt_results)

            # Tier 3 deep analysis
            deep = await self._tier3.deep_analyze(
                symbol=sym,
                direction=direction,
                regime=regime,
                indicators={},
                backtest_results=[],
                price_action=f"{sym} analysis",
            )
            llm_calls += 1
            all_setups.append(deep)

        # --- Adversarial validation ---
        setups_with_data = [s for s in all_setups if s.get("setups")]
        setups_proposed = sum(len(s.get("setups", [])) for s in setups_with_data)
        setups_approved = 0

        if setups_with_data:
            validation = await self._tier3.validate_portfolio(
                setups_with_data, regime, sectors
            )
            llm_calls += 1

            for approved in validation.get("approved", []):
                sym = approved["symbol"]
                idx = approved.get("setup_index", 0)
                source = next(
                    (s for s in setups_with_data if s["symbol"] == sym), None
                )
                if source and idx < len(source.get("setups", [])):
                    setup_data = source["setups"][idx]
                    self._setups.save({
                        "run_id": run_id,
                        "trade_date": str(trade_date),
                        "symbol": sym,
                        "strategy": setup_data.get("strategy", "unknown"),
                        "direction": setup_data.get("direction", "long"),
                        "entry_price": setup_data["entry_price"],
                        "stop_loss": setup_data["stop_loss"],
                        "target_1": setup_data["target_1"],
                        "target_2": setup_data.get("target_2", 0),
                        "confidence": setup_data["confidence"],
                        "status": "approved",
                        "reasoning": setup_data.get("edge_description", ""),
                    })
                    setups_approved += 1

        # --- Persist and emit completion ---
        duration = time.monotonic() - start
        regime_enum = MarketRegime(regime.get("regime", "range_bound"))

        analysis_run = AnalysisRun(
            run_id=run_id,
            timestamp=datetime.now(tz=IST),
            trade_date=trade_date,
            market_regime=regime_enum,
            regime_confidence=regime.get("regime_confidence", 0),
            total_scanned=len(stock_metrics),
            tier1_passed=len(scored),
            tier2_shortlisted=len(shortlist),
            setups_proposed=setups_proposed,
            setups_approved=setups_approved,
            llm_calls=llm_calls,
            llm_cost_usd=0,
            duration_seconds=duration,
        )
        self._runs.save(analysis_run)
        self._bus.emit("analysis.complete", {"run_id": run_id})

        log.info(
            "Pipeline complete: %s | regime=%s | scanned=%d | t1=%d | t2=%d | "
            "proposed=%d | approved=%d | llm=%d | %.1fs",
            run_id, regime_enum.value, len(stock_metrics), len(scored),
            len(shortlist), setups_proposed, setups_approved, llm_calls, duration,
        )
        return analysis_run

    def _build_stock_metrics(self) -> list[dict]:
        """Reads from candle store to compute metrics for all instruments.

        TODO: Real implementation needs InstrumentCache populated by DataSync.
        For now returns empty list — Tier 1 screen produces zero candidates,
        and the pipeline proceeds with Tier 2 LLM analysis using whatever
        scored stocks came through (none in this case).
        """
        return []

    def _run_backtests(self, symbol: str, results: list) -> None:
        """Run backtest across registered strategies for one symbol.

        Appends passing BacktestReports to results list.
        """
        from tradingbot.strategy.strategies import STRATEGY_REGISTRY

        for _name, strategy in STRATEGY_REGISTRY.items():
            df = self._candles.read(
                symbol, "15minute",
                datetime(2025, 1, 1, tzinfo=IST),
                datetime.now(tz=IST),
            )
            if len(df) > 0:
                report = self._backtest.run(symbol, df, strategy)
                if report.total_trades >= 5:
                    mc = self._mc.run([report.expectancy] * report.total_trades)
                    gate = self._gates.evaluate(report, mc)
                    if gate.passed:
                        results.append(report)
