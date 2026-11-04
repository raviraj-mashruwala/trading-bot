"""Transaction cost models. Every harness result is net of these.

Rates are the NSE/SEBI schedule checked 2026-10-30 and applied to all years
(STT and stamp duty changed over 2019-2026; using current rates is slightly
pessimistic for stamp duty and exact for intraday cash STT). Slippage is a
per-side fraction of traded value and is the main sensitivity to vary.
"""

from __future__ import annotations


def equity_intraday_cost(buy: float, sell: float, quantity: int,
                         slippage_bps: float = 5.0) -> float:
    """Total rupee cost of one NSE cash intraday (MIS) round trip.

    Identical to research/replay_saved_plans.estimated_cost at slippage 5 bps.
    """
    buy_value, sell_value = buy * quantity, sell * quantity
    turnover = buy_value + sell_value
    brokerage = min(20.0, buy_value * .0003) + min(20.0, sell_value * .0003)
    exchange = turnover * .0000307
    sebi = turnover * .000001
    gst = .18 * (brokerage + exchange + sebi)
    stt = sell_value * .00025
    stamp = buy_value * .00003
    slippage = turnover * slippage_bps / 10_000
    return brokerage + exchange + sebi + gst + stt + stamp + slippage
