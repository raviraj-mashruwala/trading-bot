"""Paginated Kite historical data fetcher with resume and retry."""

from __future__ import annotations

import asyncio
import logging
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

import pandas as pd

from tradingbot.data.candle_store import CandleStore

log = logging.getLogger(__name__)

KITE_LIMITS = {
    "day": 2000,
    "15minute": 200,
    "5minute": 100,
    "minute": 60,
}

INTERVAL_MAP = {
    "day": "day",
    "15m": "15minute",
    "5m": "5minute",
    "1m": "minute",
}

TARGET_DEPTHS = {
    "day": {"years": 11, "stocks": "all"},
    "15m": {"years": 11, "stocks": "liquid"},
    "5m": {"years": 5, "stocks": "liquid"},
    "1m": {"years": 5, "stocks": "liquid"},
}

INDEX_TOKENS = {
    "NIFTY 50": 256265,
    "INDIA VIX": 264969,
    "NIFTY BANK": 260105,
}

MAX_RETRIES = 3
RETRY_BACKOFF = [1, 2, 4]


@dataclass
class SyncReport:
    stocks_synced: int = 0
    rows_written: int = 0
    errors: list[str] = field(default_factory=list)
    duration_sec: float = 0.0


def _date_chunks(start: date, end: date, max_days: int) -> list[tuple[date, date]]:
    chunks = []
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=max_days - 1), end)
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks


def _kite_rows_to_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    records = []
    for r in rows:
        ts = r["date"] if isinstance(r["date"], datetime) else datetime.combine(r["date"], datetime.min.time())
        records.append({
            "timestamp": ts,
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": int(r["volume"]),
        })
    return pd.DataFrame(records)


