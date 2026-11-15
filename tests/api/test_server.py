import signal

import pytest

from tradingbot.api.server import ForceExitServer


def make_server():
    import uvicorn

    return ForceExitServer(uvicorn.Config("tradingbot.api.app:create_app", factory=True))


def test_first_signal_requests_a_graceful_shutdown(monkeypatch):
    exits = []
    monkeypatch.setattr("tradingbot.api.server.os._exit", exits.append)
    server = make_server()

    server.handle_exit(signal.SIGTERM, None)

    assert server.should_exit is True
    assert exits == []


def test_second_sigterm_force_exits_a_wedged_process(monkeypatch):
    exits = []
    monkeypatch.setattr("tradingbot.api.server.os._exit", exits.append)
    server = make_server()

    server.handle_exit(signal.SIGTERM, None)
    server.handle_exit(signal.SIGTERM, None)

    assert exits == [1]
