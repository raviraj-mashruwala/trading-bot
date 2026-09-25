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

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env    # then fill in your keys
```

Edit `config.toml` to set your capital and risk limits. It starts in paper mode.

## Usage

```bash
tradingbot analyze                 # write tomorrow's plan
tradingbot plan show               # read it back before the open
tradingbot execute --paper         # trade it in simulation
tradingbot history --detailed      # review what happened
tradingbot backtest --symbol TCS --days 90
```

Going live is a deliberate act: run `tradingbot auth` to authorise Kite Connect,
then change `mode = "live"` in `config.toml`.

## Before you risk real money

Paper trade for at least 30 sessions and check that win rate is above 50%, average
reward:risk is above 1.5, and max drawdown stayed under 5% of capital. The bot will
not promote itself to live trading.

## Risk controls

- 1% of capital risked per trade, 2% daily loss kill switch
- At most 2 concurrent positions, at most 50% of capital deployed
- Every position is squared off at 15:10, no exceptions
- Restarting mid-session adopts open positions instead of double-entering

## Testing

```bash
pytest tests/ -v
```
