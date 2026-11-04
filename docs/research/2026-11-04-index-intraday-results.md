# I-series: intraday index strategies on Nifty 50 and Bank Nifty (spot 1m, futures costs)

Pre-registered in `research/harness/index_intraday.py`. Spot 1m bars 2015-2026 stand in for futures (Kite keeps no minute
data for expired futures). Futures cost schedule, about 4 bps round trip at 0.5 bp slippage per side, 5 bps at 1 bp.
7 strategies x 2 indices = 14 trials. Holdout NOT spent (nothing passed train or valid).

Net bps per trade at 1 bp slippage per side:

| Strategy | Nifty train | Nifty valid | BankNifty train | BankNifty valid |
|---|---|---|---|---|
| mom_last30 (first 30m -> last 30m) | -4.9 | -3.0 | -5.0 | -6.1 |
| mom_last30 incl. overnight gap | -4.1 | -4.5 | -4.8 | -5.3 |
| ORB15 with stop | +0.4 | -2.8 | +3.9 | -7.1 |
| ORB15 held to 15:15 | -4.0 | -6.1 | -0.5 | -11.2 |
| gap fade | +1.7 | -5.0 | +1.4 | -0.9 |
| gap follow | -11.6 | -4.9 | -11.3 | -9.0 |
| midday momentum | +0.7 | -1.4 | +2.1 | -2.8 |

Gross edge before costs is between -9 and +9 bps everywhere, t-stats near zero for anything positive.
Verdict: no edge in simple intraday price patterns on Nifty or Bank Nifty, 2015-2023, even with the cheapest instrument.
