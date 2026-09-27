from unittest.mock import MagicMock
from tradingbot.execution.kite_auth import KiteAuth


def test_is_authenticated_false_initially():
    auth = KiteAuth(api_key="test", api_secret="secret")
    assert auth.is_authenticated() is False


def test_set_access_token():
    auth = KiteAuth(api_key="test", api_secret="secret")
    mock_kite = MagicMock()
    mock_kite.profile.return_value = {"user_name": "Test User"}
    auth.set_access_token("token123", mock_kite)
    assert auth.is_authenticated() is True


def test_kite_property_raises_before_auth():
    auth = KiteAuth(api_key="test", api_secret="secret")
    try:
        _ = auth.kite
        assert False, "Should have raised RuntimeError"
    except RuntimeError:
        pass


def test_kite_property_returns_client_after_auth():
    auth = KiteAuth(api_key="test", api_secret="secret")
    mock_kite = MagicMock()
    mock_kite.profile.return_value = {"user_name": "Test User"}
    auth.set_access_token("token123", mock_kite)
    assert auth.kite is mock_kite
