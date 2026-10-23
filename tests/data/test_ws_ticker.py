import asyncio
import threading

from tradingbot.data.ws_ticker import AsyncKiteTicker


def _loop_thread(ticker: AsyncKiteTicker) -> threading.Thread:
    """Run a bare event loop on ticker._loop without opening a websocket."""
    ticker._loop = asyncio.new_event_loop()
    t = threading.Thread(target=ticker._loop.run_forever, daemon=True)
    t.start()
    return t


def _stop_loop(ticker: AsyncKiteTicker) -> None:
    ticker._loop.call_soon_threadsafe(ticker._loop.stop)


def test_loop_not_responsive_before_start():
    assert AsyncKiteTicker("k", "t").is_loop_responsive(timeout=0.2) is False


def test_loop_responsive_when_running():
    ticker = AsyncKiteTicker("k", "t")
    _loop_thread(ticker)
    try:
        assert ticker.is_loop_responsive(timeout=1.0) is True
    finally:
        _stop_loop(ticker)


def test_loop_not_responsive_when_blocked():
    ticker = AsyncKiteTicker("k", "t")
    _loop_thread(ticker)
    release = threading.Event()
    ticker._loop.call_soon_threadsafe(release.wait)  # wedges the loop thread
    try:
        assert ticker.is_loop_responsive(timeout=0.2) is False
    finally:
        release.set()
        _stop_loop(ticker)


def test_restart_replaces_wedged_thread_and_keeps_subscriptions(monkeypatch):
    async def idle_connect_loop(self, gen=None):
        while self._running and (gen is None or gen == self._generation):
            await asyncio.sleep(0.01)

    monkeypatch.setattr(AsyncKiteTicker, "_connect_loop", idle_connect_loop)
    ticker = AsyncKiteTicker("k", "t")
    ticker.subscribe([101, 202], lambda token, ltp: None)
    ticker.start()
    release = threading.Event()
    try:
        assert ticker.is_loop_responsive(timeout=1.0) is True
        ticker._loop.call_soon_threadsafe(release.wait)
        assert ticker.is_loop_responsive(timeout=0.2) is False
        wedged_thread = ticker._thread

        ticker.restart()

        assert ticker._thread is not wedged_thread
        assert ticker.is_loop_responsive(timeout=1.0) is True
        assert ticker.subscribed_tokens == {101, 202}
    finally:
        release.set()
        ticker.stop()


def test_superseded_connect_loop_exits_without_connecting():
    ticker = AsyncKiteTicker("k", "t")
    ticker._running = True
    ticker._generation = 2
    # generation 1 was replaced by restart(); it must return instead of opening a websocket
    asyncio.run(asyncio.wait_for(ticker._connect_loop(1), timeout=2.0))
