import datetime as dt

from research.harness.portfolio import Limits, simulate


def tr(day, minute, exit_min, risk_bps=100.0, rvol=2.0, entry=100.0, exit_=101.0, side=1, sym='X'):
    return {'date': day, 'symbol': sym, 'entry_min': minute, 'exit_min': exit_min, 'risk_bps': risk_bps,
            'rvol': rvol, 'entry': entry, 'exit': exit_, 'side': side}


D = dt.date(2024, 1, 2)


def test_max_positions_blocks_third_concurrent_trade():
    r = simulate([tr(D, 560, 900), tr(D, 561, 900), tr(D, 562, 900)], Limits(max_positions=2))
    assert r['trades'] == 2 and r['skips']['max_positions'] == 1


def test_position_closed_before_next_entry_frees_slot():
    r = simulate([tr(D, 560, 570), tr(D, 580, 900)], Limits(max_positions=1))
    assert r['trades'] == 2


def test_single_lot_over_risk_cap_is_skipped_not_fractioned():
    # 200 bps stop on Rs 7.5L = Rs 15,000 risk per lot > cap 10,000
    r = simulate([tr(D, 560, 900, risk_bps=200.0)], Limits(risk_cap=10_000))
    assert r['trades'] == 0 and r['skips']['risk_or_margin'] == 1


def test_daily_loss_kill_blocks_later_entries():
    losers = tr(D, 560, 565, exit_=90.0)  # -10% on 1 lot
    r = simulate([losers, tr(D, 600, 900)], Limits(max_positions=2, daily_loss_kill=8_000))
    assert r['trades'] == 1 and r['skips']['daily_kill'] == 1


def test_costs_reduce_gross_and_slippage_matters():
    a = simulate([tr(D, 560, 900)], Limits(slippage_bps=1.0))['total']
    b = simulate([tr(D, 560, 900)], Limits(slippage_bps=8.0))['total']
    assert a > b
