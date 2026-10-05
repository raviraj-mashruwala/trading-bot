"""Phase 1C: cap per-sector exposure to avoid correlated risk."""

from __future__ import annotations

from tradingbot.core.models import ScoredStock


class CorrelationFilter:
    """Keep only the top N stocks per sector, sorted by composite score."""

    def __init__(self, max_per_sector: int = 3):
        self._max = max_per_sector

    def filter(self, stocks: list[ScoredStock]) -> list[ScoredStock]:
        sorted_stocks = sorted(
            stocks, key=lambda s: s.composite_score, reverse=True
        )
        sector_counts: dict[str, int] = {}
        result: list[ScoredStock] = []
        for stock in sorted_stocks:
            if stock.sector and stock.sector != "unknown":
                count = sector_counts.get(stock.sector, 0)
                if count >= self._max:
                    continue
                sector_counts[stock.sector] = count + 1
            result.append(stock)
        return result
