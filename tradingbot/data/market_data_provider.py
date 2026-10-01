"""Market data provider using yfinance for historical OHLCV."""

from __future__ import annotations

import logging
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

    def get_universe(self) -> list[dict[str, Any]]:
        """Get NSE equity instrument list from Kite (1 API call).

        Falls back to empty list if Kite not available.
        """
        if self._kite is None:
            log.warning("No Kite client — universe unavailable")
            return []
        try:
            raw = self._kite.kite.instruments("NSE")
            return [
                {
                    "symbol": i["tradingsymbol"],
                    "token": i["instrument_token"],
                    "exchange": "NSE",
                    "lot_size": i.get("lot_size", 1),
                    "tick_size": i.get("tick_size", 0.05),
                    "sector": i.get("industry_type") or "unknown",
                }
                for i in raw
                if i.get("instrument_type") == "EQ" and i.get("segment") == "NSE"
            ]
        except Exception as exc:
            log.error("Failed to fetch instruments from Kite: %s", exc)
            return []

    def get_daily_batch(
        self, symbols: list[str], days: int = 365
    ) -> dict[str, pd.DataFrame]:
        """Batch download daily OHLCV for multiple symbols."""
        if not symbols:
            return {}
        yf_symbols = [self.to_nse_symbol(s) for s in symbols]
        period = f"{days}d"
        try:
            raw = yf.download(
                yf_symbols, period=period, interval="1d",
                progress=False, threads=True,
            )
        except Exception as exc:
            log.error("yfinance batch download failed: %s", exc)
            return {}

        return self._split_multi(raw, symbols, yf_symbols)

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
        self, symbols: list[str], interval: str = "15m", days: int = 60
    ) -> dict[str, pd.DataFrame]:
        """Batch download intraday candles."""
        if not symbols:
            return {}
        yf_symbols = [self.to_nse_symbol(s) for s in symbols]
        try:
            raw = yf.download(
                yf_symbols, period=f"{days}d", interval=interval,
                progress=False, threads=True,
            )
        except Exception as exc:
            log.error("yfinance intraday batch failed: %s", exc)
            return {}

        return self._split_multi(raw, symbols, yf_symbols)

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
