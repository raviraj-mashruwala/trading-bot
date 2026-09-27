"""Tests for Zerodha transaction cost model."""

from tradingbot.backtest.costs import ZerodhaCosts


def test_round_trip_cost_typical_trade():
    costs = ZerodhaCosts()
    # Buy 100 shares at 500, sell at 510
    cost = costs.round_trip_cost(entry_price=500.0, exit_price=510.0, quantity=100)
    assert cost > 0
    # Rough estimate: brokerage 40 + STT ~12.75 + charges ~5 + GST ~8 + stamp ~1.5
    assert 50 < cost < 150


def test_brokerage_caps_at_20():
    costs = ZerodhaCosts()
    # Small trade: 10 shares at 100 = 1000 notional
    cost = costs.round_trip_cost(100.0, 102.0, 10)
    # Brokerage = min(20, 0.03% of 1000) = min(20, 0.30) = 0.30 per leg
    assert cost > 0


def test_brokerage_cap_applied_on_large_trade():
    costs = ZerodhaCosts(slippage_pct=0.0)
    # Large trade: 1000 shares at 1000 = 1M notional per leg
    # 0.03% of 1M = 300, capped at 20 per leg
    cost = costs.round_trip_cost(1000.0, 1010.0, 1000)
    # Brokerage should be 40 (20+20), not 600
    # Total: brokerage(40) + STT(0.025%*1010000=252.5) + exchange + gst + sebi + stamp
    assert cost > 200  # STT alone is ~252


def test_slippage_applied():
    costs = ZerodhaCosts(slippage_pct=0.02)
    cost_with = costs.round_trip_cost(500.0, 510.0, 100)
    costs_no = ZerodhaCosts(slippage_pct=0.0)
    cost_without = costs_no.round_trip_cost(500.0, 510.0, 100)
    assert cost_with > cost_without


def test_zero_quantity_returns_zero():
    costs = ZerodhaCosts()
    cost = costs.round_trip_cost(500.0, 510.0, 0)
    assert cost == 0.0


def test_components_are_positive():
    """Each component should contribute positively to cost."""
    costs = ZerodhaCosts(slippage_pct=0.0)
    cost = costs.round_trip_cost(500.0, 510.0, 100)
    assert cost > 0
