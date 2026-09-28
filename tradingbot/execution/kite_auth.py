"""Kite OAuth token management."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

TOKEN_DIR = Path.home() / ".tradingbot"


class KiteAuth:
    """Manage Kite Connect authentication lifecycle."""

    def __init__(self, api_key: str, api_secret: str):
        self._api_key = api_key
        self._api_secret = api_secret
        self._access_token: str | None = None
        self._kite: Any | None = None

    def is_authenticated(self) -> bool:
        return self._access_token is not None

    def set_access_token(self, token: str, kite: Any) -> None:
        """Validate and store an access token.

        *kite* should be a ``KiteConnect`` (or mock) instance.
        ``kite.profile()`` is called to verify the token is valid.
        """
        kite.set_access_token(token)
        kite.profile()  # validate token — raises on invalid
        self._access_token = token
        self._kite = kite
        log.info("Kite authenticated successfully")

    def get_login_url(self) -> str:
        from kiteconnect import KiteConnect

        kite = KiteConnect(api_key=self._api_key)
        return kite.login_url()

    def generate_session(self, request_token: str) -> dict:
        """Exchange request_token for access_token via Kite API."""
        from kiteconnect import KiteConnect

        kite = KiteConnect(api_key=self._api_key)
        data = kite.generate_session(request_token, api_secret=self._api_secret)
        access_token = data["access_token"]
        kite.set_access_token(access_token)
        self._access_token = access_token
        self._kite = kite
        self._save_token(access_token)
        log.info("Kite session generated for user %s", data.get("user_id", "?"))
        return data

    def _save_token(self, token: str) -> None:
        TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        token_file = TOKEN_DIR / "kite_token"
        token_file.write_text(token)
        token_file.chmod(0o600)
        log.info("Token saved to %s", token_file)

    @staticmethod
    def load_saved_token() -> str | None:
        token_file = TOKEN_DIR / "kite_token"
        if not token_file.exists():
            return None
        token = token_file.read_text().strip()
        return token if token else None

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def api_secret(self) -> str:
        return self._api_secret

    @property
    def access_token(self) -> str | None:
        return self._access_token

    @property
    def kite(self) -> Any:
        if self._kite is None:
            raise RuntimeError("Not authenticated — call set_access_token first")
        return self._kite
