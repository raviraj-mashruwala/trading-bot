"""Factor scores must measure signal magnitude, not direction."""


def test_relative_strength_symmetric():
    """Stock outperforming by 10% and underperforming by 10% should score equally."""
    score_up = _compute_rs_score(stock_5d_return=15.0, nifty_5d_change=5.0)
    score_down = _compute_rs_score(stock_5d_return=-5.0, nifty_5d_change=5.0)
    assert score_up == score_down, f"Up {score_up} != Down {score_down}"
    assert score_up > 70, f"10% excess should score high, got {score_up}"


def test_relative_strength_neutral_at_zero():
    """Stock matching Nifty should score 50 (neutral)."""
    score = _compute_rs_score(stock_5d_return=5.0, nifty_5d_change=5.0)
    assert score == 50.0


def test_price_structure_symmetric():
    """Stock 10% above SMA20 and 10% below should score equally."""
    score_above = _compute_ps_score(pct_from_sma20=10.0)
    score_below = _compute_ps_score(pct_from_sma20=-10.0)
    assert score_above == score_below


def test_sector_momentum_symmetric():
    """Strong and weak sectors should score equally (both interesting)."""
    score_strong = _compute_sm_score(sector_median_return=5.0)
    score_weak = _compute_sm_score(sector_median_return=-5.0)
    assert score_strong == score_weak


def _compute_rs_score(stock_5d_return: float, nifty_5d_change: float) -> float:
    rs_excess = stock_5d_return - nifty_5d_change
    return min(100.0, max(0.0, 50.0 + abs(rs_excess) * 5.0))


def _compute_ps_score(pct_from_sma20: float) -> float:
    return min(100.0, max(0.0, 50.0 + abs(pct_from_sma20) * 5.0))


def _compute_sm_score(sector_median_return: float) -> float:
    return min(100.0, max(0.0, 50.0 + abs(sector_median_return) * 5.0))
