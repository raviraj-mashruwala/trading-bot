from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from tradingbot.executor.candle_aggregator import CandleAggregator
from tradingbot.executor.momentum_scorer import MomentumScorer
from tradingbot.executor.entry_guard import EntryGuard
from tradingbot.executor.adaptive_exit_manager import AdaptiveExitManager
from tradingbot.executor.llm_escalator import LLMEscalator

logger = logging.getLogger(__name__)


@dataclass
class TickerHealth:
    last_tick_at: datetime | None = None
    reconnect_count: int = 0
    gap_seconds_today: int = 0
    status: str = "healthy"


class ExecutionIntelligence:
    def __init__(self, ticker, config) -> None:
        self._ticker = ticker
        self._config = config
        self._symbols: list[str] = []
        self._symbol_tokens: dict[str, str] = {}

        self.aggregator = CandleAggregator()
        self.scorer = MomentumScorer()
        self.entry_guard = EntryGuard(max_drift_pct=config.max_entry_price_drift_pct)
        self.adaptive_exit = AdaptiveExitManager(square_off_time=config.square_off_time)
        self.escalator = LLMEscalator()
        self.health = TickerHealth()

    @property
    def is_degraded(self) -> bool:
        return self.health.status == "degraded"

    def start(self, symbols: list[str]) -> None:
        self._symbols = symbols
        for sym in symbols:
            self._symbol_tokens[sym] = sym
            candles = self._fetch_historical_candles(sym)
            if candles:
                self.aggregator.seed(sym, "1min", [c for c in candles if c.timeframe == "1min"])
                self.aggregator.seed(sym, "5min", [c for c in candles if c.timeframe == "5min"])
        tokens = list(self._symbol_tokens.values())
        self._ticker.subscribe(tokens, self._on_ticks)
        self._ticker.start()

        self.aggregator.subscribe("1min_close", self._on_1min_close)
        self.aggregator.subscribe("5min_close", self._on_5min_close)

    def stop(self) -> None:
        self._ticker.stop()
        self._symbols.clear()

    def _on_ticks(self, ws, ticks: list[dict]) -> None:
        now = datetime.now()
        self.health.last_tick_at = now
        self.health.status = "healthy"
        for tick in ticks:
            symbol = tick.get("instrument_token", "")
            price = tick.get("last_price", 0.0)
            volume = tick.get("volume_traded", 0)
            ts = tick.get("exchange_timestamp", now)
            if isinstance(symbol, str) and price > 0:
                self.aggregator.on_tick(symbol, price, volume, ts)
                self.scorer.update_vwap(symbol, price, volume)

    def _on_1min_close(self, symbol: str, candle) -> None:
        candles_1m = self.aggregator.get_candles(symbol, "1min")
        candles_5m = self.aggregator.get_candles(symbol, "5min")
        state = self.scorer.update(symbol, candles_1m, candles_5m)
        if state:
            self.adaptive_exit.track_peak_momentum(symbol, state.momentum_5m)

    def _on_5min_close(self, symbol: str, candle) -> None:
        candles_1m = self.aggregator.get_candles(symbol, "1min")
        candles_5m = self.aggregator.get_candles(symbol, "5min")
        self.scorer.update(symbol, candles_1m, candles_5m)

    def _fetch_historical_candles(self, symbol: str) -> list:
        return []

    def on_disconnect(self) -> None:
        self.health.reconnect_count += 1
        self.health.status = "reconnecting"
        logger.warning("Ticker disconnected, reconnect #%d", self.health.reconnect_count)

    def on_reconnect(self) -> None:
        self.health.status = "healthy"
        logger.info("Ticker reconnected")

    def mark_degraded(self, gap_seconds: int) -> None:
        self.health.gap_seconds_today += gap_seconds
        self.health.status = "degraded"
