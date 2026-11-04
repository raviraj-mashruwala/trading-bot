import numpy as np
import pandas as pd

from research.harness import costs, daily_edges as D


def test_vector_cost_matches_scalar_model():
    for side, entry, exit_ in ((1, 100.0, 101.0), (-1, 100.0, 98.0)):
        qty = D.NOTIONAL / entry
        buy, sell = (entry, exit_) if side == 1 else (exit_, entry)
        scalar = costs.equity_intraday_cost(buy, sell, qty, 10.0) / D.NOTIONAL * 1e4
        vec = D.cost_bps(np.array([entry]), np.array([exit_]), np.array([side]), 10.0)[0]
        assert abs(scalar - vec) < 1e-9


def _el():
    d = pd.Timestamp('2024-01-02')
    return pd.DataFrame({'d': [d] * 7, 'gap': [.06, .05, .04, .03, .025, .02, -.04],
                         'adr': [.02] * 7, 'prev_ret': [.10, .08, .06, .05, .04, .035, -.09]})


def test_gap_picks_top_five_by_score_and_fade_inverts_follow():
    follow, fade = D.pick(_el(), 'gap_follow'), D.pick(_el(), 'gap_fade')
    assert len(follow) == D.TOP_N and list(follow['gap']) == list(fade['gap'])
    assert (follow['side'] == -fade['side']).all()
    assert follow.loc[follow['gap'] > 0, 'side'].eq(1).all()


def test_reversal_shorts_winners_and_longs_losers():
    t = D.pick(_el(), 'reversal')
    assert (t.loc[t['prev_ret'] > 0, 'side'] == -1).all() and (t.loc[t['prev_ret'] < 0, 'side'] == 1).all()


def test_missing_ranges_resume_logic():
    from datetime import date
    from research.harness.fetch_fno_1m import missing_ranges
    s, today = date(2019, 1, 1), date(2026, 11, 4)
    assert missing_ranges(None, None, s, today) == [(s, today)]
    full = missing_ranges(date(2019, 1, 1), date(2026, 11, 3), s, today)
    assert full == []
    both = missing_ranges(date(2026, 1, 1), date(2026, 10, 30), s, today)
    assert both == [(s, date(2025, 12, 31)), (date(2026, 10, 31), today)]
