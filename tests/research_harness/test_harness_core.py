from datetime import date

import duckdb
import numpy as np

from research.harness import bars, costs, sim, stats


def arr(*xs):
    return np.array(xs, dtype=float)


# ---- costs ----

def test_cost_matches_saved_plan_replay_model():
    # Hand-computed: buy 100 sell 101 qty 100 at 5 bps slippage.
    buy_v, sell_v = 10_000.0, 10_100.0
    turnover = buy_v + sell_v
    brokerage = buy_v * .0003 + sell_v * .0003
    exchange, sebi = turnover * .0000307, turnover * .000001
    expected = (brokerage + exchange + sebi + .18 * (brokerage + exchange + sebi)
                + sell_v * .00025 + buy_v * .00003 + turnover * .0005)
    assert abs(costs.equity_intraday_cost(100, 101, 100) - expected) < 1e-9


def test_cost_sensitivity_to_slippage():
    assert costs.equity_intraday_cost(100, 100, 100, 20) > costs.equity_intraday_cost(100, 100, 100, 5)


# ---- sim.walk_exit ----

def test_long_stop_hit_pessimistic_when_bar_touches_both():
    o = arr(100, 100, 100); h = arr(100, 106, 100); l = arr(100, 94, 100)
    e = sim.walk_exit(o, h, l, np.array([555, 556, 557]), 0, 1, 95, 105, exit_minute=557)
    assert e.reason == 'STOP' and e.price == 95 and e.idx == 1


def test_gap_through_stop_exits_at_open():
    o = arr(100, 90, 90); h = arr(100, 91, 91); l = arr(100, 89, 89)
    e = sim.walk_exit(o, h, l, np.array([555, 556, 557]), 0, 1, 95, None, 999)
    assert (e.reason, e.price, e.idx) == ('STOP_GAP', 90.0, 1)


def test_short_target_and_time_exit():
    o = arr(100, 100, 99, 99); h = arr(100, 100.5, 99.5, 99.5); l = arr(100, 99.5, 97, 98)
    m = np.array([555, 556, 557, 558])
    assert sim.walk_exit(o, h, l, m, 0, -1, 102, 98, 999).reason == 'TARGET'
    e = sim.walk_exit(o, h, arr(100, 100.5, 99.5, 99.5), m, 0, -1, 102, None, 558)
    assert (e.reason, e.price) == ('TIME', 99.0)


def test_entry_bar_stop_is_checked():
    o = arr(100, 100); h = arr(101, 100); l = arr(94, 100)
    e = sim.walk_exit(o, h, l, np.array([555, 556]), 0, 1, 95, None, 556)
    assert e.reason == 'STOP' and e.idx == 0


def test_incomplete_data_returns_none():
    o = h = l = arr(100, 100)
    assert sim.walk_exit(o, h, l, np.array([555, 556]), 0, 1, 90, None, 900) is None


# ---- sizing / settle ----

def test_quantity_caps_by_risk_and_notional():
    s = sim.Sizing(risk_rupees=4000, max_notional=100_000)
    assert sim.quantity(1000, 990, s) == 100        # notional cap (100k/1000)
    assert sim.quantity(100, 80, s) == 200          # risk cap (4000/20)
    assert sim.quantity(100, 100, s) == 0


def test_settle_net_r_is_after_costs():
    r = sim.settle(1, 100, 110, 95, 100)
    assert abs(r['gross_r'] - 2.0) < 1e-9
    assert r['r'] < r['gross_r'] and r['cost'] > 0
    rs = sim.settle(-1, 100, 90, 105, 100)
    assert abs(rs['gross_r'] - 2.0) < 1e-9


# ---- stats ----

def test_signflip_detects_real_edge_and_not_noise():
    rng = np.random.default_rng(1)
    assert stats.signflip_p(rng.normal(0.3, 1, 500)) < 0.01
    assert stats.signflip_p(rng.normal(0.0, 1, 500)) > 0.05


def test_summary_and_gate():
    rng = np.random.default_rng(2)
    v = rng.normal(0.4, 1, 600)
    s = stats.summarize(v)
    assert s['n'] == 600 and s['t'] > 3
    yearly = {2019: (100, .3), 2020: (100, .2), 2021: (100, -.1)}
    assert stats.passes_gate(s, yearly, n_trials=6)
    assert not stats.passes_gate({**s, 'n': 100}, yearly, 6)
    assert not stats.passes_gate({**s, 'mean': -0.1}, yearly, 6)


def test_max_drawdown():
    assert stats.max_drawdown(np.array([1, -2, -1, 3])) == 3


# ---- bars loader ----

def _db():
    con = duckdb.connect(':memory:')
    con.execute('CREATE TABLE candles(symbol VARCHAR, interval VARCHAR, timestamp TIMESTAMP, '
                'open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT)')
    return con


def test_load_sessions_keeps_clean_days_and_counts_bad_ones():
    con = _db()
    rows = []
    for d, first, bad in [('2024-01-02', '09:15', False), ('2024-01-03', '09:16', False),
                          ('2024-01-04', '09:15', True)]:
        for k in range(5):
            hh, mm = divmod(int(first[:2]) * 60 + int(first[3:]) + k, 60)
            price = 0.0 if (bad and k == 2) else 100 + k
            rows.append(('X', '1m', f'{d} {hh:02d}:{mm:02d}:00', 100, 101 + k, 99, price or 100, 10))
            if bad and k == 2:
                rows[-1] = ('X', '1m', f'{d} {hh:02d}:{mm:02d}:00', 100, 99, 101, 100, 10)  # high<low
    con.executemany('INSERT INTO candles VALUES (?,?,?,?,?,?,?,?)', rows)
    sessions, dropped = bars.load_sessions(con, 'X')
    assert [s.day for s in sessions] == [date(2024, 1, 2)]
    assert dropped == {'bad_prices': 1, 'no_open_bar': 1, 'not_monotonic': 0}
    assert sessions[0].idx(bars.hhmm(9, 17)) == 2 and sessions[0].idx(bars.hhmm(9, 30)) == -1
