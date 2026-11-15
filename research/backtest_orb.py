"""
ORB (Opening Range Breakout) backtest against existing historical trade plans.

Validates the NEW thesis from the design doc:
  "When overnight analysis flagged stock X with direction Y, how often did the
   following-day intraday ORB confirm the bias?"

NOT the old thesis (static EOD limit price fills).

For each plan leg (symbol + direction, taken as the overnight bias — EXACT
entry/SL prices from the old plans are ignored), simulate:
  1. Record opening range (OR) = high/low of first N minutes from 9:15.
  2. Wait for a 1m candle to CLOSE beyond the OR in the bias direction, with
     volume > 1.5x the average 1m volume during the OR window itself (proxy
     baseline — no reliable prior-day intraday average volume exists yet for
     most of these symbols).
  3. On trigger: entry = trigger candle close.
       SHORT: SL = OR_high + 0.5*(OR_high-OR_low) buffer
       LONG:  SL = OR_low  - 0.5*(OR_high-OR_low) buffer
     (OR range used as a volatility proxy instead of true ATR — no clean
     intraday ATR history exists for cold-started symbols.)
     Target = 1.5R. Move stop to breakeven once price reaches 1R.
  4. No trigger by valid_until (11:00) -> setup expired, no trade.

Runs both 15m and 30m OR windows for comparison.
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import time, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb
import pandas as pd

DB_PATH = Path(__file__).parent.parent / "candles.duckdb"

VALID_UNTIL = time(11, 0)
TARGET_R = 1.5
BREAKEVEN_AT_R = 1.0
VOLUME_MULT = 1.5

# Candidate list = plan legs, bias only (direction), prices ignored on purpose.
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


def simulate_orb(df: pd.DataFrame, direction: str, or_minutes: int) -> dict:
    if df.empty:
        return {"status": "NO_DATA"}

    day_start = df["timestamp"].iloc[0]
    or_cutoff = day_start + timedelta(minutes=or_minutes)
    valid_until_ts = pd.Timestamp.combine(day_start.date(), VALID_UNTIL)

    or_candles = df[df["timestamp"] < or_cutoff]
    if or_candles.empty:
        return {"status": "NO_OR_DATA"}

    or_high = float(or_candles["high"].max())
    or_low = float(or_candles["low"].min())
    or_range = or_high - or_low
    avg_or_volume = float(or_candles["volume"].mean())
    buffer = 0.5 * or_range

    after_or = df[(df["timestamp"] >= or_cutoff) & (df["timestamp"] <= valid_until_ts)]

    trigger = None
    for _, c in after_or.iterrows():
        vol_ok = c["volume"] > VOLUME_MULT * avg_or_volume
        if direction == "short" and c["close"] < or_low and vol_ok:
            trigger = c
            break
        if direction == "long" and c["close"] > or_high and vol_ok:
            trigger = c
            break

    result = {
        "or_high": round(or_high, 2),
        "or_low": round(or_low, 2),
        "or_range": round(or_range, 2),
        "avg_or_volume": round(avg_or_volume, 0),
    }

    if trigger is None:
        result["status"] = "SETUP_EXPIRED"
        return result

    entry_px = float(trigger["close"])
    entry_ts = trigger["timestamp"]

    if direction == "short":
        sl_px = or_high + buffer
    else:
        sl_px = or_low - buffer

    risk = abs(entry_px - sl_px)
    if risk <= 0:
        result["status"] = "DEGENERATE_RISK"
        return result

    target_px = entry_px - TARGET_R * risk if direction == "short" else entry_px + TARGET_R * risk
    breakeven_px = entry_px - BREAKEVEN_AT_R * risk if direction == "short" else entry_px + BREAKEVEN_AT_R * risk

    result.update({
        "status": "TRIGGERED",
        "entry_time": str(entry_ts.time()),
        "entry_px": round(entry_px, 2),
        "sl_px": round(sl_px, 2),
        "target_px": round(target_px, 2),
        "risk": round(risk, 2),
    })

    after_entry = df[df["timestamp"] >= entry_ts]
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
        # EOD forced exit
        last = after_entry.iloc[-1]
        exit_px = float(last["close"])
        exit_time = last["timestamp"]
        outcome = "EOD"

    if direction == "short":
        pnl_r = (entry_px - exit_px) / risk
    else:
        pnl_r = (exit_px - entry_px) / risk

    result.update({
        "exit_time": str(exit_time.time()),
        "exit_px": round(exit_px, 2),
        "outcome": outcome,
        "pnl_r": round(pnl_r, 2),
    })
    return result


def run_window(or_minutes: int) -> list[dict]:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    rows = []
    for trade_date, legs in PLANS.items():
        for symbol, direction in legs:
            df = load_day(con, symbol, trade_date)
            r = simulate_orb(df, direction, or_minutes)
            r.update({"date": trade_date, "symbol": symbol, "direction": direction, "or_minutes": or_minutes})
            rows.append(r)
    con.close()
    return rows


def summarize(rows: list[dict], or_minutes: int):
    print(f"\n{'='*90}")
    print(f"ORB BACKTEST — {or_minutes}m Opening Range Window")
    print(f"{'='*90}")

    total = len(rows)
    triggered = [r for r in rows if r.get("status") == "TRIGGERED"]
    expired = [r for r in rows if r.get("status") == "SETUP_EXPIRED"]
    no_data = [r for r in rows if r.get("status") in ("NO_DATA", "NO_OR_DATA", "DEGENERATE_RISK")]

    for r in rows:
        tag = r.get("status")
        line = f"  {r['date']} {r['symbol']:<12} {r['direction']:<5} [{tag}]"
        if tag == "TRIGGERED":
            icon = "✓" if r["pnl_r"] > 0 else ("~" if r["pnl_r"] == 0 else "✗")
            line += f"  entry={r['entry_px']}@{r['entry_time']}  exit={r['exit_px']}@{r['exit_time']} ({r['outcome']})  {icon} {r['pnl_r']:+.2f}R"
        print(line)

    wins = [r for r in triggered if r["pnl_r"] > 0]
    losses = [r for r in triggered if r["pnl_r"] < 0]
    breakeven = [r for r in triggered if r["pnl_r"] == 0]
    total_r = sum(r["pnl_r"] for r in triggered)

    print(f"\n  Candidates: {total} | Triggered: {len(triggered)} | Setup expired: {len(expired)} | No data: {len(no_data)}")
    if triggered:
        win_rate = len(wins) / len(triggered) * 100
        avg_r = total_r / len(triggered)
        print(f"  Wins: {len(wins)} | Losses: {len(losses)} | Breakeven: {len(breakeven)}")
        print(f"  Win rate: {win_rate:.0f}%  |  Avg R: {avg_r:+.2f}R  |  Total R: {total_r:+.2f}R")
        print(f"  Trigger rate: {len(triggered)/total*100:.0f}% of candidates actually fired")
    else:
        print("  No triggered setups to evaluate.")

    return {
        "or_minutes": or_minutes,
        "candidates": total,
        "triggered": len(triggered),
        "expired": len(expired),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(triggered) * 100) if triggered else 0,
        "avg_r": (total_r / len(triggered)) if triggered else 0,
        "total_r": total_r,
    }


def main():
    all_summaries = []
    for or_minutes in [15, 30]:
        rows = run_window(or_minutes)
        summary = summarize(rows, or_minutes)
        all_summaries.append(summary)

    print(f"\n{'='*90}")
    print("COMPARISON: 15m vs 30m Opening Range")
    print(f"{'='*90}")
    print(f"{'Window':<10}{'Candidates':<12}{'Triggered':<12}{'Win Rate':<12}{'Avg R':<10}{'Total R':<10}")
    for s in all_summaries:
        print(f"{s['or_minutes']}m{'':<7}{s['candidates']:<12}{s['triggered']:<12}{s['win_rate']:.0f}%{'':<8}{s['avg_r']:+.2f}{'':<5}{s['total_r']:+.2f}")

    print(f"\n{'='*90}")
    print("VALIDATION AGAINST SUCCESS CRITERIA (design doc)")
    print(f"{'='*90}")
    print("  Target: >=50% win rate AND >=1.5R average, across >=30 setups")
    for s in all_summaries:
        meets_n = s["triggered"] >= 30
        meets_wr = s["win_rate"] >= 50
        meets_r = s["avg_r"] >= 1.5
        verdict = "PASS" if (meets_n and meets_wr and meets_r) else "FAIL (sample too small / below target — directional read only)"
        print(f"  {s['or_minutes']}m window: n={s['triggered']} win_rate={s['win_rate']:.0f}% avg_r={s['avg_r']:+.2f}R -> {verdict}")

    print(f"\n  NOTE: This sample is only {sum(len(v) for v in PLANS.values())} candidates across 5 days.")
    print("  This is NOT statistically sufficient to greenlight live capital.")
    print("  It tells you whether the ORB mechanism is directionally sound on YOUR")
    print("  actual candidate-selection output before you invest in building it into")
    print("  the executor. Full validation needs the pipeline's FULL historical plan")
    print("  history (months), not just this one week of plans with populated legs.")


if __name__ == "__main__":
    main()
