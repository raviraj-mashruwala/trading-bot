"""Market data provider using yfinance for historical OHLCV."""

from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

_INDEX_MAP = {
    "NIFTY 50": "^NSEI",
    "NIFTY BANK": "^NSEBANK",
    "INDIA VIX": "^INDIAVIX",
}


class MarketDataProvider:
    """Fetches OHLCV data from yfinance. All DataFrames use lowercase columns."""

    def __init__(self, kite_client: Any = None):
        self._kite = kite_client
        self._cache: dict[str, pd.DataFrame] = {}

    @staticmethod
    def to_nse_symbol(symbol: str) -> str:
        if symbol.endswith(".NS"):
            return symbol
        return f"{symbol}.NS"

    @staticmethod
    def from_nse_symbol(yf_symbol: str) -> str:
        return yf_symbol.removesuffix(".NS")

    @staticmethod
    def _normalize(df: pd.DataFrame) -> pd.DataFrame:
        df = df.rename(columns=str.lower)
        keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
        return df[keep]

    _JUNK_SUFFIXES = ("-SG", "-GS", "-GB", "-IL", "-PP",
                      "-N1", "-N2", "-N3", "-N4", "-N5", "-N6",
                      "-SM", "-BE", "-BZ", "-ST", "-BL")
    _JUNK_RE = re.compile(r"-[A-Z]{2}$")

    def get_universe(
        self,
        min_price: float = 0.0,
        max_price: float = float("inf"),
    ) -> list[dict[str, Any]]:
        """Get NSE equity instrument list from Kite (1 API call).

        Filters out government bonds, NCDs, illiquid series, and instruments
        outside the price range using Kite's last_price metadata.
        """
        if self._kite is None:
            raise RuntimeError("Kite client required for stock universe")
        try:
            raw = self._kite.kite.instruments("NSE")
            result = []
            price_filtered = 0
            for i in raw:
                if i.get("instrument_type") != "EQ" or i.get("segment") != "NSE":
                    continue
                sym = i["tradingsymbol"]
                if any(sym.endswith(s) for s in self._JUNK_SUFFIXES):
                    continue
                if self._JUNK_RE.search(sym):
                    continue
                lp = float(i.get("last_price", 0) or 0)
                if lp > 0 and not (min_price <= lp <= max_price):
                    price_filtered += 1
                    continue
                result.append({
                    "symbol": sym,
                    "token": i["instrument_token"],
                    "exchange": "NSE",
                    "lot_size": i.get("lot_size", 1),
                    "tick_size": i.get("tick_size", 0.05),
                    "sector": i.get("industry_type") or "unknown",
                    "last_price": lp,
                })
            log.info(
                "Universe: %d equities (filtered from %d NSE instruments, %d price-excluded)",
                len(result), len(raw), price_filtered,
            )
            return result
        except Exception as exc:
            log.error("Failed to fetch instruments from Kite: %s", exc)
            return []

    def get_daily_batch(
        self, symbols: list[str], days: int = 365, chunk_size: int = 100,
    ) -> dict[str, pd.DataFrame]:
        """Batch download daily OHLCV in chunks to avoid thread exhaustion."""
        if not symbols:
            return {}
        result: dict[str, pd.DataFrame] = {}
        period = f"{days}d"

        for i in range(0, len(symbols), chunk_size):
            chunk_syms = symbols[i : i + chunk_size]
            yf_syms = [self.to_nse_symbol(s) for s in chunk_syms]
            try:
                raw = yf.download(
                    yf_syms, period=period, interval="1d",
                    progress=False, threads=False,
                )
                result.update(self._split_multi(raw, chunk_syms, yf_syms))
                log.info("Daily batch %d-%d: %d symbols fetched", i, i + len(chunk_syms), len(chunk_syms))
            except Exception as exc:
                log.error("yfinance batch chunk %d failed: %s", i, exc)

        return result

    def get_intraday(
        self, symbol: str, interval: str = "15m", days: int = 60
    ) -> pd.DataFrame:
        """Fetch intraday candles for a single symbol."""
        cache_key = f"{symbol}:{interval}:{days}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        yf_sym = self.to_nse_symbol(symbol)
        try:
            ticker = yf.Ticker(yf_sym)
            df = ticker.history(period=f"{days}d", interval=interval)
            df = self._normalize(df)
            self._cache[cache_key] = df
            return df
        except Exception as exc:
            log.warning("Intraday fetch failed for %s: %s", symbol, exc)
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    def get_intraday_batch(
        self, symbols: list[str], interval: str = "15m", days: int = 60,
        chunk_size: int = 50,
    ) -> dict[str, pd.DataFrame]:
        """Batch download intraday candles in chunks."""
        if not symbols:
            return {}
        result: dict[str, pd.DataFrame] = {}

        for i in range(0, len(symbols), chunk_size):
            chunk_syms = symbols[i : i + chunk_size]
            yf_syms = [self.to_nse_symbol(s) for s in chunk_syms]
            try:
                raw = yf.download(
                    yf_syms, period=f"{days}d", interval=interval,
                    progress=False, threads=False,
                )
                result.update(self._split_multi(raw, chunk_syms, yf_syms))
            except Exception as exc:
                log.error("yfinance intraday batch chunk %d failed: %s", i, exc)

        return result

    def get_index(self, name: str, days: int = 120) -> pd.DataFrame:
        """Fetch index or VIX daily data."""
        yf_sym = _INDEX_MAP.get(name, name)
        try:
            ticker = yf.Ticker(yf_sym)
            df = ticker.history(period=f"{days}d")
            return self._normalize(df)
        except Exception as exc:
            log.warning("Index fetch failed for %s: %s", name, exc)
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    def clear_cache(self) -> None:
        self._cache.clear()

    def _split_multi(
        self, raw: pd.DataFrame, symbols: list[str], yf_symbols: list[str],
    ) -> dict[str, pd.DataFrame]:
        """Split a yfinance multi-ticker download into per-symbol DataFrames."""
        result: dict[str, pd.DataFrame] = {}
        if raw.empty:
            return result

        if isinstance(raw.columns, pd.MultiIndex):
            for sym, yf_sym in zip(symbols, yf_symbols):
                try:
                    df = raw.xs(yf_sym, level="Ticker", axis=1).dropna(how="all")
                    if not df.empty:
                        result[sym] = self._normalize(df)
                except KeyError:
                    continue
        elif len(yf_symbols) == 1:
            df = raw.dropna(how="all")
            if not df.empty:
                result[symbols[0]] = self._normalize(df)
        return result
