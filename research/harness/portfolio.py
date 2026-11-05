"""Portfolio-level simulation of an intraday futures strategy under real capital limits.

Takes per-trade records (entry/exit price, side, entry/exit minute, stop distance) and replays each day in time
order against: capital, margin per lot, lot quantisation, max concurrent positions, a per-trade risk cap in rupees
(one lot that risks more than the cap is skipped, it cannot be fractioned) and a daily realised-loss kill switch.

Approximations, stated so they are not forgotten:
* Lot = Rs LOT_NOTIONAL at the entry price (NSE keeps lots at Rs 5-10L; real lot sizes changed over the years).
* Margin = MARGIN_PCT of lot notional (SPAN + exposure, stock futures typically 15-25%).
* Fixed lots, no compounding. Costs: futures schedule + slippage per side.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from .costs import futures_cost_bps

LOT_NOTIONAL = 750_000.0
MARGIN_PCT = 0.20


@dataclass(frozen=True)
class Limits:
    capital: float = 400_000.0
    max_positions: int = 2
    risk_cap: float = 10_000.0       # max rupees a single trade may lose at its stop
    daily_loss_kill: float = 8_000.0  # stop new entries once realised loss today reaches this
    slippage_bps: float = 3.0


def lots_for(trade: dict, lim: Limits, free_margin: float) -> int:
    risk_per_lot = trade['risk_bps'] / 1e4 * LOT_NOTIONAL
    by_risk = math.floor(lim.risk_cap / risk_per_lot) if risk_per_lot > 0 else 0
    by_margin = math.floor(free_margin / (LOT_NOTIONAL * MARGIN_PCT))
    return max(0, min(by_risk, by_margin, 2))  # never more than 2 lots in one name


def simulate(trades: list[dict], lim: Limits) -> dict:
    by_day: dict = defaultdict(list)
    for t in trades:
        by_day[t['date']].append(t)
    taken, skips = [], defaultdict(int)
    for day in sorted(by_day):
        open_pos: list[dict] = []
        realised = 0.0
        for t in sorted(by_day[day], key=lambda x: (x['entry_min'], -x['rvol'])):
            for p in [p for p in open_pos if p['exit_min'] <= t['entry_min']]:
                open_pos.remove(p)
                realised += p['net']
            if realised <= -lim.daily_loss_kill:
                skips['daily_kill'] += 1
                continue
            if len(open_pos) >= lim.max_positions:
                skips['max_positions'] += 1
                continue
            used = sum(p['margin'] for p in open_pos)
            lots = lots_for(t, lim, lim.capital - used)
            if lots < 1:
                skips['risk_or_margin'] += 1
                continue
            notional = lots * LOT_NOTIONAL
            gross = (t['exit'] - t['entry']) * t['side'] / t['entry'] * notional
            cost = futures_cost_bps(t['entry'], t['exit'], t['side'], lim.slippage_bps, lot_notional=notional) * notional / 1e4
            pos = {'date': day, 'symbol': t['symbol'], 'lots': lots, 'net': gross - cost, 'gross': gross, 'cost': cost,
                   'exit_min': t['exit_min'], 'margin': notional * MARGIN_PCT}
            open_pos.append(pos)
            taken.append(pos)
    return summarize(taken, dict(skips), len(trades), lim)


def summarize(taken: list[dict], skips: dict, signals: int, lim: Limits) -> dict:
    if not taken:
        return {'trades': 0, 'signals': signals, 'skips': skips}
    by_day: dict = defaultdict(float)
    for p in taken:
        by_day[p['date']] += p['net']
    days = sorted(by_day)
    daily = np.array([by_day[d] for d in days])
    cum = np.cumsum(daily)
    dd = float((np.maximum.accumulate(np.concatenate(([0.0], cum)))[1:] - cum).max())
    months: dict = defaultdict(float)
    years: dict = defaultdict(float)
    for d in days:
        months[(d.year, d.month)] += by_day[d]
        years[d.year] += by_day[d]
    m = np.array(list(months.values()))
    span_years = max((days[-1] - days[0]).days / 365.25, 1 / 365.25)
    return {'trades': len(taken), 'signals': signals, 'skips': skips, 'total': float(cum[-1]),
            'per_year': float(cum[-1] / span_years), 'ret_pct_per_year': float(cum[-1] / span_years / lim.capital * 100),
            'min_cum': float(min(0.0, cum.min())), 'calmar': float(cum[-1] / span_years / dd) if dd else float('inf'),
            'max_dd': dd, 'max_dd_pct': dd / lim.capital * 100, 'worst_day': float(daily.min()),
            'best_day': float(daily.max()), 'avg_month': float(m.mean()), 'median_month': float(np.median(m)),
            'worst_month': float(m.min()), 'neg_months_pct': float((m < 0).mean() * 100),
            'avg_cost_per_trade': float(np.mean([p['cost'] for p in taken])),
            'avg_net_per_trade': float(np.mean([p['net'] for p in taken])),
            'by_year': {y: round(v) for y, v in sorted(years.items())},
            'avg_lots': float(np.mean([p['lots'] for p in taken]))}
