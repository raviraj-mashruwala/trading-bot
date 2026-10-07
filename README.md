# Intraday Trading Bot

Automated intraday equity trading for the Indian market (NSE). Claude picks the
setups before the open; a deterministic executor follows the plan during the session.

## How it works

1. `analyze` scans the NSE universe, filters it down to liquid and tradable names,
   asks Claude which are worth trading tomorrow, designs setups from the technicals
   and recent backtest results, sizes them against your risk limits, and writes
   `trade_plans/YYYY-MM-DD.json`.
2. `execute` reads that plan and trades it. No LLM runs during market hours.

Analysis and execution are fully decoupled — run the analysis the night before or
the morning of, it makes no difference to the executor.

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | >= 3.12 | [python.org](https://www.python.org/downloads/) — check "Add to PATH" on Windows |
| Node.js | >= 20 LTS | [nodejs.org](https://nodejs.org/) |
| Git | any recent | [git-scm.com](https://git-scm.com/downloads) |

## Setup

### 1. Clone and enter the repo

```bash
git clone https://github.com/raviraj-mashruwala/trading-bot.git
cd trading-bot
```

### 2. Python backend

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

**Windows (Command Prompt):**
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
pip install -e ".[dev]"
```

### 3. Environment variables

```bash
cp .env.example .env   # Windows: copy .env.example .env
```

Edit `.env` and fill in your keys:
- `ANTHROPIC_API_KEY` — required, get from [console.anthropic.com](https://console.anthropic.com/)
- `KITE_API_KEY` / `KITE_API_SECRET` — required for live/paper trading, get from [Kite Connect](https://developers.kite.trade/)
- `TYPESAFE_API_KEY` — optional, enables Jev quality scoring

### 4. Frontend dashboard

```bash
cd web
npm install
cd ..
```

### 5. Configuration

Edit `config.toml` to set your capital and risk limits. It starts in paper mode.

## Running

### Start the API server + frontend together

**Terminal 1 — API server:**
```bash
# activate venv first (see step 2)
uvicorn tradingbot.api.app:create_app --factory --reload --port 8000
```

**Terminal 2 — Frontend:**
```bash
cd web
npm run dev
```

Dashboard available at `http://localhost:3000`.

### CLI commands

```bash
tradingbot analyze                 # write tomorrow's plan
tradingbot plan show               # read it back before the open
tradingbot execute --paper         # trade it in simulation
tradingbot history --detailed      # review what happened
tradingbot backtest --symbol TCS --days 90
```

Going live is a deliberate act: run `tradingbot auth` to authorise Kite Connect,
then change `mode = "live"` in `config.toml`.

## Risk controls

- 1% of capital risked per trade, 2% daily loss kill switch
- At most 2 concurrent positions, at most 50% of capital deployed
- Every position is squared off at 15:10, no exceptions
- Restarting mid-session adopts open positions instead of double-entering

## Copying data to another machine

These files are gitignored (they contain your market data, trades, and secrets).
Copy them via USB drive to get the same state on a new machine.

**Required:**

| File | Size* | What it is |
|------|-------|------------|
| `.env` | 4 KB | API keys — **do not skip** |
| `config.toml` | 4 KB | Your capital, risk limits, and strategy settings |

**Data files (place in repo root):**

| File | Size* | What it is |
|------|-------|------------|
| `candles.duckdb` | ~2.4 GB | Historical OHLCV candle data (biggest file) |
| `candles.duckdb.wal` | varies | DuckDB write-ahead log — copy alongside the .duckdb |
| `instruments.db` | ~700 KB | NSE instrument cache (symbols, lot sizes, etc.) |
| `instruments.db-wal` | varies | SQLite WAL — copy alongside the .db |
| `instruments.db-shm` | varies | SQLite shared memory — copy alongside the .db |
| `analysis.db` | ~32 KB | Pipeline analysis results and setups |
| `analysis.db-wal` / `-shm` | varies | SQLite WAL + SHM files |
| `tradingbot.db` | ~32 KB | Trade history and execution records |
| `tradingbot.db-wal` / `-shm` | varies | SQLite WAL + SHM files |

**Optional:**

| Path | Size* | What it is |
|------|-------|------------|
| `trade_plans/` | ~12 KB | Daily trade plan JSONs (`YYYY-MM-DD.json`) |
| `logs/llm/` | ~664 KB | LLM request/response logs per day |

*\*Sizes as of October 2026 — candles.duckdb grows as more market data is fetched.*

**Quick copy (macOS/Linux → USB):**
```bash
# from repo root
cp .env config.toml /Volumes/USB/trading-bot/
cp *.db *.db-wal *.db-shm *.duckdb *.duckdb.wal /Volumes/USB/trading-bot/
cp -r trade_plans/ logs/ /Volumes/USB/trading-bot/
```

**Quick copy (USB → Windows):**
```powershell
# from USB drive, into the cloned repo
Copy-Item E:\trading-bot\.env, E:\trading-bot\config.toml -Destination .\
Copy-Item E:\trading-bot\*.db, E:\trading-bot\*.db-wal, E:\trading-bot\*.db-shm -Destination .\
Copy-Item E:\trading-bot\*.duckdb, E:\trading-bot\*.duckdb.wal -Destination .\
Copy-Item E:\trading-bot\trade_plans, E:\trading-bot\logs -Destination .\ -Recurse
```

> **Note:** If you skip the data files, the bot still works — it will rebuild
> `instruments.db` on first run and fetch fresh candle data. You only lose
> historical analysis results and past trade records.

## Testing

```bash
pytest tests/ -v         # backend
cd web && npm test       # frontend
```
