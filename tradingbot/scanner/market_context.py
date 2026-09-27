"""Macro backdrop for the scanner: index trend, volatility, institutional flows.

The NSE JSON endpoints require a browser-like session: fetch the homepage first
so the server sets its cookies, then call the API with those cookies attached.
"""

from __future__ import annotations

import logging

import httpx
import yfinance as yf

from tradingbot.core.models import MarketContext, MarketRegime

logger = logging.getLogger(__name__)

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


class MarketContextFetcher:
    """Assembles the MarketContext handed to the scanner LLM call."""

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self.http_client = http_client or httpx.Client(headers=BROWSER_HEADERS, timeout=10.0)

    def fetch(self) -> MarketContext:
        fii_net, dii_net = self._fetch_fii_dii()
        nifty_level, above_sma20, above_sma50 = self._fetch_index_trend("^NSEI")
        _, bank_above_sma20, bank_above_sma50 = self._fetch_index_trend("^NSEBANK")
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
        if nifty_above_sma20 == nifty_above_sma50:
            return MarketRegime.TRENDING_UP
        return MarketRegime.RANGE_BOUND

    @staticmethod
    def _describe_trend(above_sma20: bool, above_sma50: bool) -> str:
        if above_sma20 and above_sma50:
            return "bullish"
        if not above_sma20 and not above_sma50:
            return "bearish"
        return "mixed"

    def _fetch_fii_dii(self) -> tuple[float, float]:
        """Return (FII net, DII net) in crore. Zeros when NSE is unreachable."""
        try:
            self.http_client.get(NSE_HOME, headers=BROWSER_HEADERS)
            response = self.http_client.get(NSE_FII_DII_URL, headers=BROWSER_HEADERS)
            response.raise_for_status()
            rows = response.json()
        except Exception as exc:  # noqa: BLE001 - macro data is nice to have, not required
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

    @staticmethod
    def _fetch_index_trend(ticker: str) -> tuple[float, bool, bool]:
        """Return (last level, above 20 day SMA, above 50 day SMA)."""
        try:
            history = yf.Ticker(ticker).history(period="120d", interval="1d")
            closes = history["Close"]
            last = float(closes.iloc[-1])
            return (
                last,
                last > float(closes.rolling(20).mean().iloc[-1]),
                last > float(closes.rolling(50).mean().iloc[-1]),
            )
        except Exception as exc:  # noqa: BLE001 - fall back to a neutral reading
            logger.warning("index trend fetch failed for %s: %s", ticker, exc)
            return 0.0, False, False

    @staticmethod
    def _fetch_vix() -> float:
        try:
            history = yf.Ticker("^INDIAVIX").history(period="5d", interval="1d")
            return float(history["Close"].iloc[-1])
        except Exception as exc:  # noqa: BLE001 - a mid-range default keeps regime sane
            logger.warning("VIX fetch failed, defaulting to 15.0: %s", exc)
            return 15.0
