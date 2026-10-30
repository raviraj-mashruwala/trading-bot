"""Macro backdrop for the scanner: index trend, volatility, institutional flows.

Index and VIX data are read from the local CandleStore (synced via DataSync).
FII/DII institutional flow data is fetched from the NSE JSON API via httpx.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from tradingbot.core.models import MarketContext, MarketRegime

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

NSE_HOME = "https://www.nseindia.com"
NSE_FII_DII_URL = "https://www.nseindia.com/api/fiidiiTradeReact"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

VIX_VOLATILE_THRESHOLD = 20.0
VIX_LOW_THRESHOLD = 11.0
VIX_DEFAULT = 15.0
INDEX_LOOKBACK_DAYS = 120


class MarketContextFetcher:
    """Assembles the MarketContext handed to the scanner LLM call.

    Index and VIX data come from MarketDataProvider (yfinance) or
    CandleStore (legacy fallback). FII/DII from NSE JSON API.
    """

    def __init__(
        self,
        http_client: httpx.Client | None = None,
        candle_store: Any = None,
        market_data_provider: Any = None,
    ) -> None:
        self.http_client = http_client or httpx.Client(headers=BROWSER_HEADERS, timeout=10.0)
        self._candles = candle_store
        self._provider = market_data_provider

    def fetch(self) -> MarketContext:
        fii_net, dii_net = self._fetch_fii_dii()
        nifty_level, above_sma20, above_sma50 = self._fetch_index_trend("NIFTY 50")
        bank_level, bank_above_sma20, bank_above_sma50 = self._fetch_index_trend("NIFTY BANK")
        vix = self._fetch_vix()

        return MarketContext(
            nifty_level=nifty_level,
            nifty_trend=self._describe_trend(above_sma20, above_sma50),
            banknifty_trend=self._describe_trend(bank_above_sma20, bank_above_sma50),
            india_vix=vix,
            fii_net_cr=fii_net,
            dii_net_cr=dii_net,
            global_cues="unavailable",
            sector_leaders=[],
            sector_laggards=[],
            regime=self.classify_regime(vix, above_sma20, above_sma50),
            banknifty_level=bank_level,
        )

    def classify_regime(
        self,
        vix: float,
        nifty_above_sma20: bool,
        nifty_above_sma50: bool,
    ) -> MarketRegime:
        """Volatility dominates; direction only decides trending versus ranging."""
        if vix >= VIX_VOLATILE_THRESHOLD:
            return MarketRegime.VOLATILE
        if vix <= VIX_LOW_THRESHOLD:
            return MarketRegime.LOW_VOL_SQUEEZE
        if nifty_above_sma20 and nifty_above_sma50:
            return MarketRegime.TRENDING_UP
        if not nifty_above_sma20 and not nifty_above_sma50:
            return MarketRegime.TRENDING_DOWN
        return MarketRegime.RANGE_BOUND

    @staticmethod
    def _describe_trend(above_sma20: bool, above_sma50: bool) -> str:
        if above_sma20 and above_sma50:
            return "bullish"
        if not above_sma20 and not above_sma50:
            return "bearish"
        return "mixed"

    def _fetch_index_trend(self, symbol: str) -> tuple[float, bool, bool]:
        """Return (last level, above SMA20, above SMA50).

        Uses MarketDataProvider (yfinance) if available, else CandleStore.
        Returns (0.0, False, False) on failure — degrades safely.
        """
        df = self._read_index(symbol, INDEX_LOOKBACK_DAYS)
        if df.empty or len(df) < 50:
            logger.warning("Insufficient data for %s (%d rows)", symbol, len(df))
            return 0.0, False, False
        try:
            closes = df["close"]
            last = float(closes.iloc[-1])
            sma20 = float(closes.rolling(20).mean().iloc[-1])
            sma50 = float(closes.rolling(50).mean().iloc[-1])
            return last, last > sma20, last > sma50
        except Exception as exc:
            logger.warning("Index trend failed for %s: %s", symbol, exc)
            return 0.0, False, False

    def _fetch_vix(self) -> float:
        """Return India VIX last close. Defaults to 15.0 on failure."""
        df = self._read_index("INDIA VIX", 10)
        if df.empty:
            logger.warning("VIX unavailable, defaulting to %.1f", VIX_DEFAULT)
            return VIX_DEFAULT
        try:
            return float(df["close"].iloc[-1])
        except Exception as exc:
            logger.warning("VIX parse failed, defaulting to %.1f: %s", VIX_DEFAULT, exc)
            return VIX_DEFAULT

    def _read_index(self, symbol: str, days: int) -> "pd.DataFrame":
        """Read index data from provider or candle_store fallback."""
        import pandas as pd

        if self._candles is not None:
            try:
                # CandleStore.read(symbol, interval, days=N): the last N daily rows.
                return self._candles.read(symbol, "day", days=days)
            except Exception as exc:
                logger.warning("CandleStore index fetch failed for %s: %s", symbol, exc)
        return pd.DataFrame()

    def _fetch_fii_dii(self) -> tuple[float, float]:
        """Return (FII net, DII net) in crore. Zeros when NSE is unreachable."""
        try:
            self.http_client.get(NSE_HOME, headers=BROWSER_HEADERS)
            response = self.http_client.get(NSE_FII_DII_URL, headers=BROWSER_HEADERS)
            response.raise_for_status()
            rows = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("FII/DII fetch failed, defaulting to zero: %s", exc)
            return 0.0, 0.0

        fii_net = dii_net = 0.0
        for row in rows:
            category = str(row.get("category", "")).upper()
            try:
                net = float(row.get("netValue", 0.0))
            except (TypeError, ValueError):
                continue
            if "FII" in category or "FPI" in category:
                fii_net = net
            elif "DII" in category:
                dii_net = net
        return fii_net, dii_net
