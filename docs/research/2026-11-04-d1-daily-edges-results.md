# D1: open-to-close edges on daily OHLC (2015-2026)

Rules and grid pre-registered in `research/harness/daily_edges.py`. Data: price-adjusted daily bars,
809 symbols (2015) to 1,621 (2026) in `candles.duckdb`; no download. Point-in-time liquid names only
(median turnover >= Rs 25 cr). Top 5 per day, enter at open, exit at close, Rs 1L notional, full NSE
cost schedule plus slippage per side. Bonferroni over 4 strategies.

Net bps per trade at 10 bps slippage per side (cost about 28 bps round trip):

| Strategy | train 2015-20 | valid 2021-23 | holdout 2024-26 |
|---|---|---|---|
| gap_follow | -70 | -129 | -109 |
| **gap_fade** | +13 (t 0.7) | +73 (t 4.1) | +53 (t 6.1) |
| reversal (prior-day) | -28 | -32 | -10 |
| momentum (prior-day) | -29 | -24 | -46 |

Universe drift is a known pattern: overnight +10 to +30 bps/day, intraday -9 to -19 bps/day, every year.

gap_fade (fade gaps of >= 1.5 x ADR at the open, close flat the same day) is the first strategy to clear the gate
out of sample. It lost its train period, so the claim rests on 2021-2026.

Holdout net bps by year: 2024 +117, 2025 +40, 2026 +17 (10 bps slippage); at 20 bps 2026 is -3.

Why this is not yet tradable:
1. Breakeven slippage is about 30 bps per side pooled on train+valid. Fill quality at the open is the whole question.
2. Decaying: yearly net edge has fallen each year since 2024.
3. Skewed: holdout win rate 46%, median -13 bps, mean +53. A few large reversals carry it.
4. Unbounded tail on the short side: a gap-up that runs to the upper circuit costs up to -20% per trade with no stop.
5. Train/valid edge sits in the least liquid tercile (+135 bps) and is negative in the most liquid (-27 bps).
6. Holdout was spent (see research/output/harness/holdout_log.txt, local). Any further tuning needs fresh data.
7. Needs intraday shorting in cash and a signal known at the 09:08 pre-open close.

Next: forward paper trade with real pre-open indicative prices and measured fills; design a stop and sizing rule on
train+valid only.
