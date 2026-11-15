"""Market data for the rule from Kite: completed daily bars and today's opening price."""

from __future__ import annotations

from datetime import datetime, timedelta

from tradingbot.rule_executor.kec_rule import DailyBar, Sizing, margin_quantity


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

    def ltp(self, symbol: str) -> float:
        key = f"NSE:{symbol}"
        return float(self._kite.ltp([key])[key]["last_price"])

    def _short_margin(self, symbol: str, price: float, quantity: int) -> float:
        rows = self._kite.order_margins([{
            "exchange": "NSE", "tradingsymbol": symbol, "transaction_type": "SELL", "variety": "regular",
            "product": "MIS", "order_type": "LIMIT", "quantity": quantity, "price": price,
        }])
        return float(rows[0]["total"])

    def size_short(self, symbol: str, price: float, buffer: float) -> Sizing:
        """Largest MIS short whose margin fits in Kite's available balance minus `buffer`."""
        available = float(self._kite.margins("equity")["net"])
        per_share = self._short_margin(symbol, price, 1)
        qty = margin_quantity(available, per_share, buffer)
        for _ in range(3):  # confirm with the real quantity; margin can be non-linear at size
            if qty <= 0:
                break
            total = self._short_margin(symbol, price, qty)
            if total <= available - buffer:
                break
            qty = int(qty * (available - buffer) / total) - 1
        return Sizing(available, per_share, max(qty, 0))

    def today_open(self, symbol: str) -> float | None:
        key = f"NSE:{symbol}"
        quote = self._kite.ohlc([key]).get(key)
        if not quote:
            return None
        value = float(quote["ohlc"]["open"])
        return value if value > 0 else None
