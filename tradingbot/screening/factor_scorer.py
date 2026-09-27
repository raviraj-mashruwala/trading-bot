"""Phase 1B: score each stock 0-100 across 9 weighted factors."""

from __future__ import annotations

from typing import Any


class FactorScorer:
    """Compute weighted composite score from individual factor scores."""

    FACTOR_KEYS = [
        "volume_surge",
        "relative_strength",
        "atr_expansion",
        "price_structure",
        "delivery_pct",
        "sector_momentum",
        "gap_analysis",
        "candlestick_pattern",
        "volume_profile",
    ]

    def __init__(self, weights: dict[str, int]):
        self._weights = weights
        total = sum(weights.get(k, 0) for k in self.FACTOR_KEYS)
        self._norm = total if total > 0 else 1

    def compute_composite(self, factor_scores: dict[str, float]) -> float:
        weighted_sum = sum(
            factor_scores.get(k, 50.0) * self._weights.get(k, 0)
            for k in self.FACTOR_KEYS
        )
        return weighted_sum / self._norm

    def score_stock(
        self, stock: dict[str, Any], factor_scores: dict[str, float]
    ) -> float:
        return self.compute_composite(factor_scores)
