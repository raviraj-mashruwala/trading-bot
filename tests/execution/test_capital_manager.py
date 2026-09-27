from unittest.mock import MagicMock
from tradingbot.execution.capital_manager import CapitalManager


def test_available_capital():
    client = MagicMock()
    client.get_margins.return_value = {
        "equity": {"available": {"live_balance": 400000, "intraday_payin": 0}},
    }
    mgr = CapitalManager(client, deployed=50000)
    available = mgr.available_capital()
    assert available == 350000


def test_check_margin_sufficient():
    client = MagicMock()
    client.get_margins.return_value = {
        "equity": {"available": {"live_balance": 400000, "intraday_payin": 0}},
    }
    mgr = CapitalManager(client, deployed=0)
    ok, reason = mgr.check_margin(entry_price=2500, quantity=10)
    # 2500 * 10 / 5 (margin) = 5000 needed, 400000 available
    assert ok is True


def test_check_margin_insufficient():
    client = MagicMock()
    client.get_margins.return_value = {
        "equity": {"available": {"live_balance": 1000, "intraday_payin": 0}},
    }
    mgr = CapitalManager(client, deployed=0)
    ok, reason = mgr.check_margin(entry_price=2500, quantity=100)
    assert ok is False


def test_add_and_release_deployed():
    client = MagicMock()
    client.get_margins.return_value = {
        "equity": {"available": {"live_balance": 200000, "intraday_payin": 0}},
    }
    mgr = CapitalManager(client, deployed=0)
    mgr.add_deployed(50000)
    assert mgr.available_capital() == 150000
    mgr.release_deployed(30000)
    assert mgr.available_capital() == 180000


def test_release_deployed_floors_at_zero():
    client = MagicMock()
    client.get_margins.return_value = {
        "equity": {"available": {"live_balance": 100000, "intraday_payin": 0}},
    }
    mgr = CapitalManager(client, deployed=10000)
    mgr.release_deployed(50000)  # more than deployed
    assert mgr.available_capital() == 100000  # deployed floored at 0
