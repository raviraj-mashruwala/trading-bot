"""
Swing trading backtest — momentum breakout, long and short, on daily OHLCV.

Strategy: a textbook, well-documented breakout-momentum setup (same family as
turtle trading / Donchian breakout systems), tested on this bot's actual
universe and data, not assumed to work just because it's a known idea.

LONG entry: stock makes a new 20-trading-day closing high, is above its
50-day SMA (uptrend context), and has positive 20-day relative strength vs
NIFTY (not just an absolute move — genuinely outperforming the market).

SHORT entry: mirror — new 20-day low, below 50-day SMA, negative RS vs NIFTY.

Entry executes at the NEXT day's open (today's signal, tomorrow's fill — no
lookahead). Stop = 1.5x ATR(14) at signal time. Target = 3x ATR (2:1
reward:risk). Max hold = 10 trading days, exit at that day's close if
neither stop nor target hit first (checked via daily high/low touch).

Liquidity filter matches production's screening defaults (min_volume
500k, price 50-5000) — same bar real candidates would need to clear.

Split chronologically: 2022-2024 for any future tuning, 2025-2026 holdout,
reported separately — same discipline as the intraday backtests this
session, so this doesn't repeat the earlier overfitting mistake.

CAVEAT: close prices are NOT split/bonus-adjusted in this DB (raw Kite data).
A real corporate action will show as a false "new 20-day high/low" and a
nonsensical return. Not corrected here — flagged as a known data-quality
limitation; results should be read as directional, not final.
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb
import pandas as pd
import numpy as np

DB_PATH = Path(__file__).parent.parent / "candles.duckdb"

MIN_VOLUME = 500_000
MIN_PRICE = 50.0
MAX_PRICE = 5_000.0
MIN_HISTORY_DAYS = 70

LOOKBACK_WINDOW = 20
SMA_WINDOW = 50
ATR_WINDOW = 14
STOP_ATR_MULT = 1.5
TARGET_ATR_MULT = 3.0
MAX_HOLD_DAYS = 10

START_DATE = "2022-01-01"
END_DATE = "2026-10-01"
TUNING_END = "2024-12-31"  # tuning: start..this date; holdout: after this date


def load_all_daily(con) -> pd.DataFrame:
    df = con.execute("""
        SELECT symbol, timestamp::DATE AS d, open, high, low, close, volume
        FROM candles
        WHERE interval = 'day'
        AND timestamp::DATE >= ? AND timestamp::DATE <= ?
        AND symbol NOT IN ('NIFTY 50', 'INDIA VIX', 'NIFTY BANK')
        ORDER BY symbol, d
    """, [START_DATE, END_DATE]).df()
    return df


def load_nifty(con) -> pd.DataFrame:
    df = con.execute("""
        SELECT timestamp::DATE AS d, close
        FROM candles WHERE symbol='NIFTY 50' AND interval='day'
        AND timestamp::DATE >= ? AND timestamp::DATE <= ?
        ORDER BY d
    """, [START_DATE, END_DATE]).df()
    df["nifty_ret20"] = df["close"].pct_change(LOOKBACK_WINDOW) * 100
    return df[["d", "nifty_ret20"]]


def compute_signals_for_symbol(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("d").reset_index(drop=True)
    close, high, low, volume = g["close"], g["high"], g["low"], g["volume"]

    g["sma50"] = close.rolling(SMA_WINDOW).mean()
    g["roll20high"] = close.rolling(LOOKBACK_WINDOW).max()
    g["roll20low"] = close.rolling(LOOKBACK_WINDOW).min()
    g["ret20"] = close.pct_change(LOOKBACK_WINDOW) * 100
    g["avg_vol20"] = volume.rolling(20).mean()

    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    g["atr14"] = tr.rolling(ATR_WINDOW).mean()

    return g


def main():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    print("Loading full daily dataset...")
    all_daily = load_all_daily(con)
    nifty = load_nifty(con)
    con.close()
    print(f"Loaded {len(all_daily):,} daily rows across {all_daily['symbol'].nunique()} symbols")

    all_daily = all_daily.merge(nifty, on="d", how="left")

    print("Computing signals per symbol (this takes a bit)...")
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
    full = full.dropna(subset=["sma50", "roll20high", "roll20low", "ret20", "atr14", "avg_vol20", "nifty_ret20"])
    print(f"Computed signals for {symbol_count} symbols, {len(full):,} valid rows")

    # Liquidity filter
    full = full[(full["avg_vol20"] >= MIN_VOLUME) & (full["close"] >= MIN_PRICE) & (full["close"] <= MAX_PRICE)]

    full["rs20"] = full["ret20"] - full["nifty_ret20"]
    full["long_signal"] = (full["close"] >= full["roll20high"]) & (full["close"] > full["sma50"]) & (full["rs20"] > 0)
    full["short_signal"] = (full["close"] <= full["roll20low"]) & (full["close"] < full["sma50"]) & (full["rs20"] < 0)

    print(f"Long signals: {full['long_signal'].sum():,}  Short signals: {full['short_signal'].sum():,}")

    # Simulate trades per symbol, no overlapping positions within a symbol
    trades = []
    for symbol, g in full.groupby("symbol"):
        g = g.sort_values("d").reset_index(drop=True)
        in_position = False
        exit_idx = -1
        for i in range(len(g) - 1):  # need i+1 for next-day entry
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

    trades_df = pd.DataFrame(trades)
    print(f"\nTotal trades simulated: {len(trades_df):,}")

    tuning = trades_df[trades_df["date"] <= TUNING_END]
    holdout = trades_df[trades_df["date"] > TUNING_END]

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

    print(f"\n{'='*90}")
    print("SWING MOMENTUM BREAKOUT — FULL UNIVERSE, MULTI-YEAR BACKTEST")
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

    out_path = Path(__file__).parent / "output" / "swing_momentum_trades.csv"
    trades_df.to_csv(out_path, index=False)
    print(f"\nFull trade log saved to: {out_path}")


if __name__ == "__main__":
    main()
