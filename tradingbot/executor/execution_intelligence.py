from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from tradingbot.executor.candle_aggregator import CandleAggregator, LiveCandle
from tradingbot.executor.momentum_scorer import MomentumScorer
from tradingbot.executor.entry_guard import EntryGuard
from tradingbot.executor.adaptive_exit_manager import AdaptiveExitManager
from tradingbot.executor.llm_escalator import LLMEscalator

logger = logging.getLogger(__name__)

SEED_CANDLE_COUNT = 50


@dataclass
class TickerHealth:
    last_tick_at: datetime | None = None
    reconnect_count: int = 0
    gap_seconds_today: int = 0
    status: str = "healthy"


class ExecutionIntelligence:
    def __init__(
        self,
        ticker: Any,
        config: Any,
        instrument_cache: Any | None = None,
        kite_client: Any | None = None,
    ) -> None:
        self._ticker = ticker
        self._config = config
        self._instrument_cache = instrument_cache
        self._kite_client = kite_client
        self._symbols: list[str] = []
        self._symbol_to_token: dict[str, int] = {}
        self._token_to_symbol: dict[int, str] = {}

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
        subscribe_tokens: list[int | str] = []
        for sym in symbols:
            token = self._resolve_token(sym)
            self._symbol_to_token[sym] = token
            if isinstance(token, int):
                self._token_to_symbol[token] = sym
            candles = self._fetch_historical_candles(sym)
            if candles:
                self.aggregator.seed(sym, "1min", [c for c in candles if c.timeframe == "1min"])
                self.aggregator.seed(sym, "5min", [c for c in candles if c.timeframe == "5min"])
            subscribe_tokens.append(token)
        self._ticker.subscribe(subscribe_tokens, self._on_ticks)
        self._ticker.start()

        self.aggregator.subscribe("1min_close", self._on_1min_close)
        self.aggregator.subscribe("5min_close", self._on_5min_close)

    def stop(self) -> None:
        self._ticker.stop()
        self._symbols.clear()

    def _resolve_token(self, symbol: str) -> int | str:
        if self._instrument_cache is not None:
            try:
                return self._instrument_cache.get_token(symbol)
            except KeyError:
                logger.warning("No instrument token for %s, using symbol string", symbol)
        return symbol

    def _on_ticks(self, ws: Any, ticks: list[dict]) -> None:
        now = datetime.now()
        self.health.last_tick_at = now
        if self.health.status == "reconnecting":
            self.health.status = "healthy"
        for tick in ticks:
            raw_token = tick.get("instrument_token", "")
            price = tick.get("last_price", 0.0)
            volume = tick.get("volume_traded", 0)
            ts = tick.get("exchange_timestamp", now)
            if price <= 0:
                continue
            symbol = self._token_to_symbol.get(raw_token, raw_token) if isinstance(raw_token, int) else raw_token
            if symbol:
                self.aggregator.on_tick(symbol, price, volume, ts)
                self.scorer.update_vwap(symbol, price, volume)

    def _on_1min_close(self, symbol: str, candle: Any) -> None:
        candles_1m = self.aggregator.get_candles(symbol, "1min")
        candles_5m = self.aggregator.get_candles(symbol, "5min")
        state = self.scorer.update(symbol, candles_1m, candles_5m)
        if state:
            self.adaptive_exit.track_peak_momentum(symbol, state.momentum_5m)

    def _on_5min_close(self, symbol: str, candle: Any) -> None:
        candles_1m = self.aggregator.get_candles(symbol, "1min")
        candles_5m = self.aggregator.get_candles(symbol, "5min")
        self.scorer.update(symbol, candles_1m, candles_5m)

    def _fetch_historical_candles(self, symbol: str) -> list[LiveCandle]:
        if self._kite_client is None or self._instrument_cache is None:
            return []
        try:
            token = self._symbol_to_token.get(symbol)
            if not isinstance(token, int):
                return []
            today = date.today()
            from_date = today - timedelta(days=1)
            candles: list[LiveCandle] = []
            for interval, timeframe in [("minute", "1min"), ("5minute", "5min")]:
                raw = self._kite_client.fetch_historical(token, interval, from_date, today)
                for row in raw[-SEED_CANDLE_COUNT:]:
                    ts = row["date"] if isinstance(row["date"], datetime) else datetime.combine(today, datetime.min.time())
                    candles.append(LiveCandle(
                        symbol=symbol,
                        timeframe=timeframe,
                        timestamp=ts,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=int(row["volume"]),
                        is_complete=True,
                    ))
            return candles
        except Exception:
            logger.warning("Failed to fetch historical candles for %s", symbol, exc_info=True)
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
