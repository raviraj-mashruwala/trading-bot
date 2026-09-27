"""Zerodha intraday transaction cost model.

Covers brokerage (capped at Rs 20/order), STT, exchange charges,
GST, SEBI turnover fee, stamp duty, and configurable slippage.
"""

from __future__ import annotations


class ZerodhaCosts:
    """Zerodha intraday equity transaction cost calculator."""

    BROKERAGE_CAP = 20.0  # per order
    BROKERAGE_PCT = 0.03 / 100  # 0.03%
    STT_PCT = 0.025 / 100  # on sell side
    EXCHANGE_PCT = 0.00345 / 100
    SEBI_PCT = 0.0001 / 100
    STAMP_PCT = 0.003 / 100  # on buy side
    GST_PCT = 18.0 / 100  # on brokerage + exchange

    def __init__(self, slippage_pct: float = 0.02):
        self._slippage_pct = slippage_pct / 100

    def round_trip_cost(
        self, entry_price: float, exit_price: float, quantity: int
    ) -> float:
        """Total cost for one buy+sell round trip, in rupees."""
        buy_value = entry_price * quantity
        sell_value = exit_price * quantity
        turnover = buy_value + sell_value

        brokerage_buy = min(self.BROKERAGE_CAP, buy_value * self.BROKERAGE_PCT)
        brokerage_sell = min(self.BROKERAGE_CAP, sell_value * self.BROKERAGE_PCT)
        brokerage = brokerage_buy + brokerage_sell

        stt = sell_value * self.STT_PCT
        exchange = turnover * self.EXCHANGE_PCT
        sebi = turnover * self.SEBI_PCT
        stamp = buy_value * self.STAMP_PCT
        gst = (brokerage + exchange) * self.GST_PCT

        slippage = turnover * self._slippage_pct

        return brokerage + stt + exchange + sebi + stamp + gst + slippage
