"""
ORB backtest v2 — fixes the volume-baseline flaw found in v1.

v1 finding: using the OR window's own average volume as the baseline is
self-poisoning. On crash days the big move happens INSIDE the opening range,
inflating the baseline so a genuine post-OR breakout almost never clears
1.5x of an already-elevated number. Result: real movers got skipped
("setup expired"), only weak EOD drift got captured (avg R 0.2-0.3, 0% hit
the 1.5R target).

v2 changes:
  1. OR window shrunk to 5 minutes (9:15-9:19) so entries fire closer to
     where the real move starts.
  2. Volume baseline = this symbol's OWN average 1m volume during the SAME
     9:15-9:19 clock window on the prior N trading days (not today's window).
     This is immune to today's crash inflating today's own baseline.
  3. Everything else (SL = OR range buffer, target 1.5R, breakeven at 1R,
     valid_until 11:00) unchanged from v1 for a clean comparison.
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import time, timedelta, date

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb
import pandas as pd

DB_PATH = Path(__file__).parent.parent / "candles.duckdb"

OR_MINUTES = 5
BASELINE_LOOKBACK_DAYS = 10
VALID_UNTIL = time(11, 0)
TARGET_R = 1.5
BREAKEVEN_AT_R = 1.0
VOLUME_MULT = 1.5

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


def prior_day_window_baseline(con, sym: str, trade_date: str, or_minutes: int) -> tuple[float, int]:
    """Avg total volume during 9:15-9:(15+or_minutes) over the last N trading
    days strictly before trade_date. Returns (avg_volume, days_used)."""
    td = date.fromisoformat(trade_date)
    end_minute = 15 + or_minutes
    rows = con.execute(f"""
        SELECT timestamp::DATE AS d, SUM(volume) AS vol
        FROM candles
        WHERE symbol = '{sym}' AND interval = '1m'
        AND timestamp::DATE < '{trade_date}'
        AND (timestamp::TIME >= TIME '09:15:00' AND timestamp::TIME < TIME '09:{end_minute:02d}:00')
        GROUP BY d
        ORDER BY d DESC
        LIMIT {BASELINE_LOOKBACK_DAYS}
    """).df()
    if rows.empty:
        return (0.0, 0)
    return (float(rows["vol"].mean()), len(rows))


def simulate_orb_v2(con, sym: str, df: pd.DataFrame, direction: str, trade_date: str) -> dict:
    if df.empty:
        return {"status": "NO_DATA"}

    day_start = df["timestamp"].iloc[0]
    or_cutoff = day_start + timedelta(minutes=OR_MINUTES)
    valid_until_ts = pd.Timestamp.combine(day_start.date(), VALID_UNTIL)

    or_candles = df[df["timestamp"] < or_cutoff]
    if or_candles.empty:
        return {"status": "NO_OR_DATA"}

    or_high = float(or_candles["high"].max())
    or_low = float(or_candles["low"].min())
    or_range = or_high - or_low
    buffer = 0.5 * or_range

    baseline_vol, baseline_days = prior_day_window_baseline(con, sym, trade_date, OR_MINUTES)

    result = {
        "or_high": round(or_high, 2),
        "or_low": round(or_low, 2),
        "or_range": round(or_range, 2),
        "baseline_vol": round(baseline_vol, 0),
        "baseline_days": baseline_days,
    }

    if baseline_days < 3:
        result["status"] = "NO_BASELINE"
        return result

    after_or = df[(df["timestamp"] >= or_cutoff) & (df["timestamp"] <= valid_until_ts)]

    trigger = None
    for _, c in after_or.iterrows():
        vol_ok = c["volume"] > VOLUME_MULT * baseline_vol
        if direction == "short" and c["close"] < or_low and vol_ok:
            trigger = c
            break
        if direction == "long" and c["close"] > or_high and vol_ok:
            trigger = c
            break

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
        "trigger_volume": int(trigger["volume"]),
        "volume_ratio": round(trigger["volume"] / baseline_vol, 2) if baseline_vol else None,
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
            r = simulate_orb_v2(con, symbol, df, direction, trade_date)
            r.update({"date": trade_date, "symbol": symbol, "direction": direction})
            rows.append(r)
    con.close()

    print("=" * 100)
    print(f"ORB BACKTEST v2 — {OR_MINUTES}m window, prior-day same-clock-window volume baseline ({BASELINE_LOOKBACK_DAYS}d lookback)")
    print("=" * 100)

    for r in rows:
        tag = r.get("status")
        line = f"  {r['date']} {r['symbol']:<12} {r['direction']:<5} [{tag}]"
        if "baseline_vol" in r:
            line += f"  OR=[{r.get('or_low')}-{r.get('or_high')}] baseline_vol={r['baseline_vol']:,.0f} ({r['baseline_days']}d)"
        if tag == "TRIGGERED":
            icon = "✓" if r["pnl_r"] > 0 else ("~" if r["pnl_r"] == 0 else "✗")
            line += f"\n      entry={r['entry_px']}@{r['entry_time']} (vol={r['trigger_volume']:,}, {r['volume_ratio']}x baseline)  exit={r['exit_px']}@{r['exit_time']} ({r['outcome']})  {icon} {r['pnl_r']:+.2f}R"
        print(line)

    triggered = [r for r in rows if r.get("status") == "TRIGGERED"]
    expired = [r for r in rows if r.get("status") == "SETUP_EXPIRED"]
    no_baseline = [r for r in rows if r.get("status") == "NO_BASELINE"]

    wins = [r for r in triggered if r["pnl_r"] > 0]
    losses = [r for r in triggered if r["pnl_r"] < 0]
    total_r = sum(r["pnl_r"] for r in triggered)

    print(f"\n  Candidates: {len(rows)} | Triggered: {len(triggered)} | Setup expired: {len(expired)} | No baseline: {len(no_baseline)}")
    if triggered:
        win_rate = len(wins) / len(triggered) * 100
        avg_r = total_r / len(triggered)
        targets_hit = sum(1 for r in triggered if r["outcome"] == "TARGET")
        print(f"  Wins: {len(wins)} | Losses: {len(losses)}")
        print(f"  Win rate: {win_rate:.0f}%  |  Avg R: {avg_r:+.2f}R  |  Total R: {total_r:+.2f}R")
        print(f"  Hit full 1.5R target: {targets_hit}/{len(triggered)}")
        print(f"  Trigger rate: {len(triggered)/len(rows)*100:.0f}% of candidates fired")
    else:
        print("  No triggered setups.")

    print("\n" + "=" * 100)
    print("VALIDATION AGAINST SUCCESS CRITERIA")
    print("=" * 100)
    print("  Target: >=50% win rate AND >=1.5R average, across >=30 setups")
    if triggered:
        win_rate = len(wins) / len(triggered) * 100
        avg_r = total_r / len(triggered)
        meets = len(triggered) >= 30 and win_rate >= 50 and avg_r >= 1.5
        print(f"  n={len(triggered)} win_rate={win_rate:.0f}% avg_r={avg_r:+.2f}R -> {'PASS' if meets else 'FAIL (sample too small for a verdict either way — directional read only)'}")
    print(f"\n  Sample is only {len(rows)} candidates across 5 days. Directional read only,")
    print("  not a greenlight for live capital regardless of outcome.")


if __name__ == "__main__":
    main()
