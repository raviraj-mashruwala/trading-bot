# H1 F&O ORB under real capital limits (Rs 4L), 2019-2026

`research/harness/portfolio.py` + `portfolio_h1.py`. Replays every H1 signal (k=0.5, RVOL>=1.5, 6,817 triggered signals)
in time order against capital, 20% margin per lot, lot = Rs 7.5L notional at entry, max concurrent positions, a per-trade
risk cap (one lot that risks more is skipped), 2% daily realised-loss kill, futures costs plus slippage per side.
Fixed lots, no compounding. Lot size and margin are approximations (see module docstring).

Rs 4L, 2 positions, k=0.5:

| Per-trade risk cap | Slippage/side | Trades taken | Return/yr | Max drawdown | Worst day |
|---|---|---|---|---|---|
| 1.5% (Rs 6k) | 3 bps | 240 | 8% | 38% | -3.3% |
| 2% (Rs 8k) | 3 bps | 1,201 | 13% | 86% | -5.7% |
| 2% (Rs 8k) | 6 bps | 1,191 | -3% | 135% | -5.8% |
| 3% (Rs 12k) | 3 bps | 3,013 | 110% | 114% | -7.2% |
| 3% (Rs 12k) | 6 bps | 3,000 | 64% | 132% | -7.6% |

Per-year P&L, 3% cap, 3 bps: 2019 +2.9L, 2020 +6.2L, 2021 +3.5L, 2022 +3.5L, 2023 +4.1L, 2024 +6.8L, 2025 +0.2L, 2026 +7.3L.

Scaling capital (same strategy, risk cap % of capital, 2 positions, 3 / 6 bps slippage):

| Capital | Risk cap | Return/yr 3 bps | Max DD 3 bps | Return/yr 6 bps | Max DD 6 bps |
|---|---|---|---|---|---|
| 10L | 1.5% | 42% | 47% | 17% | 60% |
| 20L | 1.5% | 44% | 33% | 22% | 40% |
| 20L | 3% | 46% | 42% | 23% | 49% |

Findings:
1. The edge lives in wide-stop (high ADR) names. At a 2% risk cap most signals are skipped (a 1-lot stop costs Rs 8-12k) and what
   remains earns little. The Rs 4L return is only available by risking about 3% of capital per trade.
2. Return/drawdown (Calmar) is about 1 at best (3 bps), 0.5 at 6 bps. At Rs 4L the peak-to-trough drawdown exceeds capital.
3. About Rs 15-20L is needed to run it with a 33-42% max drawdown and 22-46%/yr. Not a Rs 4L strategy.
4. Tighter/looser stops (k = 0.25, 1.0) do not fix it: k=0.25 flips negative at 6 bps, k=1.0 takes almost no trades. Exploratory only.
5. 2025 was nearly flat (+0.2L at 3 bps): multi-year flat spells are normal for this edge.
