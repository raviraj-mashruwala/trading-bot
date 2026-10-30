"""Tier1Screener orchestrator: liquidity -> scoring -> correlation filter."""

from __future__ import annotations

import logging
from typing import Any

from tradingbot.core.config import ScreeningConfig
from tradingbot.core.models import ScoredStock
from tradingbot.screening.correlation_filter import CorrelationFilter
from tradingbot.screening.factor_scorer import FactorScorer
from tradingbot.screening.liquidity_filter import LiquidityFilter

log = logging.getLogger(__name__)


class Tier1Screener:
    """Deterministic screening: ~1500 stocks -> ~50-100 candidates."""

    def __init__(self, config: ScreeningConfig, candle_store=None):
        self._config = config
        self._liquidity = LiquidityFilter(
            min_volume=config.min_volume,
            min_price=config.min_price,
            max_price=config.max_price,
            min_market_cap_cr=config.min_market_cap_cr,
            min_trading_days=config.min_trading_days,
        )
        self._scorer = FactorScorer(
            weights={
                "volume_surge": config.volume_surge_weight,
                "relative_strength": config.relative_strength_weight,
                "atr_expansion": config.atr_expansion_weight,
                "price_structure": config.price_structure_weight,
                "delivery_pct": config.delivery_pct_weight,
                "sector_momentum": config.sector_momentum_weight,
                "gap_analysis": config.gap_analysis_weight,
                "candlestick_pattern": config.candlestick_pattern_weight,
                "volume_profile": config.volume_profile_weight,
            }
        )
        self._correlation = CorrelationFilter(
            max_per_sector=config.max_per_sector
        )

    def screen(self, stock_metrics: list[dict[str, Any]]) -> list[ScoredStock]:
        liquid = self._liquidity.filter_all(stock_metrics)
        log.info("Liquidity filter: %d -> %d", len(stock_metrics), len(liquid))

        scored: list[ScoredStock] = []
        for stock in liquid:
            factor_scores = stock.get("factor_scores", {})
            composite = self._scorer.compute_composite(factor_scores)
            scored.append(
                ScoredStock(
                    symbol=stock["symbol"],
                    exchange="NSE",
                    last_price=stock["last_price"],
                    avg_volume=stock["avg_volume"],
                    market_cap_cr=stock["market_cap_cr"],
                    atr_pct=stock.get("atr_pct", 0),
                    sector=stock.get("sector", "unknown"),
                    composite_score=composite,
                    factor_scores=factor_scores,
                    instrument_token=stock.get("token", 0),
                    signals=stock.get("signals", {}),
                )
            )

        scored.sort(key=lambda s: s.composite_score, reverse=True)
        filtered = self._correlation.filter(scored)
        log.info("After correlation filter: %d candidates", len(filtered))
        return filtered
