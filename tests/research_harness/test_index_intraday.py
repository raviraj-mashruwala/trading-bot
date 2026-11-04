import datetime as dt

import numpy as np

from research.harness import costs, index_intraday as I
from research.harness.bars import Session, hhmm


def session(prices_by_minute: dict[int, float], day=dt.date(2024, 1, 2)) -> Session:
    minutes = np.arange(hhmm(9, 15), hhmm(15, 30))
    px = np.interp(minutes, list(prices_by_minute), list(prices_by_minute.values()))
    return Session(day, minutes, px, px + .5, px - .5, px, np.zeros(len(minutes)))


def test_futures_cost_is_a_few_bps_not_equity_scale():
    c = costs.futures_cost_bps(50_000, 50_000, 1, 1.0)
    assert 3 < c < 8                         # ~5 bps round trip incl. 2 bps slippage
    assert costs.futures_cost_bps(50_000, 50_000, 1, 3.0) > c
    assert costs.futures_cost_bps(50_000, 50_000, 1, 0.0) < 3.5


def test_momentum_follows_first_half_hour_and_trades_last_window():
    s = session({hhmm(9, 15): 100.0, hhmm(9, 45): 101.0, hhmm(15, 0): 101.0, hhmm(15, 20): 102.0, hhmm(15, 29): 102.0})
    side, entry, exit_ = I.day_trades(s, None)['mom_last30']
    assert side == 1 and entry == 101.0 and exit_ == 102.0


def test_gap_fade_is_inverse_of_follow_and_needs_threshold():
    s = session({hhmm(9, 15): 101.0, hhmm(15, 29): 100.0})
    t = I.day_trades(s, 100.0)               # +1% gap
    assert t['gap_fade'][0] == -1 and t['gap_follow'][0] == 1
    assert 'gap_fade' not in I.day_trades(session({hhmm(9, 15): 100.1, hhmm(15, 29): 100.0}), 100.0)


def test_orb_stop_vs_eod_diverge_when_stopped_out():
    pts = {hhmm(9, 15): 100.0, hhmm(9, 29): 100.0, hhmm(9, 40): 102.0, hhmm(10, 30): 98.0, hhmm(15, 29): 98.0}
    t = I.day_trades(session(pts), None)
    assert t['orb15_stop'][0] == 1 and t['orb15_stop'][2] != t['orb15_eod'][2]
