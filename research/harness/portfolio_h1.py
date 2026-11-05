"""Run the H1 futures strategy (k=0.5, RVOL>=1.5, with-direction) through the capital-constrained simulator."""

from __future__ import annotations

import duckdb

from . import h1_orb_in_play as H
from .portfolio import Limits, simulate
from .sim import Sizing

K, RVOL = 0.5, 1.5


def main() -> None:
    con = duckdb.connect('candles.duckdb', read_only=True)
    allt = H.run(con, '2019-01-01', '2027-01-01', 3.0, 25.0, Sizing(), futures=True)
    trades = [t for t in allt if t['mode'] == 'with' and t['k'] == K and t['rvol'] >= RVOL]
    print(f'signals (top-5 per day that triggered): {len(trades)}\n')
    print(f"{'pos':>3}{'riskcap':>8}{'slip':>5}{'trades':>7}{'$/yr':>9}{'ret%/yr':>8}{'maxDD':>8}{'DD%':>6}{'worstDay':>9}{'avg/mo':>8}{'neg%':>6}{'lots':>5}  skips")
    for pos in (1, 2):
        for risk_cap in (8_000, 12_000, 16_000):
            for slip in (3.0, 5.0, 6.0):
                r = simulate(trades, Limits(max_positions=pos, risk_cap=risk_cap, daily_loss_kill=8_000, slippage_bps=slip))
                if not r['trades']:
                    print(f'{pos:>3}{risk_cap:>8}{slip:>5}  no trades')
                    continue
                print(f"{pos:>3}{risk_cap:>8}{slip:>5}{r['trades']:>7}{r['per_year']:>9.0f}{r['ret_pct_per_year']:>8.1f}"
                      f"{r['max_dd']:>8.0f}{r['max_dd_pct']:>6.0f}{r['worst_day']:>9.0f}{r['avg_month']:>8.0f}{r['neg_months_pct']:>6.0f}"
                      f"{r['avg_lots']:>5.1f}  {r['skips']}")
    best = simulate(trades, Limits(max_positions=2, risk_cap=12_000, slippage_bps=3.0))
    print('\nper-year P&L (2 pos, risk cap 12k, 3 bps):', best['by_year'])


if __name__ == '__main__':
    main()
