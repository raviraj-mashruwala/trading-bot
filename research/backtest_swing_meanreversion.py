"""
Swing trading backtest — mean-reversion pullback, long and short, on daily OHLCV.

Mirror hypothesis to backtest_swing_momentum.py (which failed cleanly: avg R
~0 across 35,580 trades). This tests the other classical, well-documented
swing idea: buying oversold pullbacks WITHIN an established uptrend (not
calling a bottom in a downtrend — the trend context still has to agree),
and shorting overbought bounces within an established downtrend.

LONG entry: stock is above its 50-day SMA (uptrend context) AND RSI(14) < 30
(sharp recent pullback, oversold) — buy the dip, not the knife.

SHORT entry: stock is below its 50-day SMA (downtrend context) AND
RSI(14) > 70 (sharp recent rally, overbought) — short the bounce, not the
breakout.

Same execution framework as the momentum test, for a fair comparison:
next-day-open entry, stop = 1.5x ATR(14), target = 3x ATR, max hold 10
trading days, same liquidity filter, same 2022-2024 tuning / 2025-2026
holdout split.

Same caveat as the momentum script: close prices are not split/bonus
adjusted in this DB.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb
import pandas as pd

DB_PATH = Path(__file__).parent.parent / "candles.duckdb"

MIN_VOLUME = 500_000
MIN_PRICE = 50.0
MAX_PRICE = 5_000.0
MIN_HISTORY_DAYS = 70

SMA_WINDOW = 50
RSI_WINDOW = 14
ATR_WINDOW = 14
RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0
STOP_ATR_MULT = 1.5
TARGET_ATR_MULT = 3.0
MAX_HOLD_DAYS = 10

START_DATE = "2022-01-01"
END_DATE = "2026-10-01"
TUNING_END = "2024-12-31"


def load_all_daily(con) -> pd.DataFrame:
    return con.execute("""
        SELECT symbol, timestamp::DATE AS d, open, high, low, close, volume
        FROM candles
        WHERE interval = 'day'
        AND timestamp::DATE >= ? AND timestamp::DATE <= ?
        AND symbol NOT IN ('NIFTY 50', 'INDIA VIX', 'NIFTY BANK')
        ORDER BY symbol, d
    """, [START_DATE, END_DATE]).df()


def compute_rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def compute_signals_for_symbol(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("d").reset_index(drop=True)
    close, high, low, volume = g["close"], g["high"], g["low"], g["volume"]

    g["sma50"] = close.rolling(SMA_WINDOW).mean()
    g["rsi14"] = compute_rsi(close, RSI_WINDOW)
    g["avg_vol20"] = volume.rolling(20).mean()

    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    g["atr14"] = tr.rolling(ATR_WINDOW).mean()

    return g


def simulate(full: pd.DataFrame) -> pd.DataFrame:
    trades = []
    for symbol, g in full.groupby("symbol"):
        g = g.sort_values("d").reset_index(drop=True)
        in_position = False
        exit_idx = -1
        for i in range(len(g) - 1):
            if in_position:
                if i <= exit_idx:
                    continue
                else:
                    in_position = False

            row = g.iloc[i]
            direction = None
            if row["long_signal"]:
                direction = "long"
            elif row["short_signal"]:
                direction = "short"
            if direction is None:
                continue

            entry_idx = i + 1
            entry_row = g.iloc[entry_idx]
            entry_px = float(entry_row["open"])
            atr = float(row["atr14"])
            if atr <= 0:
                continue

            if direction == "long":
                stop_px = entry_px - STOP_ATR_MULT * atr
                target_px = entry_px + TARGET_ATR_MULT * atr
            else:
                stop_px = entry_px + STOP_ATR_MULT * atr
                target_px = entry_px - TARGET_ATR_MULT * atr

            risk = abs(entry_px - stop_px)
            outcome = None
            exit_px = None
            last_i = min(entry_idx + MAX_HOLD_DAYS, len(g) - 1)

            j = entry_idx
            for j in range(entry_idx, last_i + 1):
                day = g.iloc[j]
                if direction == "long":
                    if day["low"] <= stop_px:
                        outcome, exit_px = "SL", stop_px
                        break
                    if day["high"] >= target_px:
                        outcome, exit_px = "TARGET", target_px
                        break
                else:
                    if day["high"] >= stop_px:
                        outcome, exit_px = "SL", stop_px
                        break
                    if day["low"] <= target_px:
                        outcome, exit_px = "TARGET", target_px
                        break

            if outcome is None:
                last_day = g.iloc[last_i]
                outcome, exit_px = "TIME", float(last_day["close"])
                exit_idx = last_i
            else:
                exit_idx = j

            pnl_r = (exit_px - entry_px) / risk if direction == "long" else (entry_px - exit_px) / risk

            trades.append({
                "symbol": symbol, "date": str(row["d"]), "direction": direction,
                "entry_px": round(entry_px, 2), "exit_px": round(exit_px, 2),
                "outcome": outcome, "pnl_r": round(pnl_r, 3),
                "hold_days": exit_idx - entry_idx,
            })
            in_position = True

    return pd.DataFrame(trades)


def summarize(df, label):
    if df.empty:
        print(f"{label}: no trades")
        return
    wins = (df["pnl_r"] > 0).sum()
    win_rate = wins / len(df) * 100
    avg_r = df["pnl_r"].mean()
    total_r = df["pnl_r"].sum()
    longs = (df["direction"] == "long").sum()
    shorts = (df["direction"] == "short").sum()
    print(f"{label}: n={len(df):,} ({longs:,} long / {shorts:,} short) | "
          f"win_rate={win_rate:.1f}% avg_r={avg_r:+.3f}R total_r={total_r:+.1f}R")


def main():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    print("Loading full daily dataset...")
    all_daily = load_all_daily(con)
    con.close()
    print(f"Loaded {len(all_daily):,} daily rows across {all_daily['symbol'].nunique()} symbols")

    print("Computing signals per symbol...")
    results = []
    symbol_count = 0
    for symbol, g in all_daily.groupby("symbol"):
        if len(g) < MIN_HISTORY_DAYS:
            continue
        g = compute_signals_for_symbol(g)
        g["symbol"] = symbol
        results.append(g)
        symbol_count += 1

    full = pd.concat(results, ignore_index=True)
    full = full.dropna(subset=["sma50", "rsi14", "atr14", "avg_vol20"])
    print(f"Computed signals for {symbol_count} symbols, {len(full):,} valid rows")

    full = full[(full["avg_vol20"] >= MIN_VOLUME) & (full["close"] >= MIN_PRICE) & (full["close"] <= MAX_PRICE)]

    full["long_signal"] = (full["close"] > full["sma50"]) & (full["rsi14"] < RSI_OVERSOLD)
    full["short_signal"] = (full["close"] < full["sma50"]) & (full["rsi14"] > RSI_OVERBOUGHT)

    print(f"Long signals: {full['long_signal'].sum():,}  Short signals: {full['short_signal'].sum():,}")

    trades_df = simulate(full)
    print(f"\nTotal trades simulated: {len(trades_df):,}")

    tuning = trades_df[trades_df["date"] <= TUNING_END]
    holdout = trades_df[trades_df["date"] > TUNING_END]

    print(f"\n{'='*90}")
    print("SWING MEAN-REVERSION PULLBACK — FULL UNIVERSE, MULTI-YEAR BACKTEST")
    print(f"{'='*90}")
    summarize(tuning, f"Tuning   ({START_DATE} to {TUNING_END})")
    summarize(holdout, f"Holdout  ({TUNING_END} to {END_DATE})")
    summarize(trades_df, "Combined")

    print(f"\nBy direction (holdout only):")
    for d in ["long", "short"]:
        sub = holdout[holdout["direction"] == d]
        summarize(sub, f"  {d}")

    print(f"\nBy outcome (holdout only):")
    print(holdout["outcome"].value_counts())

    out_path = Path(__file__).parent / "output" / "swing_meanreversion_trades.csv"
    trades_df.to_csv(out_path, index=False)
    print(f"\nFull trade log saved to: {out_path}")


if __name__ == "__main__":
    main()
