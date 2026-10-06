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
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tradingbot.core.llm.provider import LLMUsage
from tradingbot.core.models import AnalysisRun, MarketRegime
from tradingbot.persistence.review_store import TradeReviewStore
from tradingbot.screening.candlestick import score_patterns as _score_candlestick
from tradingbot.screening.volume_profile_score import score_volume_profile as _score_volume_profile

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
        instrument_cache: Any = None,
        context_fetcher: Any = None,
        lookback_days: int = 365,
        db_path: Any = None,
        market_data_provider: Any = None,
        screening_config: Any = None,
        jev_config: Any = None,
        duckdb_store: Any = None,
    ):
        self._sync = data_sync
        self._candles = candle_store
        self._duckdb = duckdb_store
        self._db_path = db_path
        self._instrument_cache = instrument_cache
        self._provider = market_data_provider
        self._context_fetcher = context_fetcher
        self._screener = screener
        self._tier2 = tier2
        self._tier3 = tier3
        self._backtest = backtest_engine
        self._mc = monte_carlo
        self._gates = quality_gates
        self._lookback_days = lookback_days
        self._runs = run_store
        self._setups = setup_store
        self._bus = event_bus
        self._capital = capital
        self._screening = screening_config
        self._approved_setup_ids: dict[str, int] = {}

        # Intelligent screener wraps deterministic screener with Jev layer
        self._intelligent_screener = None
        if jev_config and getattr(jev_config, "enabled", False):
            from tradingbot.core.jev_client import JevClient
            _jev_for_screening = JevClient(jev_config)
            if _jev_for_screening.available:
                from tradingbot.screening.intelligent_screener import IntelligentScreener
                self._intelligent_screener = IntelligentScreener(
                    screening_config, jev_client=_jev_for_screening,
                ) if screening_config else None

        self._jev_tier2 = None
        if jev_config and getattr(jev_config, "enabled", False):
            from tradingbot.core.jev_client import JevClient
            jev_client = JevClient(jev_config)
            if jev_client.available:
                from tradingbot.analysis.jev_tier2 import JevTier2Analyzer
                self._jev_tier2 = JevTier2Analyzer(jev_client)

    async def run(self, trade_date: date) -> AnalysisRun:
        """Execute full analysis pipeline for a given trade date.

        Returns an AnalysisRun with stats about the run.
        """
        start = time.monotonic()
        run_id = f"run_{trade_date:%Y%m%d}_{datetime.now(tz=IST):%H%M%S}_{uuid.uuid4().hex[:6]}"
        llm_calls = 0
        total_cost = 0.0

        await self._bus.emit("analysis.started", {"run_id": run_id})

        # --- Cancellation support ---
        import asyncio as _aio
        _current_task = _aio.current_task()

        def _is_cancelled() -> bool:
            return _current_task is not None and _current_task.cancelled()

        # --- Tier 1: Deterministic screen ---

        market_ctx = await _aio.to_thread(self._fetch_market_context)
        self._bus.emit_sync("scan.context", {"regime": market_ctx.regime.value})

        instruments = await _aio.to_thread(self._fetch_universe)
        self._bus.emit_sync("scan.universe", {"total": len(instruments), "status": "fetching"})

        nifty_5d_change = await _aio.to_thread(self._compute_nifty_5d_change_from_store)
        delivery_data = await _aio.to_thread(self._fetch_delivery_data, trade_date)
        stock_metrics = await _aio.to_thread(
            self._build_stock_metrics_from_instruments,
            instruments, nifty_5d_change, delivery_data,
        )
        self._bus.emit_sync("scan.universe", {"total": len(stock_metrics)})

        if self._intelligent_screener is not None:
            scored = self._intelligent_screener.screen(
                stock_metrics,
                regime=market_ctx.regime.value,
                regime_confidence=0.7,
            )
        else:
            scored = self._screener.screen(stock_metrics)
        self._bus.emit_sync("scan.filtered", {"candidates": len(scored)})
        await self._bus.emit("analysis.tier1_complete", {"candidates": len(scored)})

        # --- Tier 2: regime + sectors (Jev when available, Claude fallback) ---
        sector_data = {s: 0.0 for s in (market_ctx.sector_leaders + market_ctx.sector_laggards)}
        _regime_args = dict(
            nifty=market_ctx.nifty_level, banknifty=0,
            vix=market_ctx.india_vix, nifty_5d_change=nifty_5d_change,
            fii_5d_net=market_ctx.fii_net_cr, dii_5d_net=market_ctx.dii_net_cr,
            advance_decline=0, sector_data=sector_data,
        )

        regime = None
        if self._jev_tier2 is not None:
            regime = await self._jev_tier2.analyze_regime(**_regime_args)
        if regime is None:
            regime = await self._tier2.analyze_regime(**_regime_args)
            llm_calls += 1
            if isinstance(regime.get("_usage"), LLMUsage):
                total_cost += regime.pop("_usage").cost_usd()

        sectors = None
        if self._jev_tier2 is not None:
            sectors = await self._jev_tier2.analyze_sectors(regime, {}, {})
        if sectors is None:
            sectors = await self._tier2.analyze_sectors(regime, {}, {})
            llm_calls += 1
            if isinstance(sectors.get("_usage") if isinstance(sectors, dict) else None, LLMUsage):
                total_cost += sectors.pop("_usage").cost_usd()

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

        if self._jev_tier2 is not None:
            from tradingbot.analysis.jev_shortlist_scorer import score_candidates
            regime_str = regime.get("regime", "range_bound") if isinstance(regime, dict) else "range_bound"

            def _jev_progress(msg: str) -> None:
                self._bus.emit_sync("scan.shortlist", {"status": "fetching", "message": msg})

            scored_dicts = await _aio.to_thread(
                score_candidates,
                self._jev_tier2._jev, scored_dicts, regime_str,
                0.0, _jev_progress, _is_cancelled,
            )
            log.info("Jev pre-scored %d candidates, top: %s", len(scored_dicts),
                     [(s["symbol"], s.get("jev_composite")) for s in scored_dicts[:5]])

        shortlist_result = await self._tier2.shortlist(regime, sectors, scored_dicts)
        llm_calls += 1
        if isinstance(shortlist_result.get("_usage"), LLMUsage):
            total_cost += shortlist_result.pop("_usage").cost_usd()
        shortlist = shortlist_result.get("shortlist", [])

        self._bus.emit_sync("scan.shortlist", {"shortlisted": len(shortlist)})
        await self._bus.emit("analysis.tier2_complete", {"shortlisted": len(shortlist)})

        # --- Fetch intraday data for shortlisted stocks (on-demand from Kite) ---
        symbols = [s["symbol"] for s in shortlist]
        if symbols and getattr(self, '_duckdb', None) is not None:
            self._bus.emit_sync("strategy.indicators", {
                "status": "fetching", "message": f"Fetching intraday data for {len(symbols)} stocks...",
            })
            try:
                from tradingbot.data.kite_data_sync import KiteDataSync
                from tradingbot.data.kite_client import KiteClient
                from kiteconnect import KiteConnect
                from pathlib import Path
                import os

                config = getattr(self, '_config', None)
                token_path = Path.home() / ".tradingbot" / "kite_token"
                kite_api_key = os.environ.get("KITE_API_KEY", "")
                if token_path.exists() and kite_api_key:
                    kite = KiteConnect(api_key=kite_api_key)
                    kite.set_access_token(token_path.read_text().strip())
                    kite_client = KiteClient(kite, rate_limit_per_sec=3)

                    sync = KiteDataSync(kite_client, self._duckdb, self._instrument_cache)

                    def _progress(msg):
                        self._bus.emit_sync("strategy.indicators", {"status": "fetching", "message": msg})

                    await sync.fetch_shortlist_data(symbols, progress_callback=_progress)
                else:
                    log.warning("Kite auth not available — skipping intraday fetch")
            except Exception as exc:
                log.warning("On-demand intraday fetch failed: %s", exc, exc_info=True)

        # --- Performance context for LLM ---
        perf_ctx = self._build_performance_context()

        # --- Backtest + Tier 3: per-stock deep analysis ---
        all_setups: list[dict[str, Any]] = []
        all_bt_results: dict[str, list[dict]] = {}
        if not shortlist:
            self._bus.emit_sync("strategy.indicators", {"status": "skipped", "reason": "no shortlisted stocks"})
            self._bus.emit_sync("strategy.backtest", {"status": "skipped", "reason": "no shortlisted stocks"})
        for i, pick in enumerate(shortlist):
            if _is_cancelled():
                log.info("Pipeline cancelled during backtest/analysis at %d/%d", i, len(shortlist))
                break
            sym = pick["symbol"]
            direction = pick.get("direction", "long")

            # Run backtest for regime-eligible strategies only
            bt_results: list[Any] = []
            self._run_backtests(sym, bt_results, regime=regime)
            all_bt_results[sym] = bt_results
            self._bus.emit_sync("strategy.backtest", {
                "symbol": sym, "progress": f"{i+1}/{len(shortlist)}",
                "strategies_passed": len(bt_results),
            })

            # Fetch real indicators and price action for Claude's context
            indicators, price_action = self._fetch_indicators_for_symbol(sym)
            self._bus.emit_sync("strategy.indicators", {
                "symbol": sym, "progress": f"{i+1}/{len(shortlist)}",
                "has_data": bool(indicators),
            })

            if not indicators:
                log.warning("Skipping %s — no indicator data, would waste LLM call", sym)
                continue

            # Tier 3 deep analysis
            self._bus.emit_sync("strategy.deep_analysis", {
                "symbol": sym, "progress": f"{i+1}/{len(shortlist)}",
                "status": "fetching", "message": f"Analyzing {sym} ({i+1}/{len(shortlist)})",
            })
            deep = await self._tier3.deep_analyze(
                symbol=sym,
                direction=direction,
                regime=regime,
                indicators=indicators,
                backtest_results=bt_results,
                price_action=price_action,
                performance_context=perf_ctx,
            )
            llm_calls += 1
            if isinstance(deep.get("_usage") if isinstance(deep, dict) else None, LLMUsage):
                total_cost += deep.pop("_usage").cost_usd()
            all_setups.append(deep)
            n_setups = len(deep.get("setups", [])) if isinstance(deep, dict) else 0
            self._bus.emit_sync("strategy.deep_analysis", {
                "symbol": sym, "progress": f"{i+1}/{len(shortlist)}",
                "setups_found": n_setups,
            })

        self._bus.emit_sync("strategy.setups", {
            "total_setups": sum(len(s.get("setups", [])) for s in all_setups),
            "symbols_analyzed": len(shortlist),
        })

        # --- Adversarial validation ---
        no_setup_symbols = [s["symbol"] for s in all_setups if not s.get("setups")]
        if no_setup_symbols:
            log.info("LLM returned no setups for: %s", ", ".join(no_setup_symbols))

        setups_with_data = [s for s in all_setups if s.get("setups")]
        pre_corr = sum(len(s.get("setups", [])) for s in setups_with_data)
        setups_with_data = self._drop_correlated_setups(setups_with_data)
        setups_proposed = sum(len(s.get("setups", [])) for s in setups_with_data)
        if pre_corr > setups_proposed:
            log.info("Correlation filter dropped %d setups", pre_corr - setups_proposed)
        setups_approved = 0

        log.info(
            "FUNNEL: %d screened → %d shortlisted → %d with setups → %d proposed",
            len(stock_metrics), len(shortlist), len(setups_with_data), setups_proposed,
        )

        if setups_with_data:
            validation = await self._tier3.validate_portfolio(
                setups_with_data, regime, sectors
            )
            llm_calls += 1
            if isinstance(validation.get("_usage") if isinstance(validation, dict) else None, LLMUsage):
                total_cost += validation.pop("_usage").cost_usd()

            for rejected in validation.get("rejected", []):
                log.info(
                    "ADVERSARIAL REJECTED %s: %s",
                    rejected.get("symbol", "?"), rejected.get("reason", "no reason"),
                )

            for approved in validation.get("approved", []):
                sym = approved["symbol"]
                idx = approved.get("setup_index", 0)
                source = next(
                    (s for s in setups_with_data if s["symbol"] == sym), None
                )
                if source and idx < len(source.get("setups", [])):
                    setup_data = source["setups"][idx]

                    # Jev quality check — overfit/credibility gate
                    if self._jev_tier2 is not None:
                        from tradingbot.analysis.jev_quality_check import jev_quality_check
                        sym_bt = all_bt_results.get(sym, [])
                        bt_stats = sym_bt[0] if sym_bt else {}
                        qc = await jev_quality_check(
                            self._jev_tier2._jev, setup_data,
                            {"win_rate": bt_stats.get("win_rate", 0),
                             "profit_factor": bt_stats.get("profit_factor", 0),
                             "max_drawdown": bt_stats.get("max_drawdown_pct", 0),
                             "n_trades": bt_stats.get("total_trades", 0),
                             "avg_r": bt_stats.get("expectancy_r", 0)},
                        )
                        if not qc["pass"]:
                            log.info(
                                "JEV QUALITY REJECTED %s: score=%.2f, overfit=%.2f, credible=%.2f",
                                sym, qc["quality_score"],
                                qc["details"].get("overfit_risk", 0),
                                qc["details"].get("backtest_credible", 0),
                            )
                            continue

                    row_id = self._setups.save({
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
                        "thesis": setup_data.get("edge_description", ""),
                        "invalidation_condition": setup_data.get("invalidation", ""),
                        "bear_case": setup_data.get("bear_case", ""),
                        "confluence_count": setup_data.get("confluence_count", 0),
                        "entry_trigger": setup_data.get("entry_trigger", ""),
                        "regime_at_generation": regime.get("regime", ""),
                        "timeframe_alignment": setup_data.get("timeframe_alignment", []),
                    })
                    strategy_key = f"{sym}:{setup_data.get('strategy', 'unknown')}"
                    self._approved_setup_ids[strategy_key] = row_id
                    setups_approved += 1

        self._bus.emit_sync("strategy.sized", {
            "proposed": setups_proposed,
            "approved": setups_approved,
        })

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
            llm_cost_usd=total_cost,
            duration_seconds=duration,
        )
        self._runs.save(analysis_run)
        await self._bus.emit("analysis.complete", {"run_id": run_id})

        log.info(
            "Pipeline complete: %s | regime=%s | scanned=%d | t1=%d | t2=%d | "
            "proposed=%d | approved=%d | llm=%d | %.1fs",
            run_id, regime_enum.value, len(stock_metrics), len(scored),
            len(shortlist), setups_proposed, setups_approved, llm_calls, duration,
        )
        return analysis_run

    def _fetch_universe(self) -> list[dict]:
        """Fetch instrument universe (fast — 1 Kite API call)."""
        if self._provider is not None:
            price_kwargs: dict = {}
            if self._screening is not None:
                price_kwargs["min_price"] = self._screening.min_price
                price_kwargs["max_price"] = self._screening.max_price
            return self._provider.get_universe(**price_kwargs)
        elif self._instrument_cache is not None:
            return self._instrument_cache.get_all()
        return []

    def _build_stock_metrics(
        self, nifty_5d_change: float = 0.0, delivery_data: dict | None = None
    ) -> list[dict]:
        """Compute all 9 screening factor scores for all instruments."""
        instruments = self._fetch_universe()
        return self._build_stock_metrics_from_instruments(
            instruments, nifty_5d_change, delivery_data,
        )

    def _build_stock_metrics_from_instruments(
        self,
        instruments: list[dict],
        nifty_5d_change: float = 0.0,
        delivery_data: dict | None = None,
    ) -> list[dict]:
        """Compute screening factor scores from pre-fetched instruments."""
        if not instruments:
            return []

        import statistics
        import pandas as pd
        from datetime import timedelta

        now = datetime.now(tz=IST)
        from_dt = now - timedelta(days=30)

        symbols = [inst["symbol"] for inst in instruments]
        inst_map = {inst["symbol"]: inst for inst in instruments}

        daily_data = {}
        if getattr(self, '_duckdb', None) is not None:
            daily_data = self._duckdb.read_batch(symbols, "day", days=30)
        if not daily_data and self._candles is not None:
            for sym in symbols:
                df = self._candles.read(sym, "day", from_dt, now)
                if not df.empty:
                    daily_data[sym] = df
        log.info("FUNNEL: %d instruments, %d with daily data in DuckDB", len(symbols), len(daily_data))

        sector_returns: dict[str, list[float]] = {}
        metrics = []
        skipped_short = 0

        for symbol, df in daily_data.items():
            if df.empty or len(df) < 5:
                skipped_short += 1
                continue
            inst = inst_map.get(symbol, {"symbol": symbol, "token": 0, "sector": "unknown"})

            close = df["close"]
            volume = df["volume"]
            last_price = float(close.iloc[-1])
            avg_volume = float(volume.tail(20).mean())
            trading_days = len(df)

            high, low, prev_close_s = df["high"], df["low"], close.shift(1)
            true_range = pd.concat(
                [high - low, (high - prev_close_s).abs(), (low - prev_close_s).abs()],
                axis=1,
            ).max(axis=1)
            atr = float(true_range.tail(min(14, len(df))).mean())
            atr_pct = (atr / last_price * 100) if last_price > 0 else 0

            # Gap analysis: today open vs yesterday close
            gap_score = 0.0
            if len(df) >= 2:
                prev_c = float(close.iloc[-2])
                today_open = float(df["open"].iloc[-1])
                if prev_c > 0:
                    gap_pct = abs(today_open - prev_c) / prev_c * 100
                    gap_score = min(100.0, gap_pct * 33.3)

            # Volume surge: today vs 20d avg
            vol_today = float(volume.iloc[-1])
            vol_surge_pct = ((vol_today / avg_volume) - 1) * 100 if avg_volume > 0 else 0
            volume_surge_score = min(100.0, max(0.0, vol_surge_pct * 2))

            # Relative strength vs Nifty (5d return excess)
            stock_5d_return = 0.0
            if len(close) >= 6:
                stock_5d_return = (float(close.iloc[-1]) / float(close.iloc[-6]) - 1) * 100
            rs_excess = stock_5d_return - nifty_5d_change
            relative_strength_score = min(100.0, max(0.0, 50.0 + rs_excess * 5.0))

            # ATR expansion (2% ATR = 100 score)
            atr_expansion_score = min(100.0, max(0.0, atr_pct * 50.0))

            # Price structure: close vs SMA20
            sma20 = float(close.tail(20).mean()) if len(close) >= 20 else last_price
            pct_above = ((last_price - sma20) / sma20 * 100) if sma20 > 0 else 0
            price_structure_score = min(100.0, max(0.0, 50.0 + pct_above * 5.0))

            sector = inst.get("sector", "unknown")
            sector_returns.setdefault(sector, []).append(stock_5d_return)

            market_cap_cr = last_price * avg_volume / 1_00_00_000

            metrics.append({
                "symbol": symbol,
                "token": inst["token"],
                "last_price": last_price,
                "avg_volume": avg_volume,
                "market_cap_cr": market_cap_cr,
                "atr_pct": atr_pct,
                "sector": sector,
                "trading_days": trading_days,
                "_stock_5d_return": stock_5d_return,
                "factor_scores": {
                    "gap_analysis": gap_score,
                    "volume_surge": volume_surge_score,
                    "relative_strength": relative_strength_score,
                    "atr_expansion": atr_expansion_score,
                    "price_structure": price_structure_score,
                    "delivery_pct": (delivery_data or {}).get(symbol, 50.0),
                    "candlestick_pattern": _score_candlestick(df),
                    "volume_profile": _score_volume_profile(df),
                    "sector_momentum": 50.0,  # filled in second pass
                },
            })

        # Second pass: fill sector_momentum from median sector 5d return
        sector_median: dict[str, float] = {
            s: statistics.median(returns)
            for s, returns in sector_returns.items()
            if returns
        }
        for m in metrics:
            med = sector_median.get(m["sector"], 0.0)
            m["factor_scores"]["sector_momentum"] = min(100.0, max(0.0, 50.0 + med * 5.0))
            del m["_stock_5d_return"]

        log.info("FUNNEL: %d skipped (< 5 rows), %d metrics built", skipped_short, len(metrics))
        return metrics

    def _fetch_delivery_data(self, trade_date: "date") -> dict[str, float]:
        """Fetch NSE delivery % from bhav copy. Returns {} on failure."""
        try:
            from tradingbot.data.delivery_fetcher import fetch_delivery_pct
            return fetch_delivery_pct(trade_date)
        except Exception as exc:
            log.warning("Delivery data fetch failed: %s", exc)
            return {}

    def _compute_nifty_5d_change_from_store(self) -> float:
        """5-day Nifty50 return. Uses provider or CandleStore fallback."""
        try:
            df = None
            if getattr(self, '_duckdb', None) is not None:
                df = self._duckdb.read("NIFTY 50", "day", days=10)
            if (df is None or df.empty) and self._candles is not None:
                df = self._candles.read(
                    "NIFTY 50", "day",
                    datetime.now(tz=IST) - timedelta(days=self._lookback_days),
                    datetime.now(tz=IST),
                )
            if df is None or df.empty:
                return 0.0
            if len(df) >= 6:
                return float((df["close"].iloc[-1] / df["close"].iloc[-6] - 1) * 100)
        except Exception:
            pass
        return 0.0

    def _fetch_market_context(self) -> "MarketContext":
        """Fetch real market data, with safe defaults on failure."""
        from tradingbot.core.models import MarketContext

        if self._context_fetcher is None:
            return self._default_context()
        try:
            return self._context_fetcher.fetch()
        except Exception:
            log.warning("MarketContextFetcher failed, using defaults")
            return self._default_context()

    def _default_context(self) -> "MarketContext":
        from tradingbot.core.models import MarketContext

        return MarketContext(
            nifty_level=0, nifty_trend="unknown", banknifty_trend="unknown",
            india_vix=15.0, fii_net_cr=0, dii_net_cr=0,
            global_cues="unavailable", sector_leaders=[], sector_laggards=[],
            regime=MarketRegime.RANGE_BOUND,
        )

    def _fetch_indicators_for_symbol(self, symbol: str) -> tuple[dict, str]:
        """Compute IndicatorSnapshot and price action summary for one symbol.

        Returns (indicators_dict, price_action_str). Returns ({}, fallback) on failure
        so a single bad symbol never aborts the whole shortlist loop.
        """
        from tradingbot.strategy.indicators import compute_snapshot, InsufficientDataError

        try:
            df = None
            if getattr(self, '_duckdb', None) is not None:
                df = self._duckdb.read(symbol, "15m", days=60)
            if (df is None or df.empty) and self._candles is not None:
                from_dt = datetime.now(tz=IST) - timedelta(days=self._lookback_days)
                df = self._candles.read(symbol, "15minute", from_dt, datetime.now(tz=IST))
            if df is None:
                import pandas as _pd
                df = _pd.DataFrame()
            if df.empty or len(df) < 30:
                return {}, f"{symbol}: insufficient candle data for indicators"

            snap = compute_snapshot(symbol, df)
            indicators = snap.to_dict()
            price_action = self._build_price_action_summary(symbol, df, snap)
            return indicators, price_action

        except InsufficientDataError:
            return {}, f"{symbol}: insufficient data for indicators"
        except Exception as exc:
            log.warning("Indicator fetch failed for %s: %s", symbol, exc)
            return {}, f"{symbol}: indicator computation failed"

    def _build_price_action_summary(self, symbol: str, df: Any, snap: Any) -> str:
        """Build compact price action narrative for Claude's deep analysis context."""
        last_5 = df.tail(5)[["open", "high", "low", "close", "volume"]].to_dict("records")
        return (
            f"{symbol} last 5 candles (15m): {last_5}\n"
            f"VWAP: {snap.vwap:.2f} | RSI14: {snap.rsi_14:.1f} | "
            f"ATR14: {snap.atr_14:.2f} | ADX14: {snap.adx_14:.1f}\n"
            f"BB: [{snap.bb_lower:.2f}, {snap.bb_middle:.2f}, {snap.bb_upper:.2f}] "
            f"BW: {snap.bb_bandwidth:.3f}\n"
            f"Support: {snap.support_levels} | Resistance: {snap.resistance_levels}\n"
            f"Supertrend: {snap.supertrend:.2f} "
            f"({'up' if snap.supertrend_direction == 1 else 'down'})"
        )

    def _drop_correlated_setups(self, setups_with_data: list[dict]) -> list[dict]:
        """Drop lower-confidence setups when two symbols have ρ > 0.7 on 20d returns.

        Uses confidence-sorted greedy: process symbols highest-confidence first,
        keep a symbol if it is not correlated with any already-kept symbol.
        This avoids the greedy pair-iteration bug where a symbol is dropped via a
        hub that itself gets dropped (hub-and-spoke over-drop).
        """
        import numpy as np

        if len(setups_with_data) <= 1:
            return setups_with_data

        def _max_conf(sym_: str) -> float:
            return max(
                (st.get("confidence", 0)
                 for st in next(
                     (x["setups"] for x in setups_with_data if x["symbol"] == sym_), []
                 )),
                default=0.0,
            )

        symbol_returns: dict[str, list[float]] = {}
        corr_symbols = [s["symbol"] for s in setups_with_data]
        corr_data = {}
        if getattr(self, '_duckdb', None) is not None and corr_symbols:
            corr_data = self._duckdb.read_batch(corr_symbols, "day", days=30)
        # corr_data from DuckDB only — no yfinance fallback
        for s in setups_with_data:
            sym = s["symbol"]
            try:
                if sym in corr_data:
                    df = corr_data[sym]
                elif self._candles is not None:
                    df = self._candles.read(
                        sym, "day",
                        datetime.now(tz=IST) - timedelta(days=self._lookback_days),
                        datetime.now(tz=IST),
                    )
                else:
                    continue
                if len(df) >= 20:
                    symbol_returns[sym] = df["close"].tail(20).pct_change().dropna().tolist()
            except Exception:
                pass

        # Sort highest-confidence first; symbols with no return data pass through
        all_syms = [s["symbol"] for s in setups_with_data]
        with_data = sorted(
            [s for s in all_syms if s in symbol_returns],
            key=_max_conf,
            reverse=True,
        )
        no_data = [s for s in all_syms if s not in symbol_returns]

        kept: list[str] = []
        for candidate in with_data:
            r_cand = symbol_returns[candidate]
            correlated_with_kept = False
            for kept_sym in kept:
                r_kept = symbol_returns[kept_sym]
                n = min(len(r_cand), len(r_kept))
                if n < 10:
                    continue
                rho = float(np.corrcoef(r_cand[-n:], r_kept[-n:])[0, 1])
                if rho > 0.7:
                    correlated_with_kept = True
                    log.info(
                        "Correlation drop: ρ=%.2f %s↔%s (kept) → drop %s",
                        rho, candidate, kept_sym, candidate,
                    )
                    break
            if not correlated_with_kept:
                kept.append(candidate)

        survivors = set(kept) | set(no_data)
        return [s for s in setups_with_data if s["symbol"] in survivors]

    def _build_performance_context(self, lookback_days: int = 30) -> str:
        """Compact performance summary for LLM context. Empty if < 10 trades."""
        try:
            from pathlib import Path
            if self._db_path is None:
                return ""
            rs = TradeReviewStore(Path(self._db_path))
            try:
                stats = rs.get_performance_stats(lookback_days)
            finally:
                rs.close()
        except Exception:
            return ""

        if stats.total_trades < 10:
            return ""

        lines = [
            f"RECENT PERFORMANCE ({stats.period_days}d):",
            f"{stats.total_trades} trades, {stats.win_rate:.1%} win rate, "
            f"avg R: {stats.avg_r_multiple:.1f}, total PnL: {stats.total_pnl:+,.0f}",
        ]

        if stats.by_strategy:
            strats = ", ".join(
                f"{k} {v.win_rate:.0%} ({v.trades}t)"
                for k, v in sorted(stats.by_strategy.items(), key=lambda x: -x[1].trades)
            )
            lines.append(f"By strategy: {strats}")

        if stats.by_regime:
            regs = ", ".join(
                f"{k} {v.win_rate:.0%} ({v.trades}t)"
                for k, v in sorted(stats.by_regime.items(), key=lambda x: -x[1].trades)
            )
            lines.append(f"By regime: {regs}")

        cb = stats.confluence_buckets
        lines.append(f"Confluence: low(1-2) {cb.get('low', 0):.0%}, "
                      f"mid(3) {cb.get('mid', 0):.0%}, high(4+) {cb.get('high', 0):.0%}")

        if stats.confidence_calibration:
            cal = ", ".join(f"{k}→{v:.0%}" for k, v in stats.confidence_calibration.items())
            lines.append(f"Calibration: {cal}")

        return "\n".join(lines)

    def _run_backtests(self, symbol: str, results: list, regime: dict | None = None) -> None:
        """Run ALL strategies on one symbol — direction-agnostic.

        Every strategy gets a chance regardless of regime. The LLM and
        quality gates filter bad setups; the regime gate was dropping
        valid setups in stocks that bucked the broader trend.
        """
        from tradingbot.strategy.strategies import STRATEGY_REGISTRY

        df = None
        if getattr(self, '_duckdb', None) is not None:
            df = self._duckdb.read(symbol, "15m", days=180)
        if (df is None or df.empty) and self._candles is not None:
            from_dt = datetime.now(tz=IST) - timedelta(days=self._lookback_days)
            df = self._candles.read(symbol, "15minute", from_dt, datetime.now(tz=IST))
        if df is None:
            import pandas as _pd
            df = _pd.DataFrame()
        if len(df) == 0:
            return

        for strategy_name, strategy in STRATEGY_REGISTRY.items():
            log.info("Backtesting %s/%s (%d candles)", symbol, strategy_name.value, len(df))
            report = self._backtest.run(symbol, df, strategy)
            if report.total_trades >= 3:
                trade_pnls = (
                    [report.avg_winner] * report.winners
                    + [report.avg_loser] * report.losers
                )
                mc = self._mc.run(trade_pnls) if trade_pnls else None
                gate = self._gates.evaluate(report, mc)
                if gate.passed:
                    from dataclasses import asdict
                    results.append(asdict(report))
                else:
                    log.info(
                        "Backtest gate FAILED %s/%s: %s",
                        symbol, strategy_name.value,
                        ", ".join(gate.failures) if gate.failures else "unknown",
                    )
