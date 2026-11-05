# H1 on F&O stocks with futures costs: first strategy with out-of-sample net evidence at intraday

Same pre-registered rules as `research/harness/h1_orb_in_play.py` (opening-range breakout on stocks in play: RVOL of the
first 5 minutes vs 14-day baseline, top 5 per day, direction = first 5-minute candle, stop k x ADR14, flat by 15:10).
Changes from the failed cash version: universe is 205 F&O stocks with >= 1,000 days of 1m history (2019-2026, downloaded
from Kite, `fno_universe.txt`), costs are the futures schedule (about 4 bps round trip plus slippage per side).
Spot 1m bars stand in for futures bars (Kite has no minute data for expired futures).

Net R per trade, k = 0.5, RVOL >= 1.5 (6 grid configs, Bonferroni 6):

| Split | Slippage/side | n | Gross R | Net R | t | bps net | Gate |
|---|---|---|---|---|---|---|---|
| train 2019-22 | 3 bps | 3,557 | +0.128 | +0.064 | 2.8 | +9.9 | PASS |
| valid 2023-24 | 3 bps | 1,684 | +0.174 | +0.099 | 2.7 | +10.5 | PASS |
| holdout 2025-26 | 3 bps | 1,576 | +0.178 | +0.102 | 2.8 | +14.3 | PASS (p 0.004) |
| holdout 2025-26 | 6 bps | 1,576 | +0.178 | +0.053 | 1.45 | +8.3 | not significant |
| train / valid | 8 bps | - | - | about 0 | about 0 | about 0 | fails |

Holdout by year at 3 bps: 2025 +0.02R, 2026 +0.20R. Break-even slippage is about 6-7 bps per side.
Hindsight check (only F&O names with 1,800+ days of history, so no recent entrants): net R +0.05 train (t 2.3), +0.08 valid (t 2.2).

Why the cash version failed and this one works: cash costs about 28 bps round trip vs about 8-10 here, and the F&O universe has
roughly double the gross edge (+0.13 to +0.18R vs +0.08R).

Open questions (not answered by this backtest):
1. Real stop-entry slippage in fast "in play" stocks. 3 bps passes, 6 bps is marginal, 8 bps is zero.
2. Portfolio fit: top 5 per day, 2-3 trades per day on average, one stock-futures lot is Rs 5-10L notional and about Rs 1-2L margin.
   Capital of Rs 4L fits about 2 lots, and a 0.5 x ADR stop can risk 2% of capital per trade. Not yet simulated.
3. Futures lot sizes and margins changed over time; spot bars differ slightly from futures prices.
4. 2025 edge was only +0.02R. Edge is lumpy.
5. Holdout spent for k = 0.5 (log: research/output/harness/holdout_log.txt, local).
