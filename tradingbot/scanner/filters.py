"""Deterministic screening. Runs before the LLM so the model only sees plausible names."""

from __future__ import annotations

from dataclasses import dataclass, field

from tradingbot.core.config import ScannerConfig
from tradingbot.core.models import Stock


@dataclass
class FilterResult:
    """Which stocks survived, and a tally of why the rest did not."""

    passed: list[Stock] = field(default_factory=list)
    rejected: dict[str, int] = field(default_factory=dict)


def _rejection_reason(stock: Stock, config: ScannerConfig) -> str | None:
    """Return the first failing filter name, or None when the stock passes."""
    if stock.avg_volume < config.min_volume:
        return "volume"
    if not (config.min_price <= stock.last_price <= config.max_price):
        return "price"
    if stock.market_cap_cr < config.min_market_cap_cr:
        return "market_cap"
    if stock.atr_pct < config.min_atr_pct:
        return "atr"
    return None


def apply_filters(stocks: list[Stock], config: ScannerConfig) -> FilterResult:
    """Screen the universe down to the candidates worth spending LLM tokens on."""
    result = FilterResult()

    for stock in stocks:
        reason = _rejection_reason(stock, config)
        if reason is None:
            result.passed.append(stock)
        else:
            result.rejected[reason] = result.rejected.get(reason, 0) + 1

    result.passed.sort(key=lambda stock: stock.avg_volume, reverse=True)
    result.passed = result.passed[: config.max_stocks_to_llm]
    return result
