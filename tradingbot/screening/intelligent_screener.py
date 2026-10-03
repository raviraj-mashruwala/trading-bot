"""Intelligent Tier1 Screener: deterministic core + Jev probabilistic layer.

The deterministic screener is too aggressive — fixed thresholds, fixed weights,
fixed sector caps. This wraps it with three Jev-powered enhancements:

1. RESCUE POOL: Stocks that barely miss liquidity thresholds get a second
   chance if Jev detects unusual activity signals.
2. REGIME-ADAPTIVE WEIGHTS: Factor weights shift based on today's market
   regime (trending → momentum weights up, range → mean reversion up).
3. SMART CORRELATION: Sector caps flex based on sector strength today
   (strong sector gets more slots, weak sector gets fewer).

The deterministic filter still runs first as a safety floor. Jev only adds
or reweights — it never lets through truly illiquid or untradeable stocks.
"""

from __future__ import annotations

import logging
from typing import Any

from tradingbot.core.config import ScreeningConfig
from tradingbot.core.models import MarketRegime, ScoredStock
from tradingbot.screening.factor_scorer import FactorScorer
from tradingbot.screening.liquidity_filter import LiquidityFilter

log = logging.getLogger(__name__)

# How close to the threshold a stock must be to qualify for rescue.
# 0.6 = must have at least 60% of the required value.
RESCUE_PROXIMITY = 0.6

# Factor weight adjustments per regime. Values are multipliers on base weights.
# >1.0 = factor matters more in this regime, <1.0 = matters less.
REGIME_WEIGHT_PROFILES: dict[str, dict[str, float]] = {
    "trending_up": {
        "volume_surge": 1.3,
        "relative_strength": 1.5,
        "atr_expansion": 1.2,
        "price_structure": 0.8,
        "delivery_pct": 1.3,
        "sector_momentum": 1.4,
        "gap_analysis": 1.0,
        "candlestick_pattern": 0.9,
        "volume_profile": 1.1,
    },
    "trending_down": {
        "volume_surge": 1.2,
        "relative_strength": 1.4,
        "atr_expansion": 1.3,
        "price_structure": 0.9,
        "delivery_pct": 1.2,
        "sector_momentum": 1.3,
        "gap_analysis": 1.1,
        "candlestick_pattern": 1.0,
        "volume_profile": 1.0,
    },
    "range_bound": {
        "volume_surge": 0.8,
        "relative_strength": 0.7,
        "atr_expansion": 0.6,
        "price_structure": 1.5,
        "delivery_pct": 1.0,
        "sector_momentum": 0.8,
        "gap_analysis": 0.9,
        "candlestick_pattern": 1.3,
        "volume_profile": 1.4,
    },
    "volatile": {
        "volume_surge": 1.4,
        "relative_strength": 1.0,
        "atr_expansion": 1.5,
        "price_structure": 0.7,
        "delivery_pct": 0.8,
        "sector_momentum": 0.9,
        "gap_analysis": 1.4,
        "candlestick_pattern": 1.1,
        "volume_profile": 1.2,
    },
    "low_vol_squeeze": {
        "volume_surge": 1.5,
        "relative_strength": 1.1,
        "atr_expansion": 1.5,
        "price_structure": 1.2,
        "delivery_pct": 1.0,
        "sector_momentum": 1.0,
        "gap_analysis": 1.0,
        "candlestick_pattern": 1.0,
        "volume_profile": 1.3,
    },
}


