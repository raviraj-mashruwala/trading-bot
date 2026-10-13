"""Download candle data from MotherDuck to a local DuckDB file.

Usage:
    python scripts/download-from-motherduck.py [output_path]

Requires MOTHERDUCK_TOKEN in .env or environment.
Default output: candles.duckdb in current directory.
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import duckdb

output = sys.argv[1] if len(sys.argv) > 1 else "candles.duckdb"

if Path(output).exists():
    print(f"{output} already exists. Delete it first or choose a different name.")
    sys.exit(1)

print("Connecting to MotherDuck...")
md = duckdb.connect("md:candles")
remote_count = md.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
print(f"MotherDuck: {remote_count:,} rows")

print(f"Creating local {output}...")
local = duckdb.connect(output)
local.execute("""CREATE TABLE IF NOT EXISTS candles (
    symbol      VARCHAR NOT NULL,
    interval    VARCHAR NOT NULL,
    timestamp   TIMESTAMP NOT NULL,
    open        DOUBLE NOT NULL,
    high        DOUBLE NOT NULL,
    low         DOUBLE NOT NULL,
    close       DOUBLE NOT NULL,
    volume      BIGINT NOT NULL
)""")
local.execute(
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_candles_pk "
    "ON candles (symbol, interval, timestamp)"
)

print(f"Downloading {remote_count:,} rows (this may take 10-20 minutes)...")
local.execute("ATTACH 'md:candles' AS remote")
local.execute("INSERT OR IGNORE INTO candles SELECT * FROM remote.candles")

local_count = local.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
print(f"Local DB: {local_count:,} rows")

local.close()
md.close()

print(f"\nDone! {output} created ({Path(output).stat().st_size / 1e9:.1f} GB)")
print("To use local DB: set CANDLE_STORE_URL= (empty) in .env")
