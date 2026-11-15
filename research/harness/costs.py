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


def futures_cost_bps(entry: float, exit_: float, side: int, slippage_bps: float,
                     lot_notional: float = 1_600_000.0, stt_rate: float = .0002) -> float:
    """Round-trip cost of one NSE futures lot in bps of entry notional.

    STT 0.02% on the sell leg (rate since Oct 2024; earlier years were 0.0125%, so older
    results are slightly pessimistic), exchange 0.00183%, SEBI 0.0001%, stamp 0.002% on the buy
    leg, brokerage Rs 20 per order, GST 18% on brokerage+exchange+SEBI. slippage_bps is per side.
    """
    buy, sell = (entry, exit_) if side == 1 else (exit_, entry)
    scale = lot_notional / entry
    buy_v, sell_v = buy * scale, sell * scale
    turnover = buy_v + sell_v
    brokerage = 40.0
    exchange, sebi = turnover * .0000183, turnover * .000001
    total = (brokerage + exchange + sebi + .18 * (brokerage + exchange + sebi)
             + sell_v * stt_rate + buy_v * .00002 + turnover * slippage_bps / 10_000)
    return total / lot_notional * 1e4
