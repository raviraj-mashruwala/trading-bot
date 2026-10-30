# Daily Workflow

How to run the bot each day. Sync, analysis and review are manual; the server only
starts execution by itself, at 09:00.

> **Check `config.toml` first.** `[general] mode` is currently `"live"`: the executor
> places real orders. Set `mode = "paper"` to rehearse.

## The day at a glance

```
 EVENING (after 16:00)                         MORNING (before 09:00)
 ─────────────────────                         ──────────────────────
 1. Sync     sync.sh            no LLM         1. Re-login to Kite
 2. Analyze  analyze.sh  ◄──┐                  2. Check today's plan
 3. Chat     answer requests ┘ (repeat)        3. Start the server
 4. Fetch    fetch.sh (once, when asked)
 5. Plan written ─────────────────────────────►  09:00 executor starts itself
                                                 09:15 first entries allowed
                                                 15:10 square-off
```

The plan you build in the evening is for the **next trading day**. How old it is
doesn't matter; only that its `trade_date` is the day it runs.

## Evening: sync, analyze

### Step 1: sync market data

Run from the repo root, or use the IntelliJ run configuration **Analysis — Sync**:

```bash
scripts/analysis/sync.sh          # add --full to force a complete refill
```

- Do this after 16:00 so the day's candles are complete.
- It needs today's Kite login (see Morning, step 1). If you did not log in today, run
  `uv run python -m tradingbot auth` first.
- First run on an empty cache is a full fill and takes a long time. Daily runs are short.
- No LLM is involved, and nothing waits on you.

### Step 2: run the analysis

The analysis asks Claude five questions, one stage at a time, and the answers come from
a Claude Code conversation instead of the Anthropic API (no API billing).

**Easiest way:** open Claude Code in this repo and say:

```
run the analysis for 2026-10-30
```

(use the next trading day's date; leave it out for the next session). The
`answer-llm-requests` skill runs the scripts, answers each stage, and repeats until
the plan is written. When it needs the candle download it starts `fetch.sh` in the
background and carries on when that finishes.

**Doing it by hand** (same thing, one step at a time):

```bash
scripts/analysis/analyze.sh 2026-10-30       # IntelliJ: Analysis — Analyze
```

It runs as far as it can, prints what is needed, and exits:

| Exit code | Meaning | You do |
|---|---|---|
| `10` | LLM answers needed | In Claude Code say: `answer the pending LLM requests for 2026-10-30`, then rerun `analyze.sh` |
| `11` | Shortlist candles missing | Run `scripts/analysis/fetch.sh 2026-10-30` (IntelliJ: **Analysis — Fetch**), then rerun `analyze.sh` |
| `0` | Done | Plan written to `trade_plans/2026-10-30.json` |
| `1` | Error | Read the message; see Troubleshooting |

IntelliJ shows exit 10 and 11 as red runs. That is normal, not a failure.

### What happens during a full analysis

```
 analyze.sh ──► Tier 1 screen (local data, seconds)
      │ exit 10
      ▼
 Chat: regime ─► (analyze.sh) ─► sectors ─► (analyze.sh) ─► shortlist
      │ exit 11
      ▼
 fetch.sh ──► downloads candles for the shortlisted stocks (the slow part)
      │
      ▼ analyze.sh ─► exit 10
 Chat: deep analysis, every shortlisted stock at once
      │
      ▼ analyze.sh ─► backtests run ─► exit 10
 Chat: adversarial portfolio review
      │
      ▼ analyze.sh ─► exit 0
 plan: trade_plans/2026-10-30.json (N legs)
```

That is about five chat rounds. No script ever waits on the chat: each run does its work,
writes its questions to files, and exits.

Rerunning `analyze.sh` after it finished is safe: it replaces the earlier approved
setups instead of adding duplicates.

## Morning: before 09:00

1. **Re-login to Kite.** The token expires early every morning.
   ```bash
   uv run python -m tradingbot auth
   ```
   Open the printed URL, log in, paste the `request_token` from the redirect URL. Or use
   the Telegram commands `/login` then `/token`.
2. **Check the plan for today exists.**
   ```bash
   uv run python -m tradingbot plan show --date 2026-10-30
   ```
3. **Start the server** (IntelliJ: **Backend — API Server**):
   ```bash
   uv run python -m tradingbot serve
   ```
   It must be running before 09:00.

## During the day

Nothing to do. The server starts the executor between 09:00 and 09:05, holds entries
until 09:15, manages the plan, and squares off at 15:10. Watch the dashboard
(`http://localhost:3000` if you run the frontend) or Telegram.

- Telegram `/status` shows positions and P&L. `/stop confirm` is the emergency stop.
- Live orders only work from an IP on your Kite app's whitelist. If orders are rejected
  with "IP is not allowed", check that you are on a whitelisted network (VPN or not).

## After market (optional): nightly review

The review is manual now. To grade a day:

```bash
curl -X POST "http://localhost:8000/api/review/nightly?date=2026-10-29"
```

(the server must be running). Results: `GET /api/review/nightly?date=...`.

## Where things live

| What | Where |
|---|---|
| Trade plans | `trade_plans/YYYY-MM-DD.json` |
| LLM questions for a day | `llm_queue/<date>/requests/` |
| Claude's answers | `llm_queue/<date>/answers/` |
| Rejected (invalid) answers | `llm_queue/<date>/rejected/` (with a `.reason.txt`) |
| Candle cache | `candles.duckdb` |
| Trade history | `tradingbot.db` |
| Kite token | `~/.tradingbot/kite_token` |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `no Kite access token found` | Run `uv run python -m tradingbot auth` |
| `analyze.sh` exit 11 forever | `fetch.sh` could not get fresh candles. Usually an expired token: run `auth`, rerun `fetch.sh` |
| `no fresh candle data after fetch` | Same: expired token, or Kite is down. Re-auth and retry |
| Exit 10 again after you answered | An answer failed validation. Check `llm_queue/<date>/rejected/<id>.reason.txt`, fix, rewrite the answer. `uv run python -m tradingbot llm pending --date <date>` lists what is still unanswered |
| `... is not a trading day` | Pick a trading day, or omit the date |
| `plan is for X, not today` | The plan's date is not today. Run the analysis for today's date, or check the date |
| Want to redo a day's analysis from scratch | Delete `llm_queue/<date>/` and rerun |
| Orders rejected: IP not allowed | Whitelist your current IPv4 in the Kite developer console (up to 2) |

## Quick reference

```bash
scripts/analysis/sync.sh                    # evening: refresh candles
scripts/analysis/analyze.sh [DATE]          # advance the analysis (exit 10 / 11 / 0)
scripts/analysis/fetch.sh [DATE]            # download shortlist candles (when exit 11)
uv run python -m tradingbot llm pending --date DATE   # what still needs an answer
uv run python -m tradingbot auth            # morning: Kite login
uv run python -m tradingbot plan show --date DATE
uv run python -m tradingbot serve           # morning: before 09:00
```
