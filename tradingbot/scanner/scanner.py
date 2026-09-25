"""Scanner agent: universe to filters to market context to LLM shortlist."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from tradingbot.core.config import ScannerConfig
from tradingbot.core.models import MarketContext, ShortlistedStock
from tradingbot.scanner.calendar import NotATradingDayError, is_trading_day
from tradingbot.scanner.filters import FilterResult, apply_filters

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Everything the strategy agent needs from the scanner."""

    trade_date: date
    context: MarketContext
    shortlist: list[ShortlistedStock]
    filter_result: FilterResult


class Scanner:
    """Runs the full pre-market narrowing pipeline for one trade date."""

    def __init__(self, fetcher, context_fetcher, analyzer, config: ScannerConfig) -> None:
        self.fetcher = fetcher
        self.context_fetcher = context_fetcher
        self.analyzer = analyzer
        self.config = config

    async def scan(self, trade_date: date) -> ScanResult:
        if not is_trading_day(trade_date):
            raise NotATradingDayError(
                f"{trade_date.isoformat()} is not an NSE trading day; nothing to plan"
            )

        symbols = self.fetcher.fetch_universe()
        logger.info("universe contains %d symbols", len(symbols))

        stocks = self.fetcher.fetch_stock_metrics(symbols)
        filter_result = apply_filters(stocks, self.config)
        logger.info(
            "%d/%d symbols passed filters (rejected: %s)",
            len(filter_result.passed),
            len(stocks),
            filter_result.rejected or "none",
        )

        context = self.context_fetcher.fetch()
        shortlist = await self.analyzer.shortlist(filter_result.passed, context)
        logger.info("LLM shortlisted %d candidates", len(shortlist))

        return ScanResult(
            trade_date=trade_date,
            context=context,
            shortlist=shortlist,
            filter_result=filter_result,
        )
