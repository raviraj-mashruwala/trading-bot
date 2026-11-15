# Intraday Edge Test Bench — Design

Date: 2026-11-04
Status: DRAFT, awaiting approval of Phase-1 scope

## Problem

The bot's execution and plan pipeline work, but no strategy has been shown to make
money after costs. Own results so far:

- Swing momentum: 35,580 trades, mean -0.001R (before costs).
- Swing mean-reversion: 3,186 trades, +0.118R (longs +0.165R, n=1,943). Pre-cost, untested out of sample.
- Saved plans replayed (24 entries): 8 levels invalid at fill, 4 no entry, 7 stops, 2 targets.
- Real trades executed: 0.
- LLM shortlist: no out-of-sample evidence it beats random liquid picks.

External evidence: 70%+ of individual intraday cash traders lose (SEBI FY23); a 2026
walk-forward test of 14 plain-OHLCV intraday signal families found none that survived
costs. The only independent positive replications need a catalyst ("stocks in play") or
volatility-scaled sizing.

Goal: find out, cheaply and honestly, whether any intraday idea has a real net edge, before
more pipeline work or real capital.

## Data we have (candles.duckdb, measured 2026-11-04)

| Interval | Rows | Symbols | Range |
|---|---|---|---|
| 1m | 56.5M | 407 | 2019-01-01 .. 2026-10-30 |
| 5m | 14.4M | 137 | 2019-01-01 .. 2026-10-30 |
| 15m | 4.8M | 137 | same |
| day | 3.2M | 1,621 | 2015-01-01 .. 2026-10-30 |

Constraints found:

1. Symbols with 1m data per year: 64 (2019) rising to 102 (2025), then 406 in 2026 only.
   Only 65 symbols have 1,500+ trading days of 1m. The long-history universe is about 65 stocks.
   Likely a fixed, hand-picked list, so survivorship/selection bias must be checked.
2. `NIFTY 50` and `NIFTY BANK` have daily bars only. No intraday index series.
3. `BANKNIFTY1` (continuous futures) has 1m and 5m since 2019. `NIFTY1` has daily only.
   So index-momentum tests start with BankNifty futures, not Nifty.
4. No news, earnings or announcement data in the store. Catalyst tests need free NSE
   corporate-announcement and bhavcopy (delivery %) data fetched separately.

## Approach: one harness, many hypotheses

Build `research/harness/` (not part of `tradingbot/`):

1. Cost model: reuse `estimated_cost` from `research/replay_saved_plans.py`
   (brokerage, STT, exchange, GST, stamp, 5 bps slippage per side). Every result is net.
2. Event-driven intraday simulator on 1m bars: entry, stop, target, forced exit at 15:10,
   gap-aware fills, ambiguous-bar exclusion (counted, not called wins).
3. Walk-forward splitter: expanding window, locked final holdout never used for tuning.
4. Significance: t-stat on net R per trade, permutation test, per-year consistency table.
5. Hypothesis registry: each idea has frozen rules written before running (pre-registration),
   same as `compare_saved_plan_entries.py`.

Promotion gate (all required): n >= 300 trades, net mean R > 0, t >= 2 out of sample,
positive in most calendar years, passes permutation test. Then 60+ trading days forward
paper trade with the real executor.

## Hypothesis list, in testing order

1. Stocks in play ORB: gap >= X% or relative volume >= 3x at 09:20, trade the opening-range
   break in gap direction. Universe: the 65-stock long-history set, extended to 2026's 406.
2. BankNifty futures intraday momentum: first-30-minute return predicts last-30-minute
   return, vol-scaled, trailing stop.
3. Gap behaviour by gap size and regime (fade vs continuation).
4. Close-of-day continuation.
5. Event/earnings drift (needs NSE announcement data).
6. Sector-relative intraday reversal (market neutral).
7. Mean-reversion long (the only positive swing result), tested as an intraday variant.
8. Options structures: deferred, no data.

Not pursued: tick/order-book microstructure (data and latency not available at ₹4L).

## LLM role (after an edge exists)

Move from "pick winners" to "is this name in play and why" (catalyst classification).
Validate the filter against random picks from the same candidate pool before trusting it.

## Costs

Zero new spend. Data: existing DuckDB plus free NSE bhavcopy and announcements.
LLM: Claude Code session, no API billing.

## Phase 1 scope (proposed first build)

- Harness skeleton + cost model + walk-forward + stats.
- Hypotheses 1 and 2 only.
- Deliverable: a results table per hypothesis (n, net R, t-stat, per-year, holdout) and a
  go / no-go call. No changes to `tradingbot/`.

## Open risks

- 65-stock universe may be survivor-biased, so 7-year results may overstate edge.
- 1m history for 2026 on 406 symbols is only one year, thin for walk-forward.
- Slippage of 5 bps may be optimistic for lower-liquidity names. Run a sensitivity check at 10 and 20 bps.
- Multiple-testing: 8 hypotheses means a t>=2 pass can be luck. Apply a stricter threshold (t >= 3) or Bonferroni when several are tried.

## The assignment

Before building: decide whether to accept that the likely outcome is "most or all ideas fail".
That outcome is a valid result and saves real capital.