class KiteDataSync:
    """Paginated Kite historical fetcher with resume, retry, and background fill."""

    def __init__(
        self,
        kite_client: Any,
        candle_store: CandleStore,
        instrument_cache: Any,
        screening_config: Any = None,
    ) -> None:
        self._kite = kite_client
        self._store = candle_store
        self._instruments = instrument_cache
        self._screening = screening_config
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    async def initial_fill(self, progress_callback: Callable | None = None) -> SyncReport:
        start = _time.monotonic()
        report = SyncReport()
        self._cancelled = False
        today = date.today()

        all_instruments = self._instruments.get_all()
        all_symbols = [i["symbol"] for i in all_instruments]

        for store_interval, config in TARGET_DEPTHS.items():
            if self._cancelled:
                break
            kite_interval = INTERVAL_MAP[store_interval]
            max_days = KITE_LIMITS[kite_interval]
            start_date = date(max(2015, today.year - config["years"]), 1, 1)

            if config["stocks"] == "all":
                symbols = all_symbols
            else:
                symbols = self._get_liquid_symbols(all_symbols)

            if store_interval == "day":
                symbols = list(set(symbols) | set(INDEX_TOKENS.keys()))

            if progress_callback:
                progress_callback(f"Starting {store_interval}: {len(symbols)} stocks, since {start_date}")

            sub = await self._sync_interval(symbols, store_interval, start_date, today,
                                            kite_interval, max_days, progress_callback)
            report.stocks_synced += sub.stocks_synced
            report.rows_written += sub.rows_written
            report.errors.extend(sub.errors)

        report.duration_sec = _time.monotonic() - start
        log.info("Initial fill complete: %d stocks, %d rows, %.0fs, %d errors",
                 report.stocks_synced, report.rows_written, report.duration_sec, len(report.errors))
        return report

    async def daily_sync(self, progress_callback: Callable | None = None) -> SyncReport:
        start = _time.monotonic()
        report = SyncReport()
        self._cancelled = False
        today = date.today()

        for store_interval in TARGET_DEPTHS:
            if self._cancelled:
                break
            kite_interval = INTERVAL_MAP[store_interval]
            symbols = self._store.symbols_with_data(store_interval)

            if not symbols:
                continue

            if progress_callback:
                progress_callback(f"Daily sync {store_interval}: {len(symbols)} stocks")

            for symbol in symbols:
                if self._cancelled:
                    break
                last = self._store.last_date(symbol, store_interval)
                if last and last >= today:
                    continue
                from_date = last + timedelta(days=1) if last else today - timedelta(days=5)
                try:
                    token = self._resolve_token(symbol)
                    raw = await asyncio.to_thread(
                        self._kite.fetch_historical, token, kite_interval, from_date, today
                    )
                    df = _kite_rows_to_df(raw)
                    written = self._store.write(symbol, store_interval, df)
                    report.rows_written += written
                    report.stocks_synced += 1
                except Exception as exc:
                    report.errors.append(f"{symbol}/{store_interval}: {exc}")

        report.duration_sec = _time.monotonic() - start
        log.info("Daily sync: %d stocks, %d rows, %.0fs",
                 report.stocks_synced, report.rows_written, report.duration_sec)
        return report

    async def fetch_on_demand(self, symbol: str, intervals: list[str] | None = None) -> None:
        if intervals is None:
            intervals = ["day", "15m"]
        today = date.today()
        for store_interval in intervals:
            last = self._store.last_date(symbol, store_interval)
            kite_interval = INTERVAL_MAP.get(store_interval, store_interval)
            max_days = KITE_LIMITS.get(kite_interval, 60)
            from_date = last + timedelta(days=1) if last else today - timedelta(days=max_days)
            try:
                token = self._resolve_token(symbol)
                raw = await asyncio.to_thread(
                    self._kite.fetch_historical, token, kite_interval, from_date, today
                )
                df = _kite_rows_to_df(raw)
                self._store.write(symbol, store_interval, df)
            except Exception:
                log.warning("On-demand fetch failed for %s/%s", symbol, store_interval, exc_info=True)

    async def _sync_interval(
        self,
        symbols: list[str],
        store_interval: str,
        start_date: date,
        end_date: date,
        kite_interval: str | None = None,
        max_days: int | None = None,
        progress_callback: Callable | None = None,
    ) -> SyncReport:
        if kite_interval is None:
            kite_interval = INTERVAL_MAP[store_interval]
        if max_days is None:
            max_days = KITE_LIMITS[kite_interval]

        report = SyncReport()
        for idx, symbol in enumerate(symbols):
            if self._cancelled:
                break

            last = self._store.last_date(symbol, store_interval)
            sym_start = last + timedelta(days=1) if last else start_date
            if sym_start > end_date:
                report.stocks_synced += 1
                continue

            chunks = _date_chunks(sym_start, end_date, max_days)
            sym_rows = 0

            for chunk_from, chunk_to in chunks:
                if self._cancelled:
                    break
                for attempt in range(MAX_RETRIES):
                    try:
                        token = self._resolve_token(symbol)
                        raw = await asyncio.to_thread(
                            self._kite.fetch_historical, token, kite_interval, chunk_from, chunk_to
                        )
                        df = _kite_rows_to_df(raw)
                        written = self._store.write(symbol, store_interval, df)
                        sym_rows += written
                        break
                    except Exception as exc:
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(RETRY_BACKOFF[attempt])
                        else:
                            report.errors.append(f"{symbol}/{store_interval} {chunk_from}-{chunk_to}: {exc}")

            report.rows_written += sym_rows
            report.stocks_synced += 1

            if progress_callback and (idx + 1) % 10 == 0:
                progress_callback(f"{store_interval}: {idx + 1}/{len(symbols)} stocks, {report.rows_written} rows")

        return report

    def _resolve_token(self, symbol: str) -> int:
        if symbol in INDEX_TOKENS:
            return INDEX_TOKENS[symbol]
        return self._instruments.get_token(symbol)

    def _get_liquid_symbols(self, all_symbols: list[str]) -> list[str]:
        daily_data = self._store.read_batch(all_symbols, "day", days=20)
        liquid = []
        for symbol, df in daily_data.items():
            if df.empty or len(df) < 5:
                continue
            avg_vol = float(df["volume"].tail(20).mean())
            last_price = float(df["close"].iloc[-1])
            if self._screening is None:
                if avg_vol >= 100_000 and 50 <= last_price <= 5000:
                    liquid.append(symbol)
            else:
                if (avg_vol >= self._screening.min_volume
                        and self._screening.min_price <= last_price <= self._screening.max_price):
                    liquid.append(symbol)
        log.info("Liquid stocks for intraday: %d / %d", len(liquid), len(all_symbols))
        return liquid
