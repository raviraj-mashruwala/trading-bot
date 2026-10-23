from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable

from tradingbot.core.jev_client import JevClient
from tradingbot.executor.candle_aggregator import CandleAggregator, LiveCandle
from tradingbot.executor.momentum_scorer import MomentumScorer
from tradingbot.executor.entry_guard import EntryGuard
from tradingbot.executor.adaptive_exit_manager import AdaptiveExitManager
from tradingbot.executor.jev_escalator import JevEscalator
from tradingbot.executor.llm_escalator import LLMEscalator

logger = logging.getLogger(__name__)

SEED_CANDLE_COUNT = 50
STALE_TICK_THRESHOLD_SECONDS = 120
LIVENESS_CHECK_INTERVAL_SECONDS = 15.0
LIVENESS_PROBE_TIMEOUT_SECONDS = 1.0
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15


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
        jev_config: Any | None = None,
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

        jev_client = None
        if jev_config and jev_config.enabled:
            jev_client = JevClient(jev_config)

        self.entry_guard = EntryGuard(
            max_drift_pct=config.max_entry_price_drift_pct,
            jev_client=jev_client,
        )
        self.adaptive_exit = AdaptiveExitManager(
            square_off_time=config.square_off_time,
            jev_client=jev_client if (jev_client and jev_client.available) else None,
        )

        llm_escalator = LLMEscalator()
        if jev_client and jev_client.available:
            self.escalator = JevEscalator(jev_client, jev_config, llm_fallback=llm_escalator)
        else:
            self.escalator = llm_escalator

        self.health = TickerHealth()
        self.alert: Callable[[str], None] | None = None
        self._last_liveness_check_at = float("-inf")
        self._stale_alerted = False

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
        if hasattr(self._ticker, "set_lifecycle_callbacks"):
            self._ticker.set_lifecycle_callbacks(
                on_disconnect=self.on_disconnect,
                on_reconnect=self.on_reconnect,
            )
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

    def _on_ticks(self, token_or_ws: Any, ltp_or_ticks: Any) -> None:
        now = datetime.now()
        self.health.last_tick_at = now
        if self.health.status == "reconnecting":
            self.health.status = "healthy"

        if isinstance(ltp_or_ticks, (int, float)):
            ticks = [{"instrument_token": token_or_ws, "last_price": ltp_or_ticks, "volume_traded": 0, "exchange_timestamp": now}]
        elif isinstance(ltp_or_ticks, list):
            ticks = ltp_or_ticks
        else:
            return

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

    _last_reconnect_at: float = 0.0
    _RECONNECT_COOLDOWN = 120.0

    def check_and_reconnect(self, now: datetime | None = None) -> bool:
        """Watchdog for the ticker. Returns True if it restarted or reconnected it.

        1. Liveness (any time, even pre-open): if the ticker thread's event loop does
           not answer, force_reconnect() cannot work because it schedules on that loop,
           so replace the thread outright.
        2. Staleness (from market open): no ticks for STALE_TICK_THRESHOLD_SECONDS
           means force-reconnect, at most once per cooldown, alerting once per episode.
        """
        import time as _time
        now = now or datetime.now()

        if self._restart_if_ticker_wedged():
            return True

        if now.hour < MARKET_OPEN_HOUR or (now.hour == MARKET_OPEN_HOUR and now.minute < MARKET_OPEN_MINUTE):
            return False
        # Check ticker's own timestamp first (set in ticker thread, no callback dependency)
        ticker_last = getattr(self._ticker, "last_tick_time", None)
        if ticker_last is not None:
            self.health.last_tick_at = ticker_last

        if self.health.last_tick_at is None:
            stale = (now - now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0)).total_seconds()
        else:
            stale = (now - self.health.last_tick_at).total_seconds()
        if stale <= STALE_TICK_THRESHOLD_SECONDS:
            self._stale_alerted = False
            return False
        if _time.monotonic() - self._last_reconnect_at < self._RECONNECT_COOLDOWN:
            return False
        logger.warning(
            "Ticks stale for %.0fs (threshold %ds) — forcing reconnect",
            stale, STALE_TICK_THRESHOLD_SECONDS,
        )
        if not self._stale_alerted:
            self._stale_alerted = True
            self._notify(f"No ticks for {stale:.0f}s — forcing ticker reconnect")
        self.health.status = "reconnecting"
        if hasattr(self._ticker, "force_reconnect"):
            self._ticker.force_reconnect()
            self.health.reconnect_count += 1
            self._last_reconnect_at = _time.monotonic()
            return True
        return False

    def _restart_if_ticker_wedged(self) -> bool:
        import time as _time
        probe = getattr(self._ticker, "is_loop_responsive", None)
        restart = getattr(self._ticker, "restart", None)
        if probe is None or restart is None:
            return False
        mono = _time.monotonic()
        if mono - self._last_liveness_check_at < LIVENESS_CHECK_INTERVAL_SECONDS:
            return False
        self._last_liveness_check_at = mono
        if probe(LIVENESS_PROBE_TIMEOUT_SECONDS):
            return False
        logger.error("Ticker thread is unresponsive — restarting it")
        restart()
        self.health.status = "reconnecting"
        self.health.reconnect_count += 1
        self._last_reconnect_at = mono
        self._notify("Ticker thread was frozen and has been restarted. Live ticks may have been missed.")
        return True

    def _notify(self, message: str) -> None:
        if self.alert is None:
            return
        try:
            self.alert(message)
        except Exception:
            logger.warning("Ticker alert delivery failed", exc_info=True)

    def mark_degraded(self, gap_seconds: int) -> None:
        self.health.gap_seconds_today += gap_seconds
        self.health.status = "degraded"
