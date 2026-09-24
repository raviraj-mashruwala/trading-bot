"""LLM call 2: turn shortlisted stocks plus evidence into concrete trade setups.

One batched call covers every shortlisted symbol, which keeps a full analysis run
at two LLM calls total.
"""

from __future__ import annotations

import logging
from datetime import time

from tradingbot.core.config import StrategyConfig
from tradingbot.core.llm.provider import LLMProvider
from tradingbot.core.models import (
    BacktestResult,
    Direction,
    EntryType,
    IndicatorSnapshot,
    MarketContext,
    ShortlistedStock,
    StrategyName,
    TradeSetup,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an expert intraday trading strategist working the Indian equity market. "
    "You design precise trade setups with exact entry, stop loss, and target levels, "
    "based only on the technical readings, backtest evidence, and market regime you "
    "are given. Do NOT guess or fabricate numbers, and do NOT reference data you were "
    "not shown. Every level you return must be justifiable from the supplied support, "
    "resistance, ATR, and price values. If a symbol has no good setup, omit it; "
    "returning fewer setups is always better than returning a weak one."
)

SETUP_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "setups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "strategy": {
                        "type": "string",
                        "enum": ["breakout", "momentum", "mean_reversion", "vwap_bounce", "orb"],
                    },
                    "direction": {"type": "string", "enum": ["long", "short"]},
                    "entry_price": {"type": "number"},
                    "entry_type": {"type": "string", "enum": ["limit", "stop"]},
                    "stop_loss": {"type": "number"},
                    "target_1": {"type": "number"},
                    "target_2": {"type": "number"},
                    "entry_window_start": {"type": "string"},
                    "entry_window_end": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reasoning": {"type": "string"},
                },
                "required": [
                    "symbol",
                    "strategy",
                    "direction",
                    "entry_price",
                    "entry_type",
                    "stop_loss",
                    "target_1",
                    "target_2",
                    "entry_window_start",
                    "entry_window_end",
                    "confidence",
                    "reasoning",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["setups"],
    "additionalProperties": False,
}


class StrategySelector:
    """Asks Claude to design setups, then validates every field it returns."""

    def __init__(self, provider: LLMProvider, strategy_config: StrategyConfig) -> None:
        self.provider = provider
        self.config = strategy_config

    async def design_setups(
        self,
        shortlist: list[ShortlistedStock],
        snapshots: dict[str, IndicatorSnapshot],
        backtests: dict[str, list[BacktestResult]],
        context: MarketContext,
    ) -> list[TradeSetup]:
        if not shortlist:
            logger.warning("shortlist is empty; skipping the setup design call")
            return []

        payload = await self.provider.analyze(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=self._build_prompt(shortlist, snapshots, backtests, context),
            tool_name="submit_setups",
            tool_description="Return one intraday trade setup per stock you want to trade.",
            input_schema=SETUP_SCHEMA,
        )

        allowed = {stock.symbol for stock in shortlist}
        setups: list[TradeSetup] = []

        for raw in payload.get("setups", []):
            setup = self._parse_setup(raw, allowed)
            if setup is not None:
                setups.append(setup)

        return setups

    @staticmethod
    def _parse_setup(raw: dict, allowed: set[str]) -> TradeSetup | None:
        symbol = str(raw.get("symbol", "")).upper()
        if symbol not in allowed:
            logger.warning("dropping setup for %s: not in the shortlist", symbol or "<blank>")
            return None

        try:
            return TradeSetup(
                symbol=symbol,
                strategy=StrategyName(raw["strategy"]),
                direction=Direction(raw["direction"]),
                entry_price=float(raw["entry_price"]),
                entry_type=EntryType(raw["entry_type"]),
                stop_loss=float(raw["stop_loss"]),
                target_1=float(raw["target_1"]),
                target_2=float(raw["target_2"]),
                entry_window_start=_parse_clock(raw["entry_window_start"]),
                entry_window_end=_parse_clock(raw["entry_window_end"]),
                confidence=float(raw["confidence"]),
                reasoning=str(raw["reasoning"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("dropping setup for %s: malformed field (%s)", symbol, exc)
            return None

    def _build_prompt(
        self,
        shortlist: list[ShortlistedStock],
        snapshots: dict[str, IndicatorSnapshot],
        backtests: dict[str, list[BacktestResult]],
        context: MarketContext,
    ) -> str:
        blocks: list[str] = [
            "MARKET REGIME\n"
            f"Regime: {context.regime.value}\n"
            f"Nifty: {context.nifty_level:.0f} ({context.nifty_trend})\n"
            f"India VIX: {context.india_vix:.2f}\n"
        ]

        for stock in shortlist:
            snapshot = snapshots.get(stock.symbol)
            if snapshot is None:
                continue

            results = backtests.get(stock.symbol, [])
            backtest_lines = (
                "\n".join(
                    f"  - {result.strategy.value}: {result.win_rate * 100:.0f}% win rate "
                    f"over {result.trades} trades, avg R:R {result.avg_reward_risk:.2f}"
                    for result in results
                )
                or "  - no backtest data"
            )

            blocks.append(
                f"=== {stock.symbol} ===\n"
                f"Scanner note: {stock.reasoning}\n"
                f"Scanner bias: {stock.direction_bias}, suggested {stock.suggested_strategy.value}\n"
                f"Last close: {snapshot.last_close:.2f}\n"
                f"RSI(14): {snapshot.rsi_14:.1f} | MACD: {snapshot.macd:.3f} "
                f"vs signal {snapshot.macd_signal:.3f}\n"
                f"ATR(14): {snapshot.atr_14:.2f} | VWAP: {snapshot.vwap:.2f} | "
                f"Pivot: {snapshot.pivot:.2f}\n"
                f"Bollinger: {snapshot.bb_lower:.2f} / {snapshot.bb_middle:.2f} / {snapshot.bb_upper:.2f}\n"
                f"SMA 20/50/200: {snapshot.sma_20:.2f} / {snapshot.sma_50:.2f} / {snapshot.sma_200:.2f}\n"
                f"Support: {', '.join(f'{level:.2f}' for level in snapshot.support_levels) or 'none'}\n"
                f"Resistance: {', '.join(f'{level:.2f}' for level in snapshot.resistance_levels) or 'none'}\n"
                f"Backtest (last {self.config.backtest_days} days):\n{backtest_lines}"
            )

        blocks.append(
            "TASK\n"
            "For each stock where you see a genuinely good intraday setup, return a trade "
            f"setup. Require at least {self.config.min_reward_risk:.1f}:1 reward to risk "
            f"measured to target 1, and at least {self.config.min_confidence:.2f} confidence. "
            "Entry windows must fall between 09:30 and 14:00 and use HH:MM. Place stops "
            "beyond a real technical level, not at a round number."
        )

        return "\n\n".join(blocks)


def _parse_clock(raw: str) -> time:
    hour, minute = str(raw).split(":")
    return time(int(hour), int(minute))
