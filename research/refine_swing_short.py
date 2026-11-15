"""
Refine the short-side mean-reversion swing strategy (the one stable positive
result from this session) on the ACTUALLY TRADEABLE universe: F&O-eligible
stocks only (since overnight shorts require stock futures in India, not
cash equity).

Grid searches RSI overbought threshold, stop/target ATR multiples, and max
hold period — tuned ONLY on 2022-2024, applied frozen to 2025-2026 holdout.
Same discipline as every other backtest this session: the holdout number is
the real estimate, not the tuning number.

Baseline to beat (RSI>70, stop=1.5xATR, target=3xATR, hold<=10d, F&O-only):
  Holdout: n=190, win_rate=52.1%, avg_r=+0.274R
"""

from __future__ import annotations

import sys
import json
from pathlib import Path
from itertools import product

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb
import pandas as pd

DB_PATH = Path(__file__).parent.parent / "candles.duckdb"
FO_LIST_PATH = Path(__file__).parent / "output" / "fo_eligible_stocks.json"

MIN_VOLUME = 500_000
MIN_PRICE = 50.0
MAX_PRICE = 5_000.0
MIN_HISTORY_DAYS = 70

SMA_WINDOW = 50
RSI_WINDOW = 14
ATR_WINDOW = 14

START_DATE = "2022-01-01"
END_DATE = "2026-10-01"
TUNING_END = "2024-12-31"

RSI_GRID = [65.0, 70.0, 75.0, 80.0]
STOP_GRID = [1.0, 1.5, 2.0]
TARGET_GRID = [3.0, 4.0, 5.0]
HOLD_GRID = [7, 10, 15]


def load_fo_daily(con, fo_symbols: list[str]) -> pd.DataFrame:
    placeholders = ",".join("?" * len(fo_symbols))
    return con.execute(f"""
        SELECT symbol, timestamp::DATE AS d, open, high, low, close, volume
        FROM candles
        WHERE interval = 'day'
        AND timestamp::DATE >= ? AND timestamp::DATE <= ?
        AND symbol IN ({placeholders})
        ORDER BY symbol, d
    """, [START_DATE, END_DATE] + fo_symbols).df()


def compute_rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def compute_base_features(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("d").reset_index(drop=True)
    close, high, low, volume = g["close"], g["high"], g["low"], g["volume"]
    g["sma50"] = close.rolling(SMA_WINDOW).mean()
    g["rsi14"] = compute_rsi(close, RSI_WINDOW)
    g["avg_vol20"] = volume.rolling(20).mean()
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    g["atr14"] = tr.rolling(ATR_WINDOW).mean()
    return g


def simulate_short(full: pd.DataFrame, rsi_threshold: float, stop_mult: float,
                    target_mult: float, max_hold: int) -> pd.DataFrame:
    full = full.copy()
    full["short_signal"] = (full["close"] < full["sma50"]) & (full["rsi14"] > rsi_threshold)

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

            if not g.iloc[i]["short_signal"]:
                continue

            entry_idx = i + 1
            entry_row = g.iloc[entry_idx]
            entry_px = float(entry_row["open"])
            atr = float(g.iloc[i]["atr14"])
            if atr <= 0:
                continue

            stop_px = entry_px + stop_mult * atr
            target_px = entry_px - target_mult * atr
            risk = abs(entry_px - stop_px)

            outcome = None
            exit_px = None
            last_i = min(entry_idx + max_hold, len(g) - 1)

            j = entry_idx
            for j in range(entry_idx, last_i + 1):
                day = g.iloc[j]
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

            pnl_r = (entry_px - exit_px) / risk

            trades.append({
                "symbol": symbol, "date": str(g.iloc[i]["d"]),
                "entry_px": round(entry_px, 2), "exit_px": round(exit_px, 2),
                "outcome": outcome, "pnl_r": round(pnl_r, 3),
            })
            in_position = True

    return pd.DataFrame(trades)


def stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0, "win_rate": 0.0, "avg_r": 0.0, "total_r": 0.0}
    wins = (df["pnl_r"] > 0).sum()
    return {
        "n": len(df),
        "win_rate": wins / len(df) * 100,
        "avg_r": df["pnl_r"].mean(),
        "total_r": df["pnl_r"].sum(),
    }


