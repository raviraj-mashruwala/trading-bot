"""Load 1-minute sessions from candles.duckdb as per-day numpy arrays.

Bars are start-labelled (the 09:15 bar covers 09:15:00-09:15:59). A session is
kept only if it is clean: positive prices, high >= low, strictly increasing
minutes, and it contains the opening bar. Days that fail are counted, not fixed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb
import numpy as np

OPEN_MIN = 9 * 60 + 15


@dataclass(frozen=True)
class Session:
    day: date
    minute: np.ndarray  # minutes since midnight
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    def idx(self, minute_of_day: int) -> int:
        """Index of the bar starting exactly at minute_of_day, or -1."""
        pos = int(np.searchsorted(self.minute, minute_of_day))
        if pos < len(self.minute) and self.minute[pos] == minute_of_day:
            return pos
        return -1


def hhmm(h: int, m: int) -> int:
    return h * 60 + m


def load_sessions(con: duckdb.DuckDBPyConnection, symbol: str, interval: str = '1m',
                  start: str = '2000-01-01', end: str = '2100-01-01'
                  ) -> tuple[list[Session], dict[str, int]]:
    """Return (clean sessions, counts of dropped days by reason)."""
    cur = con.execute(
        'SELECT timestamp, open, high, low, close, volume FROM candles '
        'WHERE symbol=? AND interval=? AND timestamp>=? AND timestamp<? ORDER BY timestamp',
        [symbol, interval, start, end])
    data = cur.fetchnumpy()
    ts = data['timestamp'].astype('datetime64[m]')
    if len(ts) == 0:
        return [], {}
    days = ts.astype('datetime64[D]')
    minutes = (ts - days).astype(np.int64)
    bounds = np.flatnonzero(np.diff(days.astype(np.int64))) + 1
    starts = np.concatenate(([0], bounds))
    ends = np.concatenate((bounds, [len(ts)]))
    sessions: list[Session] = []
    dropped = {'bad_prices': 0, 'no_open_bar': 0, 'not_monotonic': 0}
    for a, b in zip(starts, ends):
        o, h, l, c = (np.asarray(data[k][a:b], dtype=float) for k in ('open', 'high', 'low', 'close'))
        mn = minutes[a:b]
        if (np.diff(mn) <= 0).any():
            dropped['not_monotonic'] += 1
        elif mn[0] != OPEN_MIN:
            dropped['no_open_bar'] += 1
        elif (o <= 0).any() or (c <= 0).any() or (l <= 0).any() or (h < l).any() or np.isnan(c).any():
            dropped['bad_prices'] += 1
        else:
            sessions.append(Session(days[a].astype(object), mn, o, h, l, c,
                                    np.asarray(data['volume'][a:b], dtype=float)))
    return sessions, dropped