class IntelligentScreener:
    """Tier 1 screener with Jev-powered intelligence layer.

    Flow:
        1. Hard liquidity filter (safety floor, never bypassed)
        2. Soft rescue of near-miss stocks via Jev
        3. Regime-adaptive factor scoring via Jev weight modulation
        4. Smart sector cap allocation via Jev sector strength
    """

    def __init__(self, config: ScreeningConfig, jev_client=None):
        self._config = config
        self._jev = jev_client
        self._liquidity = LiquidityFilter(
            min_volume=config.min_volume,
            min_price=config.min_price,
            max_price=config.max_price,
            min_market_cap_cr=config.min_market_cap_cr,
            min_trading_days=config.min_trading_days,
        )
        self._base_weights = {
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

    def screen(
        self,
        stock_metrics: list[dict[str, Any]],
        regime: str = "range_bound",
        regime_confidence: float = 0.5,
        sector_scores: dict[str, float] | None = None,
    ) -> list[ScoredStock]:
        """Screen stocks with intelligence layer.

        Args:
            stock_metrics: Raw stock data (~1500 stocks).
            regime: Current market regime (from Jev or Claude).
            regime_confidence: How confident the regime classification is.
            sector_scores: Per-sector strength scores (0-1) from Jev.
        """
        # ── Step 1: Hard liquidity filter (safety floor) ──
        liquid = self._liquidity.filter_all(stock_metrics)
        rejected = [s for s in stock_metrics if s not in liquid]
        log.info("Hard liquidity: %d → %d passed, %d rejected",
                 len(stock_metrics), len(liquid), len(rejected))

        # ── Step 2: Rescue near-miss stocks via Jev ──
        rescued = self._rescue_near_misses(rejected)
        all_candidates = liquid + rescued
        log.info("Rescued %d near-miss stocks via Jev", len(rescued))

        # ── Step 3: Regime-adaptive scoring ──
        adapted_weights = self._adapt_weights(regime, regime_confidence)
        scorer = FactorScorer(weights=adapted_weights)

        scored: list[ScoredStock] = []
        for stock in all_candidates:
            factor_scores = stock.get("factor_scores", {})
            composite = scorer.compute_composite(factor_scores)

            # Jev bonus: unusual activity detection
            jev_bonus = 0.0
            if self._jev and stock.get("_jev_unusual_activity"):
                jev_bonus = stock["_jev_unusual_activity"] * 5.0

            scored.append(
                ScoredStock(
                    symbol=stock["symbol"],
                    exchange="NSE",
                    last_price=stock["last_price"],
                    avg_volume=stock["avg_volume"],
                    market_cap_cr=stock["market_cap_cr"],
                    atr_pct=stock.get("atr_pct", 0),
                    sector=stock.get("sector", "unknown"),
                    composite_score=composite + jev_bonus,
                    factor_scores=factor_scores,
                    instrument_token=stock.get("token", 0),
                )
            )

        scored.sort(key=lambda s: s.composite_score, reverse=True)

        # ── Step 4: Smart sector cap allocation ──
        filtered = self._smart_sector_filter(scored, sector_scores)
        log.info("After smart sector filter: %d candidates", len(filtered))
        return filtered

    # ── Rescue Pool ──────────────────────────────────────────────────────

    def _rescue_near_misses(
        self, rejected: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Rescue stocks that barely missed hard thresholds.

        A stock qualifies for rescue if:
        - It has >= RESCUE_PROXIMITY (60%) of each threshold
        - Jev says it shows unusual activity worth investigating

        This catches mid-caps with pre-market volume spikes, or stocks
        just below the price floor that have strong technicals.
        """
        if not self._jev:
            return []

        near_misses = []
        for stock in rejected:
            proximity = self._compute_proximity(stock)
            if proximity >= RESCUE_PROXIMITY:
                near_misses.append(stock)

        if not near_misses:
            return []

        log.info("Evaluating %d near-miss stocks with Jev", len(near_misses))
        rescued = []

        # Batch evaluate with Jev
        from typesafe_sdk import Noul, Score

        for stock in near_misses:
            try:
                response = self._jev.system_one(
                    state={
                        "symbol": stock["symbol"],
                        "last_price": stock["last_price"],
                        "avg_volume": stock["avg_volume"],
                        "today_volume": stock.get("today_volume", 0),
                        "volume_ratio": (
                            stock.get("today_volume", 0) / max(stock["avg_volume"], 1)
                        ),
                        "market_cap_cr": stock["market_cap_cr"],
                        "atr_pct": stock.get("atr_pct", 0),
                        "sector": stock.get("sector", "unknown"),
                        "factor_scores": stock.get("factor_scores", {}),
                        "failed_checks": self._identify_failures(stock),
                    },
                    questions={
                        "unusual_activity": Noul(
                            instructions=(
                                "Despite failing standard liquidity thresholds, "
                                "does this stock show unusual activity that makes "
                                "it worth investigating as an intraday trade?"
                            ),
                            criteria={
                                "true": (
                                    "Today's volume is significantly above average, "
                                    "or strong technical factors compensate for "
                                    "slightly below-threshold liquidity"
                                ),
                                "false": (
                                    "No unusual activity — stock rightfully filtered "
                                    "out by standard screening"
                                ),
                            },
                        ),
                        "tradeable_despite_threshold": Noul(
                            instructions=(
                                "Can this stock be safely traded intraday despite "
                                "barely missing one or more screening thresholds? "
                                "Consider: can you enter and exit without excessive "
                                "slippage?"
                            ),
                        ),
                        "opportunity_quality": Score(
                            instructions=(
                                "How strong is the trading opportunity for this stock, "
                                "ignoring the screening threshold it failed?"
                            ),
                            criteria=[
                                "Weak — no compelling setup even if liquid enough",
                                "Moderate — decent setup, worth watching",
                                "Strong — clear opportunity being missed by rigid filter",
                            ],
                        ),
                    },
                )

                unusual = response.answers["unusual_activity"].noul
                tradeable = response.answers["tradeable_despite_threshold"].noul
                quality = response.answers["opportunity_quality"].score / 2

                rescue_score = 0.4 * unusual + 0.3 * tradeable + 0.3 * quality

                if rescue_score > 0.55:
                    stock["_jev_unusual_activity"] = unusual
                    stock["_jev_rescue_score"] = rescue_score
                    rescued.append(stock)
                    log.info(
                        "RESCUED %s: unusual=%.2f tradeable=%.2f quality=%.2f → %.2f",
                        stock["symbol"], unusual, tradeable, quality, rescue_score,
                    )
            except Exception:
                log.debug("Jev rescue failed for %s, skipping", stock["symbol"])

        return rescued

    def _compute_proximity(self, stock: dict[str, Any]) -> float:
        """How close to passing the stock was (0 = far, 1 = barely missed)."""
        ratios = []
        if stock["avg_volume"] < self._config.min_volume:
            ratios.append(stock["avg_volume"] / max(self._config.min_volume, 1))
        if stock["last_price"] < self._config.min_price:
            ratios.append(stock["last_price"] / max(self._config.min_price, 0.01))
        if stock["last_price"] > self._config.max_price:
            ratios.append(self._config.max_price / max(stock["last_price"], 0.01))
        if stock["market_cap_cr"] < self._config.min_market_cap_cr:
            ratios.append(
                stock["market_cap_cr"] / max(self._config.min_market_cap_cr, 0.01)
            )
        return min(ratios) if ratios else 1.0

    def _identify_failures(self, stock: dict[str, Any]) -> list[str]:
        """List which thresholds the stock failed."""
        failures = []
        if stock["avg_volume"] < self._config.min_volume:
            failures.append(
                f"avg_volume {stock['avg_volume']:,} < min {self._config.min_volume:,}"
            )
        if stock["last_price"] < self._config.min_price:
            failures.append(
                f"price {stock['last_price']} < min {self._config.min_price}"
            )
        if stock["last_price"] > self._config.max_price:
            failures.append(
                f"price {stock['last_price']} > max {self._config.max_price}"
            )
        if stock["market_cap_cr"] < self._config.min_market_cap_cr:
            failures.append(
                f"mcap {stock['market_cap_cr']}cr < min {self._config.min_market_cap_cr}cr"
            )
        return failures

    # ── Regime-Adaptive Weights ──────────────────────────────────────────

    def _adapt_weights(
        self, regime: str, regime_confidence: float
    ) -> dict[str, int]:
        """Blend base weights with regime-specific multipliers.

        When regime confidence is high, weights shift more aggressively.
        When confidence is low (ambiguous regime), weights stay close to base.
        This prevents wild swings on uncertain classification.
        """
        profile = REGIME_WEIGHT_PROFILES.get(regime)
        if not profile:
            return self._base_weights

        # Blend strength: 0 = pure base, 1 = full regime adaptation
        # Scale by confidence so ambiguous regimes don't over-adapt
        blend = min(regime_confidence, 0.85)

        adapted = {}
        for factor, base_weight in self._base_weights.items():
            multiplier = profile.get(factor, 1.0)
            # Interpolate: base + blend * (regime-adjusted - base)
            adjusted = base_weight * (1.0 + blend * (multiplier - 1.0))
            adapted[factor] = max(1, int(round(adjusted)))

        log.info(
            "Adapted weights for regime=%s (confidence=%.2f, blend=%.2f)",
            regime, regime_confidence, blend,
        )
        return adapted

    # ── Smart Sector Allocation ──────────────────────────────────────────

    def _smart_sector_filter(
        self,
        stocks: list[ScoredStock],
        sector_scores: dict[str, float] | None,
    ) -> list[ScoredStock]:
        """Flex sector caps based on sector strength.

        Strong sectors get more slots, weak sectors get fewer.
        Base cap (from config) is the starting point.
        """
        base_cap = self._config.max_per_sector

        if not sector_scores:
            # Fallback to fixed cap
            return self._fixed_sector_filter(stocks, base_cap)

        # Compute dynamic caps: strong sector gets +1-2 slots, weak gets -1
        sector_caps: dict[str, int] = {}
        for sector, strength in sector_scores.items():
            if strength > 0.7:
                sector_caps[sector] = base_cap + 2
            elif strength > 0.5:
                sector_caps[sector] = base_cap + 1
            elif strength < 0.3:
                sector_caps[sector] = max(1, base_cap - 1)
            else:
                sector_caps[sector] = base_cap

        # Apply dynamic caps
        sector_counts: dict[str, int] = {}
        result: list[ScoredStock] = []
        for stock in stocks:
            cap = sector_caps.get(stock.sector, base_cap)
            count = sector_counts.get(stock.sector, 0)
            if count < cap:
                result.append(stock)
                sector_counts[stock.sector] = count + 1

        log.info(
            "Smart sector caps: %s",
            {s: f"{c}/{sector_caps.get(s, base_cap)}"
             for s, c in sector_counts.items()},
        )
        return result

    @staticmethod
    def _fixed_sector_filter(
        stocks: list[ScoredStock], max_per: int
    ) -> list[ScoredStock]:
        sector_counts: dict[str, int] = {}
        result: list[ScoredStock] = []
        for stock in stocks:
            count = sector_counts.get(stock.sector, 0)
            if count < max_per:
                result.append(stock)
                sector_counts[stock.sector] = count + 1
        return result
