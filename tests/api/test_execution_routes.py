import asyncio

import pytest


async def test_execute_status_is_idle_initially(api_client):
    response = await api_client.get("/api/execute/status")
    assert response.status_code == 200
    assert response.json()["status"] == "idle"


async def test_execute_returns_400_when_no_plan(api_client):
    response = await api_client.post("/api/execute", json={"mode": "paper"})
    assert response.status_code == 400
    assert "no plan" in response.json()["detail"].lower()


async def test_execute_returns_409_when_already_running(api_client):
    state = api_client._app.state.app_state
    state.executor_status = "running"
    state.executor_task = asyncio.ensure_future(asyncio.sleep(999))

    response = await api_client.post("/api/execute", json={"mode": "paper"})
    assert response.status_code == 409

    state.executor_task.cancel()
    try:
        await state.executor_task
    except asyncio.CancelledError:
        pass
    state.executor_status = "idle"


async def test_execute_status_unrealised_pnl_with_positions(api_client):
    from datetime import time
    from unittest.mock import MagicMock

    from tradingbot.core.models import Direction, EntryType, StrategyName, TradeLeg
    from tradingbot.executor.executor import LegState

    state = api_client._app.state.app_state
    state.executor_status = "running"
    state.executor_mode = "paper"

    leg = TradeLeg(
        symbol="RELIANCE", exchange="NSE", strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG, entry_price=2450.0, entry_type=EntryType.LIMIT,
        stop_loss=2420.0, target_1=2500.0, target_2=2550.0, quantity=10,
        risk_amount=300.0, entry_window_start=time(9, 15),
        entry_window_end=time(9, 45), max_entry_wait=time(10, 0),
        exit_before=time(15, 10), confidence=0.8, reasoning="test",
    )
    ls = LegState(leg=leg)
    ls.filled_quantity = 10
    ls.entry_fill_price = 2450.0

    mock_executor = MagicMock()
    mock_executor.states = [ls]
    mock_executor.broker.get_ltp.return_value = 2480.0
    state.executor_ref = mock_executor

    response = await api_client.get("/api/execute/status")
    data = response.json()
    pos = data["positions"][0]
    assert pos["last_price"] == 2480.0
    assert pos["unrealised_pnl"] == 300.0

    state.executor_ref = None
    state.executor_status = "idle"
    state.executor_mode = None


async def test_execute_status_unrealised_pnl_fallback_on_error(api_client):
    from datetime import time
    from unittest.mock import MagicMock

    from tradingbot.core.models import Direction, EntryType, StrategyName, TradeLeg
    from tradingbot.executor.executor import LegState

    state = api_client._app.state.app_state
    state.executor_status = "running"
    state.executor_mode = "paper"

    leg = TradeLeg(
        symbol="RELIANCE", exchange="NSE", strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG, entry_price=2450.0, entry_type=EntryType.LIMIT,
        stop_loss=2420.0, target_1=2500.0, target_2=2550.0, quantity=10,
        risk_amount=300.0, entry_window_start=time(9, 15),
        entry_window_end=time(9, 45), max_entry_wait=time(10, 0),
        exit_before=time(15, 10), confidence=0.8, reasoning="test",
    )
    ls = LegState(leg=leg)
    ls.filled_quantity = 10
    ls.entry_fill_price = 2450.0

    mock_executor = MagicMock()
    mock_executor.states = [ls]
    mock_executor.broker.get_ltp.side_effect = RuntimeError("market closed")
    state.executor_ref = mock_executor

    response = await api_client.get("/api/execute/status")
    data = response.json()
    pos = data["positions"][0]
    assert pos["last_price"] == 0.0
    assert pos["unrealised_pnl"] == 0.0

    state.executor_ref = None
    state.executor_status = "idle"
    state.executor_mode = None


async def test_execute_stop_when_idle_returns_ok(api_client):
    response = await api_client.post("/api/execute/stop")
    assert response.status_code == 200
