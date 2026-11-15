"""
Final validation step of the Assignment: run immediate-entry on the full
Tier1 replay candidate set (scripts/replay_tier1_history.py output,
~435 candidates across 87 days), with a proper chronological tuning/holdout
split — NOT re-tuning on the same data we're measuring, unlike the small
12-candidate sample in backtest_immediate_entry_v2.py.

Process:
  1. Split the 87 days chronologically: first 60% = TUNING set, last 40% =
     HOLDOUT set.
  2. On the TUNING set only, try a small grid of (breakeven_trigger_r,
     target_r) pairs and pick whichever maximizes avg R.
  3. Freeze those parameters. Run them UNCHANGED on the HOLDOUT set.
  4. Report HOLDOUT performance as the real estimate — this is what matters,
     not the tuning-set number.

Reuses the exact simulate_immediate() mechanics from
backtest_immediate_entry.py (immediate entry at first-candle close, SL from
first-candle opposite extreme, 0.5% minimum risk floor).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb
import pandas as pd

DB_PATH = Path(__file__).parent.parent / "candles.duckdb"
CANDIDATES_PATH = Path(__file__).parent / "output" / "tier1_replay_candidates.json"

MIN_RISK_PCT = 0.005
TUNING_FRACTION = 0.6

# Grid searched ONLY on the tuning set.
PARAM_GRID = [
    (1.0, 1.5),
    (1.5, 2.0),
    (2.0, 3.0),
    (2.5, 3.5),
]


def load_day(con, sym: str, trade_date: str) -> pd.DataFrame:
    df = con.execute("""
        SELECT timestamp, open, high, low, close, volume
        FROM candles
        WHERE symbol=? AND interval='1m'
        AND timestamp::DATE = ?
        ORDER BY timestamp
    """, [sym, trade_date]).df()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def simulate_immediate(df: pd.DataFrame, direction: str, breakeven_at_r: float, target_r: float) -> dict:
    if df.empty or len(df) < 2:
        return {"status": "NO_DATA"}

    first_candle = df.iloc[0]
    entry_px = float(first_candle["close"])

    if direction == "short":
        raw_sl = float(first_candle["high"])
    else:
        raw_sl = float(first_candle["low"])

    raw_risk = abs(entry_px - raw_sl)
    min_risk = entry_px * MIN_RISK_PCT
    risk = max(raw_risk, min_risk)
    if risk <= 0:
        return {"status": "DEGENERATE_RISK"}

    sl_px = entry_px + risk if direction == "short" else entry_px - risk
    target_px = entry_px - target_r * risk if direction == "short" else entry_px + target_r * risk
    breakeven_px = entry_px - breakeven_at_r * risk if direction == "short" else entry_px + breakeven_at_r * risk

    after_entry = df.iloc[1:]
    current_sl = sl_px
    moved_to_breakeven = False
    exit_px = None
    outcome = None

    for _, c in after_entry.iterrows():
        if direction == "short":
            if not moved_to_breakeven and c["low"] <= breakeven_px:
                current_sl = entry_px
                moved_to_breakeven = True
            if c["high"] >= current_sl:
                exit_px = current_sl
                outcome = "BREAKEVEN" if moved_to_breakeven and current_sl == entry_px else "SL"
                break
            if c["low"] <= target_px:
                exit_px = target_px
                outcome = "TARGET"
                break
        else:
            if not moved_to_breakeven and c["high"] >= breakeven_px:
                current_sl = entry_px
                moved_to_breakeven = True
            if c["low"] <= current_sl:
                exit_px = current_sl
                outcome = "BREAKEVEN" if moved_to_breakeven and current_sl == entry_px else "SL"
                break
            if c["high"] >= target_px:
                exit_px = target_px
                outcome = "TARGET"
                break

    if exit_px is None:
        exit_px = float(after_entry.iloc[-1]["close"])
        outcome = "EOD"

    pnl_r = (entry_px - exit_px) / risk if direction == "short" else (exit_px - entry_px) / risk
    return {"status": "TRIGGERED", "outcome": outcome, "pnl_r": round(pnl_r, 3)}


def run_set(con, candidates: list[dict], breakeven_at_r: float, target_r: float) -> dict:
    results = []
    for c in candidates:
        df = load_day(con, c["symbol"], c["date"].split(" ")[0])
        r = simulate_immediate(df, c["direction"], breakeven_at_r, target_r)
        if r.get("status") == "TRIGGERED":
            results.append(r)

    if not results:
        return {"n": 0, "win_rate": 0, "avg_r": 0, "total_r": 0}

    wins = sum(1 for r in results if r["pnl_r"] > 0)
    total_r = sum(r["pnl_r"] for r in results)
    return {
        "n": len(results),
        "win_rate": wins / len(results) * 100,
        "avg_r": total_r / len(results),
        "total_r": total_r,
        "triggered_of": len(candidates),
    }


def main():
    with open(CANDIDATES_PATH) as f:
        candidates = json.load(f)

    # chronological split
    candidates.sort(key=lambda c: c["date"])
    dates_sorted = sorted(set(c["date"] for c in candidates))
    split_idx = int(len(dates_sorted) * TUNING_FRACTION)
    tuning_dates = set(dates_sorted[:split_idx])
    holdout_dates = set(dates_sorted[split_idx:])

    tuning_set = [c for c in candidates if c["date"] in tuning_dates]
    holdout_set = [c for c in candidates if c["date"] in holdout_dates]

    print("=" * 100)
    print("TIER1 REPLAY BACKTEST — TUNING/HOLDOUT SPLIT (immediate entry mechanism)")
    print("=" * 100)
    print(f"Total candidates: {len(candidates)} across {len(dates_sorted)} days")
    print(f"Tuning set:  {len(tuning_set)} candidates, {len(tuning_dates)} days "
          f"({min(tuning_dates)} to {max(tuning_dates)})")
    print(f"Holdout set: {len(holdout_set)} candidates, {len(holdout_dates)} days "
          f"({min(holdout_dates)} to {max(holdout_dates)})")

    con = duckdb.connect(str(DB_PATH), read_only=True)

    print(f"\n{'─'*100}")
    print("STEP 1: Grid search on TUNING set only")
    print(f"{'─'*100}")
    print(f"{'BE_trigger':<12}{'Target_R':<10}{'n':<6}{'Win%':<8}{'Avg R':<10}{'Total R':<10}")

    best = None
    for be_r, target_r in PARAM_GRID:
        stats = run_set(con, tuning_set, be_r, target_r)
        print(f"{be_r:<12}{target_r:<10}{stats['n']:<6}{stats['win_rate']:.0f}%{'':<5}{stats['avg_r']:+.2f}{'':<5}{stats['total_r']:+.1f}")
        if best is None or stats["avg_r"] > best[2]["avg_r"]:
            best = (be_r, target_r, stats)

    best_be, best_target, best_tuning_stats = best
    print(f"\nBest on tuning set: BE@{best_be}R, target={best_target}R "
          f"(avg_r={best_tuning_stats['avg_r']:+.2f}R, n={best_tuning_stats['n']})")

    print(f"\n{'─'*100}")
    print(f"STEP 2: Apply FROZEN parameters (BE@{best_be}R, target={best_target}R) to HOLDOUT set — never touched during tuning")
    print(f"{'─'*100}")
    holdout_stats = run_set(con, holdout_set, best_be, best_target)
    print(f"  n={holdout_stats['n']} (of {holdout_stats['triggered_of']} candidates)")
    print(f"  Win rate: {holdout_stats['win_rate']:.0f}%")
    print(f"  Avg R: {holdout_stats['avg_r']:+.2f}R")
    print(f"  Total R: {holdout_stats['total_r']:+.1f}R")

    con.close()

    print(f"\n{'='*100}")
    print("VERDICT")
    print(f"{'='*100}")
    print(f"  Tuning set (parameters chosen here):  avg_r={best_tuning_stats['avg_r']:+.2f}R, win_rate={best_tuning_stats['win_rate']:.0f}%, n={best_tuning_stats['n']}")
    print(f"  Holdout set (parameters NEVER seen):  avg_r={holdout_stats['avg_r']:+.2f}R, win_rate={holdout_stats['win_rate']:.0f}%, n={holdout_stats['n']}")
    degradation = best_tuning_stats['avg_r'] - holdout_stats['avg_r']
    print(f"  Degradation from tuning to holdout: {degradation:+.2f}R")
    print(f"\n  Target: holdout avg_r >= 1.5R AND win_rate >= 50% AND n >= 30")
    meets = holdout_stats['n'] >= 30 and holdout_stats['win_rate'] >= 50 and holdout_stats['avg_r'] >= 1.5
    print(f"  {'PASS — mechanism holds on unseen data' if meets else 'FAIL — does not clear the bar on unseen data'}")
    print(f"\n  NOTE: direction bias in this candidate set is a heuristic proxy (sign of")
    print(f"  5d relative-strength vs NIFTY), not the real LLM shortlist judgment.")
    print(f"  This validates the MECHANISM under that proxy. Phase 2 (re-running the")
    print(f"  actual LLM on a subsample) is still needed before trusting this for real capital.")


if __name__ == "__main__":
    main()
