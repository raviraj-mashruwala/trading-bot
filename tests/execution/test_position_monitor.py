"""Tests for PositionMonitor — snapshot and unrealised P&L."""
from unittest.mock import MagicMock
from tradingbot.executor.position_monitor import PositionMonitor
from tradingbot.core.models import Position


def _mock_broker(positions=None, ltp_map=None):
    broker = MagicMock()
    broker.get_positions.return_value = positions or []
    if ltp_map:
        broker.get_ltp.side_effect = lambda sym: ltp_map[sym]
    return broker


def test_snapshot_keys_by_symbol():
    pos = MagicMock(spec=Position)
    pos.symbol = "RELIANCE"
    broker = _mock_broker(positions=[pos])
    monitor = PositionMonitor(broker)
    snap = monitor.snapshot()
    assert "RELIANCE" in snap
    assert snap["RELIANCE"] is pos


def test_snapshot_empty_when_no_positions():
    broker = _mock_broker()
    monitor = PositionMonitor(broker)
    assert monitor.snapshot() == {}


def test_unrealised_pnl_sums_positions():
    pos_a = MagicMock(spec=Position)
    pos_a.symbol = "RELIANCE"
    pos_a.unrealised_pnl.return_value = 500.0

    pos_b = MagicMock(spec=Position)
    pos_b.symbol = "INFY"
    pos_b.unrealised_pnl.return_value = -200.0

    broker = _mock_broker(ltp_map={"RELIANCE": 2600.0, "INFY": 1500.0})
    monitor = PositionMonitor(broker)

    positions = {"RELIANCE": pos_a, "INFY": pos_b}
    total = monitor.unrealised_pnl(positions)

    assert total == 300.0
    pos_a.unrealised_pnl.assert_called_once_with(2600.0)
    pos_b.unrealised_pnl.assert_called_once_with(1500.0)
