"""I-series: intraday index-futures strategies, backtested on spot 1-minute bars with futures costs.

Pre-registered 2026-11-04 before any result. Spot NIFTY 50 / NIFTY BANK 1m bars stand in for futures
(Kite keeps no minute data for expired futures); costs are the futures schedule in costs.py. Bars are
start-labelled; signals use only bars that are complete at the decision time; fills at the next bar open.
One trade per day per index. Value per trade = net bps of notional. Exit time-based, no targets.

  I1a mom_last30  : sign of (09:15 open -> 09:45) return, trade 15:00 -> 15:20
  I1b mom_last30g : sign of (prev close -> 09:45) return incl. overnight gap, trade 15:00 -> 15:20
  I2a orb15_stop  : 09:15-09:29 range; first break 09:30-11:00; stop at opposite edge; exit 15:15
  I2b orb15_eod   : same entry, no stop, exit 15:15
  I3a gap_fade    : |gap| >= 0.4%: fade at the 09:16 open, exit 15:15
  I3b gap_follow  : same selection, follow
  I4  mid_mom     : sign of (09:15 open -> 12:00) return, trade 12:00 -> 15:15
Splits train 2015-20, valid 2021-23, holdout 2024-26 (single use, --confirm-holdout).
Trials for Bonferroni = 7 strategies x 2 indices = 14.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import duckdb
import numpy as np

from . import stats
from .bars import hhmm, load_sessions
from .costs import futures_cost_bps
from .daily_edges import SPLITS
from .sim import walk_exit

INDICES = ('NIFTY 50', 'NIFTY BANK')
STRATEGIES = ('mom_last30', 'mom_last30g', 'orb15_stop', 'orb15_eod', 'gap_fade', 'gap_follow', 'mid_mom')
SLIPS = (0.5, 1.0, 3.0)
GAP_MIN = .004
OUT_DIR = Path('research/output/harness')


def _timed(s, side: int, t_in: int, t_out: int):
    i, j = s.idx(t_in), s.idx(t_out)
    if i < 0 or j <= i:
        return None
    return float(s.open[i]), float(s.open[j])


def _signed_ret(s, t_from: int, t_to: int, ref: float | None = None) -> float | None:
    i, j = s.idx(t_from), s.idx(t_to)
    if i < 0 or j <= i:
        return None
    return float(s.open[j] / (ref if ref else s.open[i]) - 1)


def day_trades(s, prev_close: float | None) -> dict[str, tuple[int, float, float]]:
    """strategy -> (side, entry, exit) for one session."""
    out: dict[str, tuple[int, float, float]] = {}
    r = _signed_ret(s, hhmm(9, 15), hhmm(9, 45))
    if r:
        px = _timed(s, 0, hhmm(15, 0), hhmm(15, 20))
        if px:
            out['mom_last30'] = (int(np.sign(r)), *px)
    if prev_close and r is not None:
        rg = _signed_ret(s, hhmm(9, 15), hhmm(9, 45), prev_close)
        px = _timed(s, 0, hhmm(15, 0), hhmm(15, 20))
        if rg and px:
            out['mom_last30g'] = (int(np.sign(rg)), *px)
    # ORB15
    i15 = s.idx(hhmm(9, 29))
    if i15 == 14:
        hi, lo = float(s.high[:15].max()), float(s.low[:15].min())
        for j in range(15, len(s.minute)):
            if s.minute[j] > hhmm(11, 0):
                break
            side = 1 if s.high[j] > hi else (-1 if s.low[j] < lo else 0)
            if not side:
                continue
            if s.high[j] > hi and s.low[j] < lo:
                break  # both edges in one bar: ambiguous, skip the day
            entry = max(float(s.open[j]), hi) if side == 1 else min(float(s.open[j]), lo)
            for name, stop in (('orb15_stop', lo if side == 1 else hi), ('orb15_eod', 0.0 if side == 1 else 1e18)):
                ex = walk_exit(s.open, s.high, s.low, s.minute, j, side, stop, None, hhmm(15, 15))
                if ex:
                    out[name] = (side, entry, ex.price)
            break
    if prev_close:
        gap = float(s.open[0] / prev_close - 1)
        if abs(gap) >= GAP_MIN:
            px = _timed(s, 0, hhmm(9, 16), hhmm(15, 15))
            if px:
                out['gap_fade'] = (-int(np.sign(gap)), *px)
                out['gap_follow'] = (int(np.sign(gap)), *px)
    rm = _signed_ret(s, hhmm(9, 15), hhmm(12, 0))
    px = _timed(s, 0, hhmm(12, 0), hhmm(15, 15))
    if rm and px:
        out['mid_mom'] = (int(np.sign(rm)), *px)
    return out


def collect(con, index: str) -> list[dict]:
    sessions, dropped = load_sessions(con, index, '1m')
    rows, prev = [], None
    for s in sessions:
        pc = prev if prev is not None and (s.day - prev_day).days <= 5 else None
        for name, (side, entry, exit_) in day_trades(s, pc).items():
            gross = (exit_ - entry) * side / entry * 1e4
            row = {'date': s.day, 'index': index, 'strategy': name, 'side': side, 'gross_bps': gross}
            for sl in SLIPS:
                row[f'net_{sl}'] = gross - futures_cost_bps(entry, exit_, side, sl)
            rows.append(row)
        prev, prev_day = float(s.close[-1]), s.day
    print(f'{index}: {len(sessions)} clean sessions, dropped {dropped}')
    return rows


def report(rows: list[dict], start: str, end: str) -> bool:
    any_pass = False
    print(f"{'index':11}{'strategy':13}{'n':>5}{'gross':>8}{'net@.5':>8}{'net@1':>8}{'net@3':>8}{'t@1':>7}{'p':>7}{'win%':>6}  gate  years(net@1)")
    for idx in INDICES:
        for st in STRATEGIES:
            t = [r for r in rows if r['index'] == idx and r['strategy'] == st and start <= str(r['date']) < end]
            if len(t) < 30:
                continue
            v = np.array([r['net_1.0'] for r in t])
            sm = stats.summarize(v, n_perm=5000)
            yearly = stats.by_year([{**r, 'v': r['net_1.0']} for r in t], 'v')
            gate = stats.passes_gate(sm, yearly, n_trials=len(INDICES) * len(STRATEGIES))
            any_pass |= gate
            yrs = ' '.join(f'{y % 100:02d}:{m:+.0f}' for y, (_, m) in yearly.items())
            print(f"{idx:11}{st:13}{len(t):5}{np.mean([r['gross_bps'] for r in t]):8.1f}{np.mean([r['net_0.5'] for r in t]):8.1f}"
                  f"{v.mean():8.1f}{np.mean([r['net_3.0'] for r in t]):8.1f}{sm['t']:7.2f}{sm['p_signflip']:7.3f}{sm['win_rate']*100:6.1f}"
                  f"  {'PASS' if gate else '-':4}  {yrs}")
    return any_pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--split', choices=list(SPLITS), required=True)
    ap.add_argument('--confirm-holdout', action='store_true')
    ap.add_argument('--database', default='candles.duckdb')
    a = ap.parse_args()
    if a.split == 'holdout':
        if not a.confirm_holdout:
            raise SystemExit('holdout is single-use: pass --confirm-holdout to spend it')
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with (OUT_DIR / 'holdout_log.txt').open('a') as f:
            f.write(f'{dt.datetime.now().isoformat()} index_intraday\n')
    con = duckdb.connect(a.database, read_only=True)
    rows = [r for ix in INDICES for r in collect(con, ix)]
    start, end = SPLITS[a.split]
    print(f'\nindex_intraday split={a.split} {start}..{end}')
    print('GATE PASSED' if report(rows, start, end) else 'NO STRATEGY PASSES THE GATE')


if __name__ == '__main__':
    main()