def main():
    with open(FO_LIST_PATH) as f:
        fo_symbols = json.load(f)

    con = duckdb.connect(str(DB_PATH), read_only=True)
    print(f"Loading daily data for {len(fo_symbols)} F&O-eligible symbols...")
    all_daily = load_fo_daily(con, fo_symbols)
    con.close()
    print(f"Loaded {len(all_daily):,} rows across {all_daily['symbol'].nunique()} symbols")

    results = []
    for symbol, g in all_daily.groupby("symbol"):
        if len(g) < MIN_HISTORY_DAYS:
            continue
        g = compute_base_features(g)
        g["symbol"] = symbol
        results.append(g)

    full = pd.concat(results, ignore_index=True)
    full = full.dropna(subset=["sma50", "rsi14", "atr14", "avg_vol20"])
    full = full[(full["avg_vol20"] >= MIN_VOLUME) & (full["close"] >= MIN_PRICE) & (full["close"] <= MAX_PRICE)]
    print(f"Valid feature rows: {len(full):,}")

    tuning_data = full[full["d"].astype(str) <= TUNING_END]
    holdout_data = full[full["d"].astype(str) > TUNING_END]

    print(f"\n{'='*100}")
    print("GRID SEARCH ON TUNING SET (2022-2024) — short side, F&O-eligible only")
    print(f"{'='*100}")
    print(f"{'RSI':<6}{'Stop':<6}{'Target':<8}{'Hold':<6}{'n':<7}{'Win%':<8}{'Avg R':<10}{'Total R':<10}")

    best = None
    all_grid_results = []
    combos = list(product(RSI_GRID, STOP_GRID, TARGET_GRID, HOLD_GRID))
    for i, (rsi_th, stop_m, target_m, hold_d) in enumerate(combos):
        trades = simulate_short(tuning_data, rsi_th, stop_m, target_m, hold_d)
        s = stats(trades)
        all_grid_results.append((rsi_th, stop_m, target_m, hold_d, s))
        if s["n"] >= 30:  # require minimum sample to be considered
            print(f"{rsi_th:<6}{stop_m:<6}{target_m:<8}{hold_d:<6}{s['n']:<7}{s['win_rate']:.0f}%{'':<5}{s['avg_r']:+.3f}{'':<5}{s['total_r']:+.1f}")
            if best is None or s["avg_r"] > best[4]["avg_r"]:
                best = (rsi_th, stop_m, target_m, hold_d, s)

    if best is None:
        print("No parameter combo had >=30 tuning trades. Aborting.")
        return

    rsi_th, stop_m, target_m, hold_d, tuning_stats = best
    print(f"\nBest on tuning: RSI>{rsi_th}, stop={stop_m}xATR, target={target_m}xATR, hold<={hold_d}d")
    print(f"  Tuning: n={tuning_stats['n']} win_rate={tuning_stats['win_rate']:.1f}% avg_r={tuning_stats['avg_r']:+.3f}R")

    print(f"\n{'='*100}")
    print(f"APPLYING FROZEN BEST PARAMS TO HOLDOUT (2025-2026) — never touched during tuning")
    print(f"{'='*100}")
    holdout_trades = simulate_short(holdout_data, rsi_th, stop_m, target_m, hold_d)
    holdout_stats = stats(holdout_trades)
    print(f"  Holdout: n={holdout_stats['n']} win_rate={holdout_stats['win_rate']:.1f}% avg_r={holdout_stats['avg_r']:+.3f}R total_r={holdout_stats['total_r']:+.1f}R")

    print(f"\n{'='*100}")
    print("COMPARISON TO BASELINE (RSI>70, stop=1.5x, target=3x, hold<=10d)")
    print(f"{'='*100}")
    baseline_tuning = simulate_short(tuning_data, 70.0, 1.5, 3.0, 10)
    baseline_holdout = simulate_short(holdout_data, 70.0, 1.5, 3.0, 10)
    bt_stats = stats(baseline_tuning)
    bh_stats = stats(baseline_holdout)
    print(f"  Baseline tuning:  n={bt_stats['n']} win_rate={bt_stats['win_rate']:.1f}% avg_r={bt_stats['avg_r']:+.3f}R")
    print(f"  Baseline holdout: n={bh_stats['n']} win_rate={bh_stats['win_rate']:.1f}% avg_r={bh_stats['avg_r']:+.3f}R")
    print(f"  Refined holdout:  n={holdout_stats['n']} win_rate={holdout_stats['win_rate']:.1f}% avg_r={holdout_stats['avg_r']:+.3f}R")

    out_path = Path(__file__).parent / "output" / "swing_short_refined_trades.csv"
    holdout_trades.to_csv(out_path, index=False)
    print(f"\nHoldout trade log saved to: {out_path}")


if __name__ == "__main__":
    main()
