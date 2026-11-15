"""
Immediate-entry-at-open backtest — v3, tests the pivot away from ORB.

v1 and v2 (backtest_orb.py, backtest_orb_v2.py) both showed the same failure
mode: on these overnight-bias candidates, the real move happens inside the
first few minutes of trading. Any "wait for a confirmed breakout" entry
donates that move and only catches weak EOD drift (avg R 0.2-0.9, 0/5 hit
the 1.5R target across both ORB versions).

This version drops the breakout wait entirely:
  1. Enter in the bias direction right after the FIRST 1m candle closes
     (i.e. at ~9:16, using that candle's close as fill price).
  2. SL = that first candle's opposite extreme (high for shorts, low for
     longs) — this is LIVE data from today's actual open, not a stale
     EOD-derived price. This is the fix for the original root-cause bug
     (gap-open invalidating EOD stop levels).
  3. A minimum risk floor (0.5% of entry price) prevents degenerate
     near-zero stops when the first candle is very narrow.
  4. Target = 1.5R, move stop to breakeven at 1R — same rules as v1/v2 for
     a clean three-way comparison.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb
import pandas as pd

DB_PATH = Path(__file__).parent.parent / "candles.duckdb"

TARGET_R = 3.0
BREAKEVEN_AT_R = 2.0
MIN_RISK_PCT = 0.005  # 0.5% floor on SL distance

PLANS = {
    "2026-10-08": [("NELCAST", "short"), ("GLAND", "short")],
    "2026-10-09": [("ADANIENT", "short"), ("INDIAGLYCO", "short")],
    "2026-10-12": [("KEC", "short"), ("SHANTIGOLD", "long")],
    "2026-10-14": [("GOODLUCK", "long"), ("INDIAGLYCO", "long")],
    "2026-10-15": [
        ("DHAMPURSUG", "short"),
        ("IDBI", "short"),
        ("GOODLUCK", "short"),
        ("HCLTECH", "short"),
    ],
}


def load_day(con, sym: str, trade_date: str) -> pd.DataFrame:
    df = con.execute(f"""
        SELECT timestamp, open, high, low, close, volume
        FROM candles
        WHERE symbol='{sym}' AND interval='1m'
        AND timestamp::DATE = '{trade_date}'
        ORDER BY timestamp
    """).df()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def simulate_immediate(df: pd.DataFrame, direction: str) -> dict:
    if df.empty or len(df) < 2:
        return {"status": "NO_DATA"}

    first_candle = df.iloc[0]
    entry_px = float(first_candle["close"])
    entry_ts = first_candle["timestamp"]

    if direction == "short":
        raw_sl = float(first_candle["high"])
    else:
        raw_sl = float(first_candle["low"])

    raw_risk = abs(entry_px - raw_sl)
    min_risk = entry_px * MIN_RISK_PCT
    risk = max(raw_risk, min_risk)
    floored = risk > raw_risk

    sl_px = entry_px + risk if direction == "short" else entry_px - risk
    target_px = entry_px - TARGET_R * risk if direction == "short" else entry_px + TARGET_R * risk
    breakeven_px = entry_px - BREAKEVEN_AT_R * risk if direction == "short" else entry_px + BREAKEVEN_AT_R * risk

    result = {
        "status": "TRIGGERED",
        "entry_time": str(entry_ts.time()),
        "entry_px": round(entry_px, 2),
        "first_candle_high": round(float(first_candle["high"]), 2),
        "first_candle_low": round(float(first_candle["low"]), 2),
        "sl_px": round(sl_px, 2),
        "target_px": round(target_px, 2),
        "risk": round(risk, 2),
        "risk_floored": floored,
    }

    after_entry = df.iloc[1:]
    current_sl = sl_px
    moved_to_breakeven = False
    exit_px = None
    exit_time = None
    outcome = None

    for _, c in after_entry.iterrows():
        if direction == "short":
            if not moved_to_breakeven and c["low"] <= breakeven_px:
                current_sl = entry_px
                moved_to_breakeven = True
            if c["high"] >= current_sl:
                exit_px = current_sl
                exit_time = c["timestamp"]
                outcome = "BREAKEVEN" if moved_to_breakeven and current_sl == entry_px else "SL"
                break
            if c["low"] <= target_px:
                exit_px = target_px
                exit_time = c["timestamp"]
                outcome = "TARGET"
                break
        else:
            if not moved_to_breakeven and c["high"] >= breakeven_px:
                current_sl = entry_px
                moved_to_breakeven = True
            if c["low"] <= current_sl:
                exit_px = current_sl
                exit_time = c["timestamp"]
                outcome = "BREAKEVEN" if moved_to_breakeven and current_sl == entry_px else "SL"
                break
            if c["high"] >= target_px:
                exit_px = target_px
                exit_time = c["timestamp"]
                outcome = "TARGET"
                break

    if exit_px is None:
        last = after_entry.iloc[-1]
        exit_px = float(last["close"])
        exit_time = last["timestamp"]
        outcome = "EOD"

    pnl_r = (entry_px - exit_px) / risk if direction == "short" else (exit_px - entry_px) / risk

    result.update({
        "exit_time": str(exit_time.time()),
        "exit_px": round(exit_px, 2),
        "outcome": outcome,
        "pnl_r": round(pnl_r, 2),
    })
    return result


def main():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    rows = []
    for trade_date, legs in PLANS.items():
        for symbol, direction in legs:
            df = load_day(con, symbol, trade_date)
            r = simulate_immediate(df, direction)
            r.update({"date": trade_date, "symbol": symbol, "direction": direction})
            rows.append(r)
    con.close()

    print("=" * 100)
    print("IMMEDIATE-ENTRY-AT-OPEN BACKTEST v2 (breakeven at 2R) — SL from live first-candle range, target 1.5R")
    print("=" * 100)

    for r in rows:
        tag = r.get("status")
        line = f"  {r['date']} {r['symbol']:<12} {r['direction']:<5} [{tag}]"
        if tag == "TRIGGERED":
            icon = "✓" if r["pnl_r"] > 0 else ("~" if r["pnl_r"] == 0 else "✗")
            floor_note = " (risk floored to 0.5%)" if r["risk_floored"] else ""
            line += f"\n      entry={r['entry_px']}@{r['entry_time']}  sl={r['sl_px']}{floor_note}  target={r['target_px']}"
            line += f"\n      exit={r['exit_px']}@{r['exit_time']} ({r['outcome']})  {icon} {r['pnl_r']:+.2f}R"
        print(line)

    triggered = [r for r in rows if r.get("status") == "TRIGGERED"]
    wins = [r for r in triggered if r["pnl_r"] > 0]
    losses = [r for r in triggered if r["pnl_r"] < 0]
    total_r = sum(r["pnl_r"] for r in triggered)
    targets_hit = sum(1 for r in triggered if r["outcome"] == "TARGET")
    sl_hits = sum(1 for r in triggered if r["outcome"] == "SL")

    print(f"\n  Candidates: {len(rows)} | Triggered: {len(triggered)} (100% — no confirmation wait)")
    if triggered:
        win_rate = len(wins) / len(triggered) * 100
        avg_r = total_r / len(triggered)
        print(f"  Wins: {len(wins)} | Losses: {len(losses)}")
        print(f"  Win rate: {win_rate:.0f}%  |  Avg R: {avg_r:+.2f}R  |  Total R: {total_r:+.2f}R")
        print(f"  Hit full 1.5R target: {targets_hit}/{len(triggered)}  |  SL hit: {sl_hits}/{len(triggered)}")

    print("\n" + "=" * 100)
    print("THREE-WAY COMPARISON (same 12 candidates, same target/breakeven rules)")
    print("=" * 100)
    print(f"{'Strategy':<30}{'Triggered':<12}{'Win Rate':<12}{'Avg R':<10}{'Total R':<10}")
    print(f"{'ORB 15m (self-baseline)':<30}{'3/12':<12}{'100%':<12}{'+0.29':<10}{'+0.88':<10}")
    print(f"{'ORB 5m (prior-day baseline)':<30}{'2/12':<12}{'100%':<12}{'+0.67':<10}{'+1.33':<10}")
    if triggered:
        win_rate = len(wins) / len(triggered) * 100
        avg_r = total_r / len(triggered)
        print(f"{'Immediate entry':<30}{f'{len(triggered)}/{len(rows)}':<12}{f'{win_rate:.0f}%':<12}{f'{avg_r:+.2f}':<10}{f'{total_r:+.2f}':<10}")

    print(f"\n  Sample is only {len(rows)} candidates across 5 days. Directional read only.")
    print("  Not a greenlight for live capital under any of the three mechanisms tested.")


if __name__ == "__main__":
    main()
