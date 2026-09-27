from unittest.mock import MagicMock
from tradingbot.execution.safety import SafetyManager


def test_daily_loss_not_breached():
    mgr = SafetyManager(capital=400000, max_daily_loss_pct=2.0)
    assert mgr.check_daily_loss(-5000) is False  # 1.25% < 2%


def test_daily_loss_breached():
    mgr = SafetyManager(capital=400000, max_daily_loss_pct=2.0)
    assert mgr.check_daily_loss(-9000) is True  # 2.25% > 2%


def test_daily_loss_exactly_at_limit():
    mgr = SafetyManager(capital=400000, max_daily_loss_pct=2.0)
    # 2% of 400000 = 8000; exactly at limit counts as breached
    assert mgr.check_daily_loss(-8000) is True


def test_daily_loss_positive_pnl():
    mgr = SafetyManager(capital=400000, max_daily_loss_pct=2.0)
    assert mgr.check_daily_loss(5000) is False


def test_max_positions_check():
    mgr = SafetyManager(capital=400000, max_daily_loss_pct=2.0, max_positions=4)
    assert mgr.can_open_position(current_positions=3) is True
    assert mgr.can_open_position(current_positions=4) is False


def test_emergency_stop():
    mgr = SafetyManager(capital=400000, max_daily_loss_pct=2.0)
    mock_executor = MagicMock()
    # Should not raise
    mgr.emergency_stop(mock_executor)
