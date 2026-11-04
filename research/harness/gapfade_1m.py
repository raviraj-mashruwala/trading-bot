"""Execution-realism backtest of the D1 gap-fade strategy on 1-minute bars (2019-2026).

Same selection as daily_edges.gap_fade: liquid names (>= 25 cr, point-in-time), gap >= 1.5 x ADR14,
top 5 per day by |gap|/ADR14, side = against the gap, flat the same day. Fixed variants, no grid search:
  entry at the 09:15 open (idealised auction fill), 09:16 open (1 min late), 09:20 open (5 min late)
  stop: none, or 1.0 x ADR14 from entry (chosen a priori, not tuned)
  exit: 15:10 bar open (the bot's square-off), slippage 5/10/20 bps per side.
Universe is the ~65 long-history 1m symbols, so n is far smaller than the daily test.
"""

from __future__ import annotations

import argparse
from collections import defaultdict

import duckdb
import numpy as np

from . import stats
from .bars import hhmm, load_sessions
from .h1_orb_in_play import MIN_PRICE, universe
from .sim import settle, walk_exit

ENTRIES = {'0915': hhmm(9, 15), '0916': hhmm(9, 16), '0920': hhmm(9, 20)}
STOPS = {'nostop': None, 'stop1adr': 1.0}
SLIPS = (5.0, 10.0, 20.0)
EXIT_AT, NOTIONAL, TOP_N, MIN_SCORE, MIN_TURNOVER = hhmm(15, 10), 100_000.0, 5, 1.5, 2.5e8


def features(sessions) -> list[dict]:
    out, hist = [], []
    for s in sessions:
        close = float(s.close[-1])
        raw = {'range_pct': float((s.high.max() - s.low.min()) / close), 'turnover': float((s.close * s.volume).sum()),
               'close': close, 'day': s.day, 'jump': False}
        if hist:
            raw['jump'] = abs(s.open[0] / hist[-1]['close'] - 1) > .25 or abs(close / hist[-1]['close'] - 1) > .35
            prior = hist[-14:]
            if len(prior) >= 10 and (s.day - hist[-1]['day']).days <= 5 and not any(p['jump'] for p in prior) \
                    and not raw['jump'] and len(hist) >= 15:
                adr = float(np.mean([p['range_pct'] for p in prior]))
                gap = float(s.open[0] / hist[-1]['close'] - 1)
                liq = float(np.median([p['turnover'] for p in hist[-20:]]))
                if adr > 0 and liq >= MIN_TURNOVER and s.open[0] >= MIN_PRICE:
                    out.append({'day': s.day, 'adr': adr, 'gap': gap, 'score': abs(gap) / adr})
        hist.append(raw)
    return out


def collect(con, slips=SLIPS) -> list[dict]:
    cand: dict = defaultdict(list)
    for sym in universe(con):
        sessions, _ = load_sessions(con, sym, '1m', '2018-10-01', '2027-01-01')
        for f in features(sessions):
            if f['score'] >= MIN_SCORE and f['day'].year >= 2019:
                cand[f['day']].append({'symbol': sym, **f})
    picks = {d: sorted(v, key=lambda r: -r['score'])[:TOP_N] for d, v in cand.items()}
    need: dict = defaultdict(dict)
    for d, v in picks.items():
        for r in v:
            need[r['symbol']][d] = r
    trades = []
    for sym, days in need.items():
        sessions, _ = load_sessions(con, sym, '1m', '2019-01-01', '2027-01-01')
        for s in sessions:
            r = days.get(s.day)
            if r is None:
                continue
            side = -int(np.sign(r['gap']))
            for en, em in ENTRIES.items():
                i = s.idx(em)
                if i < 0:
                    continue
                entry = float(s.open[i])
                qty = int(NOTIONAL / entry)
                if qty < 1:
                    continue
                for sn, mult in STOPS.items():
                    stop = entry * (1 - side * mult * r['adr']) if mult else (0.0 if side == 1 else 1e18)
                    ex = walk_exit(s.open, s.high, s.low, s.minute, i, side, stop, None, EXIT_AT)
                    if ex is None:
                        continue
                    row = {'date': s.day, 'symbol': sym, 'side': side, 'entry': en, 'stop': sn, 'reason': ex.reason,
                           'gross_bps': (ex.price - entry) * side / entry * 1e4}
                    for sl in slips:
                        row[f'net_{int(sl)}'] = settle(side, entry, ex.price, stop if mult else entry * .99, qty, sl)['net_bps']
                    trades.append(row)
    return trades


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    trades = collect(duckdb.connect('candles.duckdb', read_only=True))
    for name, (a, b) in stats.SPLITS.items():
        print(f'\n== {name} {a}..{b}')
        print(f"{'entry':6}{'stop':10}{'n':>5}{'gross':>8}{'net5':>8}{'net10':>8}{'net20':>8}{'t@10':>7}{'win%':>6}{'med10':>8}")
        for en in ENTRIES:
            for sn in STOPS:
                t = [x for x in trades if x['entry'] == en and x['stop'] == sn and a <= str(x['date']) < b]
                if len(t) < 30:
                    print(f'{en:6}{sn:10}{len(t):5} (too few)')
                    continue
                v10 = np.array([x['net_10'] for x in t])
                sm = stats.summarize(v10, n_perm=2000)
                print(f"{en:6}{sn:10}{len(t):5}{np.mean([x['gross_bps'] for x in t]):8.1f}{np.mean([x['net_5'] for x in t]):8.1f}"
                      f"{v10.mean():8.1f}{np.mean([x['net_20'] for x in t]):8.1f}{sm['t']:7.2f}{sm['win_rate']*100:6.1f}{np.median(v10):8.1f}")


if __name__ == '__main__':
    main()
