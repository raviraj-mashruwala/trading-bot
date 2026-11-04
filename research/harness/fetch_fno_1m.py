"""Download 1-minute history for the F&O universe from Kite into candles.duckdb (resumable).

Why spot, not futures: Kite has no minute data for expired futures contracts. Intraday futures returns
track the underlying, so the backtest uses spot bars and charges futures-level costs (costs.py).

Order: indices first (small, fastest), then F&O stocks. Safe to Ctrl-C and rerun: each chunk is written
as it arrives and a rerun only fetches missing ranges (before the first stored bar, after the last).
Close the web app / any other process holding candles.duckdb before running.

    tradingbot auth                                   # Kite token expires every morning
    python -m research.harness.fetch_fno_1m --list    # show the plan, no data calls
    python -m research.harness.fetch_fno_1m --only-indices
    python -m research.harness.fetch_fno_1m           # everything (about an hour)
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import date, timedelta
from pathlib import Path

from tradingbot.data.kite_data_sync import _date_chunks, _kite_rows_to_df

log = logging.getLogger('fetch_fno_1m')
INDEX_NAMES = ('NIFTY 50', 'NIFTY BANK', 'NIFTY FIN SERVICE', 'NIFTY MID SELECT', 'INDIA VIX')
CHUNK_DAYS = 60  # Kite minute-candle window per request


def missing_ranges(first: date | None, last: date | None, start: date, today: date) -> list[tuple[date, date]]:
    """Ranges still to fetch given what is stored. Skips sub-week slivers at the old edge."""
    if first is None or last is None:
        return [(start, today)]
    out = []
    if first - start > timedelta(days=7):
        out.append((start, first - timedelta(days=1)))
    if last < today - timedelta(days=1):
        out.append((last + timedelta(days=1), today))
    return out


def fast_write(store, symbol: str, df) -> int:
    """Bulk INSERT OR IGNORE. CandleStore.write counts rows with two full-table scans per call,
    which is minutes per chunk on a 78M-row table."""
    if df.empty:
        return 0
    if getattr(df['timestamp'].dt, 'tz', None) is not None:
        df = df.assign(timestamp=df['timestamp'].dt.tz_localize(None))  # keep IST wall clock
    df = df.assign(symbol=symbol, interval='1m')[
        ['symbol', 'interval', 'timestamp', 'open', 'high', 'low', 'close', 'volume']]
    con = store._ensure_connected()
    con.register('incoming', df)
    try:
        con.execute('INSERT OR IGNORE INTO candles SELECT * FROM incoming')
    finally:
        con.unregister('incoming')
    return len(df)


def resolve_universe(kite, only_indices: bool) -> list[tuple[str, int, str]]:
    """(symbol, token, kind) for indices and F&O underlyings."""
    nse = kite.instruments('NSE')
    out = [(i['tradingsymbol'], i['instrument_token'], 'index')
           for i in nse if i['segment'] == 'INDICES' and i['tradingsymbol'] in INDEX_NAMES]
    if not only_indices:
        names = {i['name'] for i in kite.instruments('NFO') if i['segment'] == 'NFO-FUT'}
        out += sorted((i['tradingsymbol'], i['instrument_token'], 'stock')
                      for i in nse if i['segment'] == 'NSE' and i['instrument_type'] == 'EQ'
                      and i['tradingsymbol'] in names)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--list', action='store_true', help='print the plan and exit')
    ap.add_argument('--only-indices', action='store_true')
    ap.add_argument('--index-start', default='2015-01-01')
    ap.add_argument('--stock-start', default='2019-01-01')
    ap.add_argument('--database', default='candles.duckdb')
    ap.add_argument('--limit', type=int, default=0, help='stop after N symbols (testing)')
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

    from kiteconnect import KiteConnect
    from tradingbot.core.config import load_config
    from tradingbot.data.candle_store import CandleStore
    from tradingbot.data.kite_client import KiteClient

    config = load_config(Path('config.toml'), anthropic_key_optional=True)
    token_path = Path.home() / '.tradingbot' / 'kite_token'
    if not token_path.exists():
        raise SystemExit('no Kite token: run `tradingbot auth` first')
    kite = KiteConnect(api_key=config.secrets.kite_api_key)
    kite.set_access_token(token_path.read_text().strip())
    client = KiteClient(kite, rate_limit_per_sec=3)
    try:
        universe = resolve_universe(kite, a.only_indices)
    except Exception as exc:  # token expired or network
        raise SystemExit(f'Kite rejected the request ({exc}). Token expires each morning: run `tradingbot auth`.')

    store = CandleStore(Path(a.database))
    today = date.today()
    plan = []
    for sym, tok, kind in universe:
        start = date.fromisoformat(a.index_start if kind == 'index' else a.stock_start)
        first, last = store.date_range(sym, '1m')
        for lo, hi in missing_ranges(first, last, start, today):
            plan.append((sym, tok, lo, hi))
    requests = sum(len(_date_chunks(lo, hi, CHUNK_DAYS)) for _, _, lo, hi in plan)
    log.info('%d symbols, %d ranges, %d requests, about %.0f min at 3 req/s',
             len(universe), len(plan), requests, requests / 3 / 60)
    if a.list:
        for sym, tok, lo, hi in plan[:60]:
            print(sym, tok, lo, hi)
        return

    done_symbols, t0 = set(), time.time()
    for sym, tok, lo, hi in plan:
        if a.limit and len(done_symbols) >= a.limit and sym not in done_symbols:
            break
        written = 0
        for c_lo, c_hi in _date_chunks(lo, hi, CHUNK_DAYS):
            for attempt in range(3):
                try:
                    rows = client.fetch_historical(tok, 'minute', c_lo, c_hi)
                    written += fast_write(store, sym, _kite_rows_to_df(rows))
                    break
                except Exception as exc:  # noqa: BLE001
                    if 'token' in str(exc).lower() or 'api_key' in str(exc).lower():
                        raise SystemExit(f'auth failed ({exc}): run `tradingbot auth` and rerun (progress is kept)')
                    time.sleep(2 ** attempt)
            else:
                log.warning('%s %s..%s failed after retries; rerun to fill it', sym, c_lo, c_hi)
        done_symbols.add(sym)
        store._ensure_connected().execute('CHECKPOINT')
        log.info('%s %s..%s +%d rows (%d/%d symbols, %.0f min elapsed)', sym, lo, hi, written,
                 len(done_symbols), len({p[0] for p in plan}), (time.time() - t0) / 60)


if __name__ == '__main__':
    main()
