"""LLM call 1: narrow the filtered candidate pool to high conviction names."""

from __future__ import annotations

import logging

from tradingbot.core.config import ScannerConfig
from tradingbot.core.llm.provider import LLMProvider
from tradingbot.core.models import MarketContext, ShortlistedStock, Stock, StrategyName

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an expert Indian equity market analyst specialising in intraday trading "
    "on the NSE. You identify stocks with the highest probability of a significant "
    "intraday move, based on technical setups, market context, and institutional "
    "activity. You only ever choose from the candidate list you are given. You never "
    "invent a ticker, and you never recommend a stock you cannot justify from the "
    "supplied data."
)

SHORTLIST_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "reasoning": {"type": "string"},
                    "suggested_strategy": {
                        "type": "string",
                        "enum": ["breakout", "momentum", "mean_reversion", "vwap_bounce", "orb"],
                    },
                    "direction_bias": {"type": "string", "enum": ["long", "short", "neutral"]},
                    "key_levels": {"type": "array", "items": {"type": "number"}},
                },
                "required": [
                    "symbol",
                    "reasoning",
                    "suggested_strategy",
                    "direction_bias",
                    "key_levels",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["picks"],
    "additionalProperties": False,
}


class MarketAnalyzer:
    """Wraps the shortlist LLM call and validates everything it returns."""

    def __init__(self, provider: LLMProvider, config: ScannerConfig) -> None:
        self.provider = provider
        self.config = config

    async def shortlist(
        self,
        stocks: list[Stock],
        context: MarketContext,
    ) -> list[ShortlistedStock]:
        if not stocks:
            logger.warning("no candidates survived filtering; skipping the LLM call")
            return []

        payload = await self.provider.analyze(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=self._build_prompt(stocks, context),
            tool_name="submit_shortlist",
            tool_description="Return the intraday candidates chosen from the supplied list.",
            input_schema=SHORTLIST_SCHEMA,
        )

        allowed = {stock.symbol for stock in stocks}
        picks: list[ShortlistedStock] = []

        for raw in payload.get("picks", []):
            symbol = str(raw.get("symbol", "")).upper()
            if symbol not in allowed:
                logger.warning("dropping %s: not in the candidate pool", symbol or "<blank>")
                continue
            try:
                strategy = StrategyName(raw["suggested_strategy"])
            except (KeyError, ValueError):
                logger.warning("dropping %s: unknown strategy %r", symbol, raw.get("suggested_strategy"))
                continue

            picks.append(
                ShortlistedStock(
                    symbol=symbol,
                    reasoning=str(raw.get("reasoning", "")),
                    suggested_strategy=strategy,
                    direction_bias=str(raw.get("direction_bias", "neutral")),
                    key_levels=[float(level) for level in raw.get("key_levels", [])],
                )
            )

        return picks[: self.config.llm_pick_count]

    def _build_prompt(self, stocks: list[Stock], context: MarketContext) -> str:
        rows = "\n".join(
            f"| {stock.symbol} | {stock.sector} | {stock.last_price:.2f} | "
            f"{stock.avg_volume:,.0f} | {stock.market_cap_cr:,.0f} | {stock.atr_pct:.2f} |"
            for stock in stocks
        )
        return (
            "MARKET CONTEXT\n"
            f"Nifty: {context.nifty_level:.0f} ({context.nifty_trend})\n"
            f"Bank Nifty: {context.banknifty_trend}\n"
            f"India VIX: {context.india_vix:.2f}\n"
            f"FII net: {context.fii_net_cr:+.0f} Cr | DII net: {context.dii_net_cr:+.0f} Cr\n"
            f"Global cues: {context.global_cues}\n"
            f"Leading sectors: {', '.join(context.sector_leaders) or 'n/a'}\n"
            f"Lagging sectors: {', '.join(context.sector_laggards) or 'n/a'}\n"
            f"Regime: {context.regime.value}\n\n"
            "CANDIDATES (all passed liquidity, price, market cap, and volatility screens)\n"
            "| Symbol | Sector | Price | Avg Volume | Market Cap (Cr) | ATR % |\n"
            "|---|---|---|---|---|---|\n"
            f"{rows}\n\n"
            f"TASK\nSelect at most {self.config.llm_pick_count} of these stocks that are most "
            "suitable for an intraday trade on the next session. Use only symbols from the "
            "table above. For each pick, give your reasoning, the strategy type that best "
            "suits the setup, a direction bias, and the key price levels that matter."
        )
