#!/usr/bin/env bash
# Uploads local candles.duckdb to MotherDuck.
# Usage: MOTHERDUCK_TOKEN=<token> ./scripts/migrate-to-motherduck.sh [path/to/candles.duckdb]
set -euo pipefail

DB_PATH="${1:-candles.duckdb}"
if [ ! -f "$DB_PATH" ]; then
  echo "File not found: $DB_PATH"
  echo "Usage: MOTHERDUCK_TOKEN=<token> $0 [path/to/candles.duckdb]"
  exit 1
fi

if [ -z "${MOTHERDUCK_TOKEN:-}" ]; then
  echo "Set MOTHERDUCK_TOKEN env var first."
  echo "Get one at: app.motherduck.com → Settings → Access Tokens"
  exit 1
fi

echo "Uploading $DB_PATH to MotherDuck database 'candles'..."

python3 -c "
import duckdb
import os

db_path = '$DB_PATH'

local = duckdb.connect(db_path, read_only=True)
count = local.execute('SELECT COUNT(*) FROM candles').fetchone()[0]
print(f'Local DB: {count:,} rows')

print('Connecting to MotherDuck...')
md = duckdb.connect('md:candles')
md.execute('''
CREATE TABLE IF NOT EXISTS candles (
    symbol      VARCHAR NOT NULL,
    interval    VARCHAR NOT NULL,
    timestamp   TIMESTAMP NOT NULL,
    open        DOUBLE NOT NULL,
    high        DOUBLE NOT NULL,
    low         DOUBLE NOT NULL,
    close       DOUBLE NOT NULL,
    volume      BIGINT NOT NULL
)
''')
md.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_candles_pk ON candles (symbol, interval, timestamp)')

existing = md.execute('SELECT COUNT(*) FROM candles').fetchone()[0]
print(f'MotherDuck before: {existing:,} rows')

print('Copying data (this may take several minutes for large databases)...')
local.execute(\"ATTACH 'md:candles' AS remote\")
local.execute('INSERT OR IGNORE INTO remote.candles SELECT * FROM candles')

md_count = md.execute('SELECT COUNT(*) FROM candles').fetchone()[0]
new_rows = md_count - existing
print(f'MotherDuck after: {md_count:,} rows ({new_rows:,} new)')
print()
print('Done! Add these to your .env:')
print(f'  MOTHERDUCK_TOKEN={os.environ[\"MOTHERDUCK_TOKEN\"]}')
print('  CANDLE_STORE_URL=md:candles')

local.close()
md.close()
"
