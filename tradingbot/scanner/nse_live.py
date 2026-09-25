"""Real-time LTP from NSE's public website.

Scrapes the same data the NSE website shows — updates every few seconds
during market hours. Not tick-level, but under 5 seconds stale.

Session management: NSE requires cookies from the homepage before the API
endpoint responds. We visit nseindia.com once to get cookies, then reuse
the session. Sessions expire after ~5 minutes, so we refresh on 403/cookie
errors.
"""

from __future__ import annotations

import logging
import time
import threading

import requests

logger = logging.getLogger(__name__)

NSE_BASE = "https://www.nseindia.com"
QUOTE_URL = f"{NSE_BASE}/api/quote-equity"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": f"{NSE_BASE}/",
}

SESSION_MAX_AGE = 240


class NseFetchError(Exception):
    """Raised when NSE data could not be retrieved."""


class NseLiveFetcher:
    """Fetch real-time LTP from NSE's public API with automatic session renewal."""

    def __init__(self) -> None:
        self._session: requests.Session | None = None
        self._session_created: float = 0
        self._lock = threading.Lock()

    def _ensure_session(self) -> requests.Session:
        now = time.monotonic()
        if self._session is not None and (now - self._session_created) < SESSION_MAX_AGE:
            return self._session

        session = requests.Session()
        session.headers.update(HEADERS)
        resp = session.get(NSE_BASE, timeout=10)
        resp.raise_for_status()
        self._session = session
        self._session_created = now
        logger.debug("NSE session refreshed, cookies: %d", len(session.cookies))
        return session

    def get_ltp(self, symbol: str) -> float:
        """Return the last traded price for an NSE equity symbol.

        Retries once on session expiry (403 or missing data).
        """
        with self._lock:
            for attempt in range(2):
                session = self._ensure_session()
                try:
                    resp = session.get(
                        QUOTE_URL,
                        params={"symbol": symbol},
                        timeout=10,
                    )
                    if resp.status_code == 403:
                        logger.info("NSE 403 on attempt %d, refreshing session", attempt + 1)
                        self._session = None
                        continue

                    resp.raise_for_status()
                    data = resp.json()

                    price_info = data.get("priceInfo", {})
                    ltp = price_info.get("lastPrice")
                    if ltp is None:
                        raise NseFetchError(f"no lastPrice in response for {symbol}")

                    return float(ltp)

                except requests.RequestException as exc:
                    if attempt == 0:
                        logger.info("NSE request failed on attempt 1: %s, retrying", exc)
                        self._session = None
                        continue
                    raise NseFetchError(f"NSE fetch failed for {symbol}: {exc}") from exc

            raise NseFetchError(f"NSE fetch failed for {symbol} after 2 attempts")
