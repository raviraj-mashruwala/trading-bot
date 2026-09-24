"""Market data access for the analysis phase.

Analysis runs the night before or early morning, so a 15 minute delayed free
source is acceptable here. The executor uses live broker data instead.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import yfinance as yf

from tradingbot.core.models import Stock

logger = logging.getLogger(__name__)

MIN_HISTORY_ROWS = 20

NSE_UNIVERSE: tuple[str, ...] = (
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "HINDUNILVR", "ITC",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "MARUTI",
    "TITAN", "SUNPHARMA", "ULTRACEMCO", "BAJFINANCE", "WIPRO", "NESTLEIND",
    "ONGC", "NTPC", "POWERGRID", "TATAMOTORS", "TATASTEEL", "JSWSTEEL",
    "HINDALCO", "COALINDIA", "GRASIM", "ADANIENT", "ADANIPORTS", "CIPLA",
    "DRREDDY", "DIVISLAB", "EICHERMOT", "HEROMOTOCO", "BAJAJ-AUTO", "BRITANNIA",
    "APOLLOHOSP", "INDUSINDBK", "BAJAJFINSV", "TECHM", "HCLTECH", "SBILIFE",
    "HDFCLIFE", "TATACONSUM", "UPL", "BPCL", "SHREECEM", "M&M",
)


class DataFetchError(Exception):
    """Raised when market data could not be retrieved for a symbol."""


class DataFetcher:
    """Fetches the tradable universe, per-symbol metrics, and candle history."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch_universe(self) -> list[str]:
        """Return the NSE symbols the scanner is allowed to consider."""
        return list(dict.fromkeys(NSE_UNIVERSE))

    def fetch_candles(self, symbol: str, days: int, interval: str) -> pd.DataFrame:
        """Return OHLCV candles with lowercase column names."""
        ticker = yf.Ticker(f"{symbol}.NS")
        raw = ticker.history(period=f"{days}d", interval=interval)
        if raw is None or raw.empty:
            raise DataFetchError(f"no candle data returned for {symbol}")

        df = raw.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )
        return df[["open", "high", "low", "close", "volume"]]

    def fetch_stock_metrics(self, symbols: list[str]) -> list[Stock]:
        """Build Stock records. Symbols that fail to load are skipped, not fatal."""
        stocks: list[Stock] = []

        for symbol in symbols:
            try:
                ticker = yf.Ticker(f"{symbol}.NS")
                info = ticker.info or {}
                history = ticker.history(period="60d", interval="1d")
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the scan
                logger.warning("skipping %s: %s", symbol, exc)
                continue

            if history is None or history.empty or len(history) < MIN_HISTORY_ROWS:
                logger.warning("skipping %s: insufficient history", symbol)
                continue

            df = history.rename(
                columns={
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                }
            )
            last_price = float(df["close"].iloc[-1])
            daily_range = (df["high"] - df["low"]).tail(14).mean()
            atr_pct = float(daily_range / last_price * 100.0) if last_price else 0.0

            stocks.append(
                Stock(
                    symbol=symbol,
                    exchange="NSE",
                    last_price=last_price,
                    avg_volume=float(df["volume"].tail(20).mean()),
                    market_cap_cr=float(info.get("marketCap", 0.0)) / 1e7,
                    atr_pct=atr_pct,
                    sector=info.get("sector", "Unknown"),
                )
            )

        return stocks
