"""Tests for LiveTickManager — Kite WebSocket tick dispatch."""
import pytest
from unittest.mock import MagicMock, patch, call
from tradingbot.data.kite_ticker import LiveTickManager


def test_subscribe_registers_tokens():
    with patch("tradingbot.data.kite_ticker.KiteTicker") as MockTicker:
        mock_ws = MagicMock()
        MockTicker.return_value = mock_ws

        manager = LiveTickManager(api_key="test", access_token="token")
        callback = MagicMock()
        manager.subscribe([738561, 341249], callback)

        assert 738561 in manager.subscribed_tokens
        assert 341249 in manager.subscribed_tokens


def test_unsubscribe_removes_tokens():
    with patch("tradingbot.data.kite_ticker.KiteTicker"):
        manager = LiveTickManager(api_key="test", access_token="token")
        manager.subscribe([738561], MagicMock())
        manager.unsubscribe([738561])
        assert 738561 not in manager.subscribed_tokens


def test_on_ticks_calls_callback():
    with patch("tradingbot.data.kite_ticker.KiteTicker"):
        manager = LiveTickManager(api_key="test", access_token="token")
        callback = MagicMock()
        manager.subscribe([738561], callback)
        manager._on_ticks(None, [{"instrument_token": 738561, "last_price": 2510.0}])
        callback.assert_called_once_with(738561, 2510.0)


def test_on_ticks_ignores_unsubscribed_token():
    with patch("tradingbot.data.kite_ticker.KiteTicker"):
        manager = LiveTickManager(api_key="test", access_token="token")
        callback = MagicMock()
        manager.subscribe([738561], callback)
        # Tick for a different token — callback should NOT fire
        manager._on_ticks(None, [{"instrument_token": 999999, "last_price": 100.0}])
        callback.assert_not_called()


def test_on_ticks_multiple_tokens():
    with patch("tradingbot.data.kite_ticker.KiteTicker"):
        manager = LiveTickManager(api_key="test", access_token="token")
        cb_a = MagicMock()
        cb_b = MagicMock()
        manager.subscribe([111], cb_a)
        manager.subscribe([222], cb_b)

        manager._on_ticks(None, [
            {"instrument_token": 111, "last_price": 10.0},
            {"instrument_token": 222, "last_price": 20.0},
        ])
        cb_a.assert_called_once_with(111, 10.0)
        cb_b.assert_called_once_with(222, 20.0)


def test_start_creates_ticker_and_thread():
    with patch("tradingbot.data.kite_ticker.KiteTicker") as MockTicker:
        mock_ws = MagicMock()
        MockTicker.return_value = mock_ws

        with patch("tradingbot.data.kite_ticker.threading") as mock_threading:
            mock_thread = MagicMock()
            mock_threading.Thread.return_value = mock_thread

            manager = LiveTickManager(api_key="key", access_token="tok")
            manager.start()

            MockTicker.assert_called_once_with("key", "tok")
            mock_threading.Thread.assert_called_once()
            mock_thread.start.assert_called_once()


def test_stop_closes_ticker():
    with patch("tradingbot.data.kite_ticker.KiteTicker") as MockTicker:
        mock_ws = MagicMock()
        MockTicker.return_value = mock_ws

        with patch("tradingbot.data.kite_ticker.threading"):
            manager = LiveTickManager(api_key="key", access_token="tok")
            manager.start()
            manager.stop()
            mock_ws.close.assert_called_once()


def test_on_connect_subscribes_tokens():
    with patch("tradingbot.data.kite_ticker.KiteTicker"):
        manager = LiveTickManager(api_key="key", access_token="tok")
        manager.subscribe([738561], MagicMock())

        mock_ws = MagicMock()
        manager._on_connect(mock_ws, {})
        mock_ws.subscribe.assert_called_once_with([738561])


def test_callback_error_does_not_crash():
    """Callback exception logged, not propagated."""
    with patch("tradingbot.data.kite_ticker.KiteTicker"):
        manager = LiveTickManager(api_key="test", access_token="token")
        bad_callback = MagicMock(side_effect=ValueError("boom"))
        manager.subscribe([738561], bad_callback)
        # Should not raise
        manager._on_ticks(None, [{"instrument_token": 738561, "last_price": 100.0}])
