"""Market data provider — Kite instruments API only. OHLCV data comes from CandleStore."""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)


class MarketDataProvider:
    """Provides NSE instrument universe from Kite. Historical OHLCV is in CandleStore."""

    def __init__(self, kite_client: Any = None):
        self._kite = kite_client

    @staticmethod
    def to_nse_symbol(symbol: str) -> str:
        return f"{symbol}.NS"

    @staticmethod
    def from_nse_symbol(yf_symbol: str) -> str:
        return yf_symbol.replace(".NS", "")

    _JUNK_SUFFIXES = ("-SG", "-GS", "-GB", "-IL", "-PP",
                      "-N1", "-N2", "-N3", "-N4", "-N5", "-N6",
                      "-SM", "-BE", "-BZ", "-ST", "-BL")
    _JUNK_RE = re.compile(r"-[A-Z]{2}$")
    # ETFs and funds are baskets or commodities, not intraday single-stock setups. Kite names
    # every one "... ETF" or "... BEES"; whole-word matching keeps operating companies such as
    # "SBI FUNDS MANAGEMENT".
    _FUND_NAME_RE = re.compile(r"\b(ETF|BEES|FUND|GILT|LIQUID)\b", re.IGNORECASE)
    _FUND_SYMBOL_RE = re.compile(r"(BEES|ETF)$")

    def get_universe(
        self,
        min_price: float = 0.0,
        max_price: float = float("inf"),
    ) -> list[dict[str, Any]]:
        """Get NSE equity instrument list from Kite (1 API call)."""
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
                if self._FUND_SYMBOL_RE.search(sym) or self._FUND_NAME_RE.search(i.get("name") or ""):
                    continue
                lp = float(i.get("last_price", 0) or 0)
                if lp > 0 and not (min_price <= lp <= max_price):
                    price_filtered += 1
                    continue
                result.append({
                    "symbol": sym,
                    "token": i["instrument_token"],
                    "exchange": i["exchange"],
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
