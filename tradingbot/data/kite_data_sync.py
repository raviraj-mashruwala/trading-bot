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
    "15minute": 180,
    "5minute": 90,
    "minute": 30,
}

INTERVAL_MAP = {
    "day": "day",
    "15m": "15minute",
    "5m": "5minute",
    "1m": "minute",
}

# Initial fill + daily sync: daily only for full MIS universe
SYNC_DEPTHS = {
    "day": {"years": 11, "stocks": "all"},
}

# On-demand fetch for shortlisted stocks: 7 years, all intervals
ON_DEMAND_DEPTHS = {
    "15m": 7,
    "5m": 7,
    "1m": 7,
}

INDEX_TOKENS = {
    "NIFTY 50": 256265,
    "INDIA VIX": 264969,
    "NIFTY BANK": 260105,
}

MIS_MARGINS_URL = "https://api.kite.trade/margins/equity"

MAX_RETRIES = 3
RETRY_BACKOFF = [1, 2, 4]


def _fetch_mis_symbols() -> list[str]:
    """Fetch stocks with MIS (intraday) margins from Kite. ~1,672 stocks."""
    import httpx
    try:
        resp = httpx.get(MIS_MARGINS_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        symbols = [item["tradingsymbol"] for item in data if "tradingsymbol" in item]
        log.info("MIS margin universe: %d stocks", len(symbols))
        return symbols
    except Exception as exc:
        log.warning("Failed to fetch MIS margins list: %s", exc)
        return []


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

        # Fetch MIS margin stocks — only stocks Zerodha allows for intraday trading
        mis_symbols = await asyncio.to_thread(_fetch_mis_symbols)
        if not mis_symbols:
            log.error("Cannot proceed without MIS stock list")
            return report

        # Refresh instrument cache for token resolution
        try:
            raw_instruments = await asyncio.to_thread(self._kite.fetch_instruments, "NSE")
            self._instruments.refresh(raw_instruments)
        except Exception as exc:
            log.warning("Instrument refresh failed, using cache: %s", exc)

        all_symbols = mis_symbols
        log.info("Initial fill: %d MIS-margin stocks", len(all_symbols))

        for store_interval, config in SYNC_DEPTHS.items():
            if self._cancelled:
                break
            kite_interval = INTERVAL_MAP[store_interval]
            max_days = KITE_LIMITS[kite_interval]
            start_date = date(max(2015, today.year - config["years"]), 1, 1)

            symbols = all_symbols
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

        # Use MIS list — only sync stocks we can actually trade
        mis_symbols = await asyncio.to_thread(_fetch_mis_symbols)
        mis_set = set(mis_symbols) if mis_symbols else None

        for store_interval in SYNC_DEPTHS:
            if self._cancelled:
                break
            kite_interval = INTERVAL_MAP[store_interval]
            cached = self._store.symbols_with_data(store_interval)
            # Only sync stocks that are both cached AND in current MIS list
            symbols = [s for s in cached if mis_set is None or s in mis_set or s in INDEX_TOKENS]

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

    async def fetch_on_demand(
        self,
        symbol: str,
        intervals: list[str] | None = None,
        years: int | None = None,
        progress_callback: Callable | None = None,
    ) -> int:
        """Fetch historical data for a single stock. Paginated, gap-aware.

        If stock has no cached data: fetches `years` of history (default from ON_DEMAND_DEPTHS).
        If stock has cached data: fetches only from last_date to today (gap fill).
        Returns total rows written.
        """
        if intervals is None:
            intervals = list(ON_DEMAND_DEPTHS.keys())
        today = date.today()
        total_written = 0

        for store_interval in intervals:
            last = self._store.last_date(symbol, store_interval)
            kite_interval = INTERVAL_MAP.get(store_interval, store_interval)
            max_days = KITE_LIMITS.get(kite_interval, 60)

            if last is not None:
                from_date = last + timedelta(days=1)
                if from_date > today:
                    continue
            else:
                depth_years = years or ON_DEMAND_DEPTHS.get(store_interval, 7)
                from_date = date(max(2015, today.year - depth_years), 1, 1)

            chunks = _date_chunks(from_date, today, max_days)
            for chunk_from, chunk_to in chunks:
                if self._cancelled:
                    return total_written
                for attempt in range(MAX_RETRIES):
                    try:
                        token = self._resolve_token(symbol)
                        raw = await asyncio.to_thread(
                            self._kite.fetch_historical, token, kite_interval, chunk_from, chunk_to
                        )
                        df = _kite_rows_to_df(raw)
                        written = await asyncio.to_thread(self._store.write, symbol, store_interval, df)
                        total_written += written
                        break
                    except Exception as exc:
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(RETRY_BACKOFF[attempt])
                        else:
                            log.warning("On-demand fetch failed for %s/%s %s-%s: %s",
                                        symbol, store_interval, chunk_from, chunk_to, exc)

            if progress_callback:
                progress_callback(f"{symbol} {store_interval}: {'gap fill' if last else 'full fetch'} done")

        return total_written

    async def fetch_shortlist_data(
        self,
        symbols: list[str],
        progress_callback: Callable | None = None,
    ) -> dict[str, int]:
        """Fetch 7-year intraday data for shortlisted stocks. Gap-aware.

        New stocks get full 7-year fetch. Returning stocks get gap fill only.
        Returns {symbol: rows_written}.
        """
        results = {}
        for i, symbol in enumerate(symbols):
            if self._cancelled:
                break
            if progress_callback:
                last = self._store.last_date(symbol, "15m")
                action = "updating" if last else "fetching 7yr"
                progress_callback(f"Intraday data: {action} {symbol} ({i+1}/{len(symbols)})")
            rows = await self.fetch_on_demand(symbol, progress_callback=None)
            results[symbol] = rows
        if progress_callback:
            total = sum(results.values())
            progress_callback(f"Intraday data: {len(symbols)} stocks, {total:,} rows")
        return results

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
                        written = await asyncio.to_thread(self._store.write, symbol, store_interval, df)
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
