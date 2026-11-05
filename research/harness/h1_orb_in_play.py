"""H1: opening-range breakout on "stocks in play" (pre-registered 2026-11-04).

Frozen rules, written before any result was seen:
* Universe: symbols with >=1500 days of 1m history (excluding ETFs/indices), kept on a day
  only if their median daily turnover over the prior 20 sessions >= --liquid-cr crore
  (point-in-time, no lookahead) and the opening price >= Rs 100.
* In play: RVOL = volume of the 09:15-09:19 bars / mean of the same window over the prior
  14 sessions (needs >=10). Keep RVOL >= min_rvol, rank by RVOL, trade the top 5 per day.
  Days within 14 sessions of a >35% close-to-close jump (unadjusted splits) are excluded.
* Direction: colour of the first 5-minute candle (09:15-09:19). Doji skipped.
* Entry: stop-entry on a break of that candle's high (long) / low (short), scanned from
  09:20 to 11:00. Fill = max(bar open, level) long / min(bar open, level) short.
* Stop: k x ADR14 away from the fill, ADR14 = mean of (high-low)/close over the prior 14
  sessions. No target. Exit at the 15:10 bar open at the latest.
* Grid (all of it, the number of trials): k in {0.25, 0.5, 1.0} x min_rvol in {1.5, 2.0}.
* Control (diagnostic, not a trial): same selection, trade AGAINST the first candle.
Tune on train, confirm on valid, touch holdout once with --confirm-holdout.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from collections import defaultdict
from pathlib import Path

import duckdb
import numpy as np

from . import stats
from .bars import Session, hhmm, load_sessions
from .costs import futures_cost_bps
from .sim import Sizing, quantity, settle, walk_exit

K_GRID = (0.25, 0.5, 1.0)
RVOL_GRID = (1.5, 2.0)
TOP_N = 5
ENTRY_FROM, ENTRY_UNTIL, EXIT_AT = hhmm(9, 20), hhmm(11, 0), hhmm(15, 10)
MIN_PRICE, LOOKBACK = 100.0, 14
NOT_STOCKS = ('BANKNIFTY1',)
ETF_HINTS = ('BEES', 'ETF', 'NIFTY', 'GOLD')
OUT_DIR = Path('research/output/harness')


def universe(con) -> list[str]:
    rows = con.execute("SELECT symbol FROM (SELECT symbol, COUNT(DISTINCT timestamp::DATE) d FROM candles "
                       "WHERE interval='1m' GROUP BY 1) WHERE d>=1500 ORDER BY 1").fetchall()
    return [s for (s,) in rows if s not in NOT_STOCKS and not any(h in s for h in ETF_HINTS)]


def day_features(sessions: list[Session]) -> list[dict]:
    """Point-in-time features: each row only uses sessions strictly before its own day."""
    feats: list[dict] = []
    hist: list[dict] = []
    for s in sessions:
        i4 = s.idx(hhmm(9, 19))
        row = {'day': s.day}
        close = s.close[-1]
        raw = {'vol5': float(s.volume[:5].sum()) if i4 == 4 else np.nan,
               'range_pct': float((s.high.max() - s.low.min()) / close),
               'turnover': float((s.close * s.volume).sum()), 'close': float(close),
               'jump': abs(close / hist[-1]['close'] - 1) > 0.35 if hist else False}
        prior = hist[-LOOKBACK:]
        usable = [p['vol5'] for p in prior if np.isfinite(p['vol5'])]
        ok = (i4 == 4 and len(usable) >= 10 and np.mean(usable) > 0
              and not raw['jump'] and not any(p['jump'] for p in prior))
        if ok:
            liq = hist[-20:]
            row.update(rvol=raw['vol5'] / np.mean(usable),
                       adr=float(np.mean([p['range_pct'] for p in prior])),
                       turnover20=float(np.median([p['turnover'] for p in liq])),
                       open_price=float(s.open[0]),
                       first_dir=int(np.sign(s.close[4] - s.open[0])))
            feats.append(row)
        hist.append(raw)
    return feats


FNO_FILE = Path(__file__).with_name('fno_universe.txt')


def fno_universe(con, min_days: int = 1000) -> list[str]:
    names = [n for n in FNO_FILE.read_text().split() if n]
    q = ','.join("'" + n.replace("'", "''") + "'" for n in names)
    rows = con.execute(f"SELECT symbol FROM (SELECT symbol, COUNT(DISTINCT timestamp::DATE) d FROM candles "
                       f"WHERE interval='1m' AND symbol IN ({q}) GROUP BY 1) WHERE d>={min_days} ORDER BY 1").fetchall()
    return [s for (s,) in rows]


def settle_futures(side: int, entry: float, exit_price: float, stop: float, slippage_bps: float) -> dict:
    """Per-unit settle with futures costs (fractional lots; brokerage assumes a Rs 6L lot)."""
    gross_bps = (exit_price - entry) * side / entry * 1e4
    cost = futures_cost_bps(entry, exit_price, side, slippage_bps, lot_notional=600_000.0)
    risk_bps = abs(entry - stop) / entry * 1e4
    return {'qty': 1, 'gross': gross_bps, 'cost': cost, 'net': gross_bps - cost,
            'gross_r': gross_bps / risk_bps, 'r': (gross_bps - cost) / risk_bps, 'net_bps': gross_bps - cost}


def simulate_day(s: Session, side: int, k: float, adr: float, slippage_bps: float,
                 sizing: Sizing, futures: bool = False) -> dict | None:
    hi, lo = float(s.high[:5].max()), float(s.low[:5].min())
    for j in range(5, len(s.minute)):
        if s.minute[j] > ENTRY_UNTIL:
            return None
        if s.minute[j] < ENTRY_FROM:
            continue
        broke = s.high[j] > hi if side == 1 else s.low[j] < lo
        if not broke:
            continue
        fill = max(s.open[j], hi) if side == 1 else min(s.open[j], lo)
        stop = fill * (1 - side * k * adr)
        qty = quantity(fill, stop, sizing)
        if qty < 1:
            return None
        ex = walk_exit(s.open, s.high, s.low, s.minute, j, side, stop, None, EXIT_AT)
        if ex is None:
            return None
        done = (settle_futures(side, fill, ex.price, stop, slippage_bps) if futures
                else settle(side, fill, ex.price, stop, qty, slippage_bps))
        return {'entry': fill, 'exit': ex.price, 'reason': ex.reason, **done}
    return None


def run(con, start: str, end: str, slippage_bps: float, liquid_cr: float, sizing: Sizing,
        futures: bool = False) -> list[dict]:
    warm = (dt.date.fromisoformat(start) - dt.timedelta(days=120)).isoformat()
    lo_d, hi_d = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    rows: list[dict] = []
    for sym in (fno_universe(con) if futures else universe(con)):
        sessions, _ = load_sessions(con, sym, '1m', warm, end)
        for f in day_features(sessions):
            if lo_d <= f['day'] < hi_d and f['first_dir'] != 0 and f['open_price'] >= MIN_PRICE \
                    and f['turnover20'] >= liquid_cr * 1e7 and f['rvol'] >= min(RVOL_GRID):
                rows.append({'symbol': sym, **f})
    by_day: dict[dt.date, list[dict]] = defaultdict(list)
    for r in rows:
        by_day[r['day']].append(r)
    picks = {d: sorted(v, key=lambda r: -r['rvol'])[:TOP_N] for d, v in by_day.items()}
    needed: dict[str, set] = defaultdict(set)
    for d, v in picks.items():
        for r in v:
            needed[r['symbol']].add(d)
    out: list[dict] = []
    for sym, days in needed.items():
        sessions, _ = load_sessions(con, sym, '1m', start, end)
        lookup = {s.day: s for s in sessions}
        for d in days:
            r = next(x for x in picks[d] if x['symbol'] == sym)
            s = lookup.get(d)
            if s is None:
                continue
            for mode, side in (('with', r['first_dir']), ('against', -r['first_dir'])):
                for k in K_GRID:
                    t = simulate_day(s, side, k, r['adr'], slippage_bps, sizing, futures)
                    if t:
                        out.append({'date': d, 'symbol': sym, 'mode': mode, 'k': k,
                                    'rvol': r['rvol'], 'side': side, **t})
    return out


def report(trades: list[dict]) -> bool:
    n_trials = len(K_GRID) * len(RVOL_GRID)
    any_pass = False
    print(f"{'mode':8}{'k':>5}{'rvol':>6}{'n':>6}{'netR':>8}{'grossR':>8}{'t':>7}{'p':>8}{'win%':>6}{'bps':>8}  gate  years(net R)")
    for mode in ('with', 'against'):
        for k in K_GRID:
            for mr in RVOL_GRID:
                sel = [t for t in trades if t['mode'] == mode and t['k'] == k and t['rvol'] >= mr]
                sm = stats.summarize([t['r'] for t in sel], n_perm=5000)
                if sm['n'] < 2:
                    print(f'{mode:8}{k:5}{mr:6}{sm["n"]:6}   (too few trades)')
                    continue
                yearly = stats.by_year(sel, 'r')
                gross = np.nanmean([t['gross_r'] for t in sel])
                bps = np.nanmean([t['net_bps'] for t in sel])
                gate = stats.passes_gate(sm, yearly, n_trials) if mode == 'with' else False
                any_pass |= gate
                yrs = ' '.join(f'{y}:{m:+.2f}' for y, (_, m) in yearly.items())
                print(f"{mode:8}{k:5}{mr:6}{sm['n']:6}{sm['mean']:8.3f}{gross:8.3f}{sm['t']:7.2f}"
                      f"{sm['p_signflip']:8.3f}{sm['win_rate']*100:6.1f}{bps:8.1f}  {'PASS' if gate else '-':4}  {yrs}")
    return any_pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--split', choices=list(stats.SPLITS), required=True)
    ap.add_argument('--confirm-holdout', action='store_true')
    ap.add_argument('--slippage-bps', type=float, default=5.0)
    ap.add_argument('--liquid-cr', type=float, default=25.0)
    ap.add_argument('--database', default='candles.duckdb')
    ap.add_argument('--futures', action='store_true', help='F&O universe, futures cost model (use --slippage-bps 3)')
    a = ap.parse_args()
    if a.split == 'holdout':
        if not a.confirm_holdout:
            raise SystemExit('holdout is single-use: pass --confirm-holdout to spend it')
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with (OUT_DIR / 'holdout_log.txt').open('a') as f:
            f.write(f'{dt.datetime.now().isoformat()} h1{"-futures" if a.futures else ""} slippage={a.slippage_bps} liquid_cr={a.liquid_cr}\n')
    con = duckdb.connect(a.database, read_only=True)
    start, end = stats.SPLITS[a.split]
    trades = run(con, start, end, a.slippage_bps, a.liquid_cr, Sizing(), a.futures)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f'h1{"f" if a.futures else ""}_{a.split}.csv'
    if trades:
        with path.open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(trades[0]))
            w.writeheader()
            w.writerows(trades)
    print(f'h1 split={a.split} {start}..{end} slippage={a.slippage_bps}bps liquid>={a.liquid_cr}cr trades={len(trades)}')
    print('GATE PASSED' if report(trades) else 'NO CONFIG PASSES THE GATE')


if __name__ == '__main__':
    main()
