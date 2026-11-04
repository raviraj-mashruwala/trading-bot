"""D1: open-to-close edges testable on daily OHLC, 2015-2026, ~800-1,600 symbols.

Pre-registered 2026-11-04 before any result was seen. Every trade enters at the day's open and
exits at the day's close (pure intraday, flat overnight), notional Rs 1L, net of the full NSE
intraday cost schedule plus slippage per side (default 10 bps because opens are wide).

Eligibility on day t, all point-in-time (uses sessions before t only):
  median daily turnover over prior 20 sessions >= 25 cr, open >= Rs 50, ADR14 defined,
  |gap| <= 25% (drops corporate-action artefacts), no locked bar (high == low).
Signals, each trading the top 5 names per day by |score|:
  A gap_follow : score = gap/ADR14, need |score| >= 1.5, side = sign(gap)
  B gap_fade   : same selection as A, side = -sign(gap)
  C reversal   : score = prior-day close-to-close return, need |ret| >= 3%, side = -sign(ret)
  D momentum   : same selection as C, side = +sign(ret)
A/B and C/D are each other's control: if neither side is positive net, there is no edge.
Splits: train 2015-2020, valid 2021-2023, holdout 2024-2026 (single use, --confirm-holdout).
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from . import stats

SPLITS = {'train': ('2015-01-01', '2021-01-01'), 'valid': ('2021-01-01', '2024-01-01'),
          'holdout': ('2024-01-01', '2027-01-01')}
TOP_N, NOTIONAL, MIN_TURNOVER, MIN_PRICE = 5, 100_000.0, 2.5e8, 50.0
STRATEGIES = ('gap_follow', 'gap_fade', 'reversal', 'momentum')
OUT_DIR = Path('research/output/harness')


def cost_bps(entry: np.ndarray, exit_: np.ndarray, side: np.ndarray, slippage_bps: float) -> np.ndarray:
    """Vectorised twin of costs.equity_intraday_cost for NOTIONAL rupees at entry."""
    qty = NOTIONAL / entry
    buy = np.where(side == 1, entry, exit_) * qty
    sell = np.where(side == 1, exit_, entry) * qty
    turnover = buy + sell
    brokerage = np.minimum(20.0, buy * .0003) + np.minimum(20.0, sell * .0003)
    exchange, sebi = turnover * .0000307, turnover * .000001
    total = (brokerage + exchange + sebi + .18 * (brokerage + exchange + sebi)
             + sell * .00025 + buy * .00003 + turnover * slippage_bps / 10_000)
    return total / NOTIONAL * 1e4


def load_features(con) -> pd.DataFrame:
    df = con.execute("SELECT symbol, timestamp::DATE AS d, open, high, low, close, volume "
                     "FROM candles WHERE interval='day' AND open>0 AND close>0 AND high>=low "
                     "ORDER BY symbol, d").df()
    df['d'] = pd.to_datetime(df['d'])
    g = df.groupby('symbol', sort=False)
    prev_close, prev_close2 = g['close'].shift(1), g['close'].shift(2)
    df['gap'] = df['open'] / prev_close - 1
    df['prev_ret'] = prev_close / prev_close2 - 1
    df['oc'] = df['close'] / df['open'] - 1
    df['co'] = df['gap']
    df['range_pct'] = (df['high'] - df['low']) / df['close']
    df['turnover'] = df['close'] * df['volume']
    df['adr'] = g['range_pct'].transform(lambda x: x.shift(1).rolling(14, min_periods=10).mean())
    df['liq'] = g['turnover'].transform(lambda x: x.shift(1).rolling(20, min_periods=15).median())
    df['stale'] = (df['d'] - g['d'].shift(2)).dt.days > 10  # missing rows around the signal
    return df


def eligible(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    m = ((df['d'] >= start) & (df['d'] < end) & (df['liq'] >= MIN_TURNOVER) & (df['open'] >= MIN_PRICE)
         & df['adr'].notna() & df['gap'].notna() & df['prev_ret'].notna()
         & (df['gap'].abs() <= .25) & (df['high'] > df['low']) & ~df['stale'])
    return df[m].copy()


def pick(el: pd.DataFrame, strategy: str) -> pd.DataFrame:
    if strategy in ('gap_follow', 'gap_fade'):
        el = el.assign(score=el['gap'] / el['adr'])
        el = el[el['score'].abs() >= 1.5]
        base = np.sign(el['gap'])
    else:
        el = el.assign(score=el['prev_ret'])
        el = el[el['score'].abs() >= .03]
        base = np.sign(el['prev_ret'])
    side = base if strategy in ('gap_follow', 'momentum') else -base
    el = el.assign(side=side.astype(int), absscore=el['score'].abs())
    return (el.sort_values(['d', 'absscore'], ascending=[True, False]).groupby('d').head(TOP_N))


def run(df: pd.DataFrame, start: str, end: str, slippage_bps: float) -> dict[str, pd.DataFrame]:
    el = eligible(df, start, end)
    out = {}
    for s in STRATEGIES:
        t = pick(el, s)
        gross = t['side'] * t['oc'] * 1e4
        net = gross - cost_bps(t['open'].to_numpy(), t['close'].to_numpy(), t['side'].to_numpy(), slippage_bps)
        out[s] = t.assign(gross_bps=gross, net_bps=net)
    return out


def drift_table(df: pd.DataFrame, start: str, end: str) -> None:
    el = eligible(df, start, end)
    el['y'] = el['d'].dt.year
    tab = el.groupby('y').agg(n=('oc', 'size'), overnight_bps=('co', lambda x: x.mean() * 1e4),
                              intraday_bps=('oc', lambda x: x.mean() * 1e4))
    print('Universe drift, equal weight, eligible names (bps/day):')
    print(tab.round(1).to_string())


def report(results: dict[str, pd.DataFrame]) -> bool:
    print(f"{'strategy':11}{'n':>7}{'grossbps':>10}{'netbps':>9}{'t':>7}{'p':>8}{'win%':>6}  gate  years(net bps)")
    any_pass = False
    for s, t in results.items():
        if len(t) < 30:
            print(f'{s:11}{len(t):7}  (too few)')
            continue
        recs = [{'date': d.date(), 'v': v} for d, v in zip(t['d'], t['net_bps'])]
        sm = stats.summarize(t['net_bps'].to_numpy(), n_perm=5000)
        yearly = stats.by_year(recs, 'v')
        gate = stats.passes_gate(sm, yearly, n_trials=len(STRATEGIES))
        any_pass |= gate
        yrs = ' '.join(f'{y % 100:02d}:{m:+.0f}' for y, (_, m) in yearly.items())
        print(f"{s:11}{sm['n']:7}{t['gross_bps'].mean():10.1f}{sm['mean']:9.1f}{sm['t']:7.2f}"
              f"{sm['p_signflip']:8.3f}{sm['win_rate']*100:6.1f}  {'PASS' if gate else '-':4}  {yrs}")
    return any_pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--split', choices=list(SPLITS), required=True)
    ap.add_argument('--confirm-holdout', action='store_true')
    ap.add_argument('--slippage-bps', type=float, default=10.0)
    ap.add_argument('--database', default='candles.duckdb')
    a = ap.parse_args()
    if a.split == 'holdout':
        if not a.confirm_holdout:
            raise SystemExit('holdout is single-use: pass --confirm-holdout to spend it')
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with (OUT_DIR / 'holdout_log.txt').open('a') as f:
            f.write(f'{dt.datetime.now().isoformat()} d1 slippage={a.slippage_bps}\n')
    df = load_features(duckdb.connect(a.database, read_only=True))
    start, end = SPLITS[a.split]
    drift_table(df, start, end)
    print(f'\nd1 split={a.split} {start}..{end} slippage={a.slippage_bps}bps top{TOP_N}/day')
    print('GATE PASSED' if report(run(df, start, end, a.slippage_bps)) else 'NO STRATEGY PASSES THE GATE')


if __name__ == '__main__':
    main()
