"""
Fetch missing 1m intraday data for the Tier1 replay candidates
(scripts/replay_tier1_history.py output). Groups by symbol, fetches the
min-to-max date range needed per symbol in <=30-day Kite API chunks
(fetches a few extra days along the way — harmless, just more cache).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb

env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

KITE_API_KEY = os.environ.get("KITE_API_KEY", "")
DB_PATH = Path(__file__).parent.parent / "candles.duckdb"
TOKEN_PATH = Path.home() / ".tradingbot" / "kite_token"
CANDIDATES_PATH = Path(__file__).parent / "output" / "tier1_replay_candidates.json"


def _date_chunks(start: date, end: date, max_days: int) -> list[tuple[date, date]]:
    chunks = []
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=max_days - 1), end)
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks


async def main():
    with open(CANDIDATES_PATH) as f:
        candidates = json.load(f)

    con = duckdb.connect(str(DB_PATH), read_only=True)
    needed: dict[str, set[str]] = {}
    for c in candidates:
        cnt = con.execute(
            "SELECT COUNT(*) FROM candles WHERE symbol=? AND interval='1m' AND timestamp::DATE=?",
            [c["symbol"], c["date"]],
        ).fetchone()[0]
        if cnt == 0:
            needed.setdefault(c["symbol"], set()).add(c["date"])
    con.close()

    print(f"{len(needed)} symbols need 1m data fetched ({sum(len(v) for v in needed.values())} symbol-day gaps)")

    if not needed:
        print("Nothing to fetch.")
        return

    from kiteconnect import KiteConnect
    from tradingbot.data.kite_client import KiteClient
    from tradingbot.data.candle_store import CandleStore
    from tradingbot.data.instrument_cache import InstrumentCache
    from tradingbot.data.kite_data_sync import _kite_rows_to_df

    kite = KiteConnect(api_key=KITE_API_KEY)
    kite.set_access_token(TOKEN_PATH.read_text().strip())
    kite_client = KiteClient(kite)
    store = CandleStore(DB_PATH)
    instruments_db = Path(__file__).parent.parent / "instruments.db"
    instruments_cache = InstrumentCache(instruments_db)

    total_fetched = 0
    total_rows = 0
    skipped_symbols = []

    for i, (symbol, dates) in enumerate(sorted(needed.items())):
        date_objs = sorted(date.fromisoformat(d.split(" ")[0]) for d in dates)
        from_date = date_objs[0]
        to_date = date_objs[-1] + timedelta(days=1)

        try:
            token = instruments_cache.get_token(symbol)
        except KeyError:
            skipped_symbols.append(symbol)
            continue

        chunks = _date_chunks(from_date, to_date, 30)  # Kite minute limit
        sym_rows = 0
        for cf, ct in chunks:
            try:
                raw = await asyncio.to_thread(
                    kite_client.fetch_historical, token, "minute", cf, ct
                )
                df = _kite_rows_to_df(raw)
                written = await asyncio.to_thread(store.write, symbol, "1m", df)
                sym_rows += written
            except Exception as e:
                print(f"  FAILED {symbol} {cf}->{ct}: {e}")
            await asyncio.sleep(0.34)  # ~3 req/sec

        total_fetched += 1
        total_rows += sym_rows
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(needed)} symbols fetched, {total_rows:,} rows so far")

    print(f"\nDone. {total_fetched} symbols fetched, {total_rows:,} rows written.")
    if skipped_symbols:
        print(f"Skipped (no instrument token found — likely delisted/renamed): {skipped_symbols}")


if __name__ == "__main__":
    asyncio.run(main())
