from unittest.mock import MagicMock, patch
from tradingbot.execution.kite_auth import KiteAuth, TOKEN_DIR


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


def test_generate_session_saves_token_file(tmp_path, monkeypatch):
    import tradingbot.execution.kite_auth as mod
    monkeypatch.setattr(mod, "TOKEN_DIR", tmp_path)

    auth = KiteAuth(api_key="test", api_secret="secret")
    mock_kite_class = MagicMock()
    mock_kite_instance = MagicMock()
    mock_kite_class.return_value = mock_kite_instance
    mock_kite_instance.generate_session.return_value = {
        "access_token": "saved_token_123",
        "user_id": "AB1234",
    }

    with patch("kiteconnect.KiteConnect", mock_kite_class):
        auth.generate_session("req_token")

    token_file = tmp_path / "kite_token"
    assert token_file.exists()
    assert token_file.read_text().strip() == "saved_token_123"
    assert oct(token_file.stat().st_mode)[-3:] == "600"


def test_load_saved_token(tmp_path, monkeypatch):
    import tradingbot.execution.kite_auth as mod
    monkeypatch.setattr(mod, "TOKEN_DIR", tmp_path)

    token_file = tmp_path / "kite_token"
    token_file.write_text("existing_token_456")
    token_file.chmod(0o600)

    assert KiteAuth.load_saved_token() == "existing_token_456"


def test_load_saved_token_returns_none_when_missing(tmp_path, monkeypatch):
    import tradingbot.execution.kite_auth as mod
    monkeypatch.setattr(mod, "TOKEN_DIR", tmp_path)

    assert KiteAuth.load_saved_token() is None
