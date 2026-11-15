"""Market data for the rule from Kite: completed daily bars and today's opening price."""

from __future__ import annotations

from datetime import datetime, timedelta

from tradingbot.rule_executor.kec_rule import DailyBar


class KiteMarketData:
    def __init__(self, kite) -> None:
        self._kite = kite
        self._tokens: dict[str, int] = {}

    def _token(self, symbol: str) -> int:
        if symbol not in self._tokens:
            key = f"NSE:{symbol}"
            self._tokens[symbol] = int(self._kite.ltp([key])[key]["instrument_token"])
        return self._tokens[symbol]

    def completed_daily_bars(self, symbol: str, before: datetime, count: int) -> list[DailyBar]:
        today = before.date()
        rows = self._kite.historical_data(self._token(symbol), today - timedelta(days=count * 2 + 10),
                                          today - timedelta(days=1), "day")
        bars = []
        for r in rows:
            day = r["date"].date() if hasattr(r["date"], "date") else r["date"]
            if day < today:
                bars.append(DailyBar(day, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])))
        return bars[-count:]

    def today_open(self, symbol: str) -> float | None:
        key = f"NSE:{symbol}"
        quote = self._kite.ohlc([key]).get(key)
        if not quote:
            return None
        value = float(quote["ohlc"]["open"])
        return value if value > 0 else None
