"""Intraday trade simulation on 1-minute bars, pessimistic by construction.

Rules (fixed, not tunable):
* Stops are checked before targets inside a bar, so a bar touching both counts
  as a stop. The entry bar is checked too, because the order inside it is unknown.
* A bar that opens beyond a stop/target exits at its open (gap fill).
* The time exit fills at the open of the first bar at/after exit_minute.
* A trade that cannot reach its time exit (data ends early) returns None and is skipped.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .costs import equity_intraday_cost


@dataclass(frozen=True)
class Exit:
    price: float
    idx: int
    reason: str


def walk_exit(o: np.ndarray, h: np.ndarray, l: np.ndarray, minute: np.ndarray,
              entry_idx: int, side: int, stop: float, target: float | None,
              exit_minute: int) -> Exit | None:
    """side = +1 long, -1 short. Entry fill happened inside bar entry_idx."""
    long = side == 1
    for j in range(entry_idx, len(o)):
        if minute[j] >= exit_minute:
            return None if j == entry_idx else Exit(float(o[j]), j, 'TIME')
        if j > entry_idx:
            if (o[j] <= stop) if long else (o[j] >= stop):
                return Exit(float(o[j]), j, 'STOP_GAP')
            if target is not None and ((o[j] >= target) if long else (o[j] <= target)):
                return Exit(float(o[j]), j, 'TARGET_GAP')
        if (l[j] <= stop) if long else (h[j] >= stop):
            return Exit(float(stop), j, 'STOP')
        if target is not None and ((h[j] >= target) if long else (l[j] <= target)):
            return Exit(float(target), j, 'TARGET')
    return None


@dataclass(frozen=True)
class Sizing:
    """Defaults mirror the bot's real limits: 1% of Rs 4L risked, <=50% of capital in 2 legs."""
    risk_rupees: float = 4000.0
    max_notional: float = 100_000.0


def quantity(entry: float, stop: float, sizing: Sizing) -> int:
    per_share = abs(entry - stop)
    if per_share <= 0:
        return 0
    return max(0, int(min(sizing.risk_rupees / per_share, sizing.max_notional / entry)))


def settle(side: int, entry: float, exit_price: float, stop: float, qty: int,
           slippage_bps: float = 5.0) -> dict:
    """Gross/net rupee P&L and net R (net P&L over rupees actually risked)."""
    gross = (exit_price - entry) * qty * side
    buy, sell = (entry, exit_price) if side == 1 else (exit_price, entry)
    cost = equity_intraday_cost(buy, sell, qty, slippage_bps)
    risk = abs(entry - stop) * qty
    net = gross - cost
    return {'qty': qty, 'gross': gross, 'cost': cost, 'net': net,
            'gross_r': gross / risk if risk else math.nan,
            'r': net / risk if risk else math.nan,
            'net_bps': net / (entry * qty) * 10_000 if qty else math.nan}
