"""Fetch NSE equity delivery percentage from the daily bhav copy archive.

NSE publishes `sec_bhavdata_full_{DDMMMYYYY}.csv` containing DELIV_PER
(delivery as % of traded quantity) for each equity. High delivery % indicates
institutional conviction; low % indicates speculative activity.

Falls back to {} on any network or parse error — caller uses 50.0 neutral.
"""

from __future__ import annotations

import io
import logging
from datetime import date, timedelta

import httpx
import pandas as pd

log = logging.getLogger(__name__)

_BHAV_URL = (
    "https://archives.nseindia.com/products/content/sec_bhavdata_full_{date}.csv"
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/csv,text/plain,*/*",
    "Referer": "https://www.nseindia.com/",
}
_TIMEOUT = 15.0
_MAX_LOOKBACK_DAYS = 7  # calendar days back, enough for a weekend plus holidays


def _date_str(d: date) -> str:
    """NSE names the file sec_bhavdata_full_DDMMYYYY.csv (numeric month)."""
    return f"{d.day:02d}{d.month:02d}{d.year}"


def fetch_delivery_pct(
    trade_date: date | None = None,
    http_client: httpx.Client | None = None,
    today: date | None = None,
) -> dict[str, float]:
    """Return {symbol: delivery_pct} for NSE equities from bhav copy.

    Starts at trade_date, or today when trade_date is in the future (an analysis
    for Monday has no Monday file yet, so the newest possible file is today's),
    and walks back up to _MAX_LOOKBACK_DAYS calendar days, skipping weekends.
    Returns {} on failure: the caller uses 50.0 neutral.
    """
    client = http_client or httpx.Client(headers=_HEADERS, timeout=_TIMEOUT)
    today = today or date.today()
    target = min(trade_date or today, today)

    for days_back in range(_MAX_LOOKBACK_DAYS):
        candidate = target - timedelta(days=days_back)
        if candidate.weekday() >= 5:  # skip weekends
            continue
        result = _try_fetch(client, candidate)
        if result is not None:
            log.info("Delivery data loaded from bhav copy %s (%d symbols)", candidate, len(result))
            return result

    log.warning("Delivery bhav copy unavailable for %s (tried %d days back)", target, _MAX_LOOKBACK_DAYS)
    return {}


def _try_fetch(client: httpx.Client, d: date) -> dict[str, float] | None:
    url = _BHAV_URL.format(date=_date_str(d))
    try:
        resp = client.get(url)
        if resp.status_code != 200:
            return None
        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = [c.strip() for c in df.columns]

        # Locate symbol and delivery % columns
        sym_col = next((c for c in df.columns if "SYMBOL" in c.upper()), None)
        del_col = next((c for c in df.columns if "DELPCT" in c.upper() or "DELIV_PER" in c.upper()), None)
        series_col = next((c for c in df.columns if "SERIES" in c.upper()), None)

        if sym_col is None or del_col is None:
            log.warning("Unexpected bhav CSV columns: %s", list(df.columns))
            return None

        # Keep only EQ series (exclude BE, BZ, SM etc.)
        if series_col:
            df = df[df[series_col].str.strip() == "EQ"]

        df[del_col] = pd.to_numeric(df[del_col], errors="coerce").fillna(0.0)
        return {
            str(row[sym_col]).strip(): float(row[del_col])
            for _, row in df.iterrows()
            if str(row[sym_col]).strip()
        }
    except Exception as exc:
        log.debug("Bhav fetch failed for %s: %s", d, exc)
        return None
