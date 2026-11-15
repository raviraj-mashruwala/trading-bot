"""
Phase 1 of the Assignment: replay the REAL Tier1 deterministic screener across
many historical trading days to get a sample size large enough to validate
(or reject) the immediate-entry mechanism found in backtest_immediate_entry_v2.py.

This reuses the actual production factor-scoring code (candlestick.py,
volume_profile_score.py) and the actual production weights/thresholds from
tradingbot/core/config.py — not a reimplementation guess. Only the final
"which 3-5 names, which direction" step is approximated, because that step
is an LLM call in production (not cheaply replayable across 90 days).

IMPORTANT ASYMMETRY vs production: all 9 factor-score formulas in
tradingbot/analysis/pipeline.py discard sign (every score is "50 + abs(x)"),
because Tier1 only measures HOW INTERESTING a stock is, not which direction.
Direction is an LLM judgment downstream. Since we can't replay the LLM at
this scale, direction here is proxied by the SIGN of the stock's 5-day
return minus NIFTY's 5-day return (positive excess -> long bias, negative
-> short bias) — the same "relative strength vs NIFTY" reasoning that
appeared in the bias_reason examples in the design doc. This is a stated
approximation, not the real system's judgment — Phase 2 (re-running the
actual LLM on a subsample) is required before trusting this fully.

Known gaps vs production (documented, not hidden):
  - Universe = all symbols with day-interval data in candles.duckdb, not the
    live MIS-margin-eligible list for each historical date (no historical MIS
    list exists). Some selected symbols may not have actually been
    intraday-tradeable on that historical date.
  - delivery_pct factor defaults to 50.0 (neutral) — same fallback production
    uses when the NSE bhav-copy fetch is unavailable; no historical delivery
    data was pulled for 90 days.
  - sector is "unknown" for all symbols (Kite's instrument dump doesn't
    populate industry_type) — same as production's actual current state, so
    the correlation filter is a no-op here exactly as it is in production.
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb
import pandas as pd
import json

from tradingbot.screening.candlestick import score_patterns as score_candlestick
from tradingbot.screening.volume_profile_score import score_volume_profile

DB_PATH = Path(__file__).parent.parent / "candles.duckdb"

# Real production defaults for a 4L-capital account (tradingbot/core/config.py)
MIN_VOLUME = 500_000
MIN_PRICE = 50.0
MAX_PRICE = 5_000.0
MIN_TRADING_DAYS = 10
TOP_N_PER_DAY = 5

WEIGHTS = {
    "volume_surge": 15,
    "relative_strength": 15,
    "atr_expansion": 10,
    "price_structure": 15,
    "delivery_pct": 10,
    "sector_momentum": 10,
    "gap_analysis": 10,
    "candlestick_pattern": 10,
    "volume_profile": 5,
}
WEIGHT_NORM = sum(WEIGHTS.values())

START_DATE = date(2026, 6, 1)
END_DATE = date(2026, 10, 2)
# Exclude the week already tested in backtest_immediate_entry*.py to keep this
# an independent (if overlapping-universe) second look, not a re-measurement.
EXCLUDE_DATES = {date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7),
                  date(2026, 10, 8), date(2026, 10, 9)}

LOOKBACK_CALENDAR_DAYS = 40  # buffer to guarantee >=20 trading rows


def get_test_dates(con) -> list[date]:
    rows = con.execute(f"""
        SELECT DISTINCT timestamp::DATE AS d FROM candles
        WHERE symbol = 'NIFTY 50' AND interval = 'day'
        AND timestamp::DATE >= '{START_DATE}' AND timestamp::DATE <= '{END_DATE}'
        ORDER BY d
    """).df()
    dates = [d for d in rows["d"].tolist() if d not in EXCLUDE_DATES]
    return dates


def get_nifty_5d_returns(con) -> dict[date, float]:
    df = con.execute(f"""
        SELECT timestamp::DATE AS d, close FROM candles
        WHERE symbol = 'NIFTY 50' AND interval = 'day'
        ORDER BY d
    """).df()
    df["ret_5d"] = (df["close"] / df["close"].shift(5) - 1) * 100
    return dict(zip(df["d"], df["ret_5d"]))


def compute_factor_scores(df: pd.DataFrame, nifty_5d_change: float) -> dict | None:
    """Replicates tradingbot/analysis/pipeline.py:_build_stock_metrics_from_instruments
    factor-score formulas exactly, for one symbol's trailing window."""
    if df.empty or len(df) < 20:
        return None

    close = df["close"]
    volume = df["volume"]
    last_price = float(close.iloc[-1])
    avg_volume = float(volume.tail(20).mean())
    trading_days = len(df)

    high, low, prev_close_s = df["high"], df["low"], close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close_s).abs(), (low - prev_close_s).abs()],
        axis=1,
    ).max(axis=1)
    atr = float(true_range.tail(min(14, len(df))).mean())
    atr_pct = (atr / last_price * 100) if last_price > 0 else 0

    gap_score = 0.0
    if len(df) >= 2:
        prev_c = float(close.iloc[-2])
        today_open = float(df["open"].iloc[-1])
        if prev_c > 0:
            gap_pct = abs(today_open - prev_c) / prev_c * 100
            gap_score = min(100.0, gap_pct * 33.3)

    vol_today = float(volume.iloc[-1])
    vol_surge_pct = ((vol_today / avg_volume) - 1) * 100 if avg_volume > 0 else 0
    volume_surge_score = min(100.0, max(0.0, vol_surge_pct * 2))

    stock_5d_return = 0.0
    if len(close) >= 6:
        stock_5d_return = (float(close.iloc[-1]) / float(close.iloc[-6]) - 1) * 100
    rs_excess = stock_5d_return - nifty_5d_change
    relative_strength_score = min(100.0, max(0.0, 50.0 + abs(rs_excess) * 5.0))

    atr_expansion_score = min(100.0, max(0.0, atr_pct * 50.0))

    sma20 = float(close.tail(20).mean()) if len(close) >= 20 else last_price
    pct_above = ((last_price - sma20) / sma20 * 100) if sma20 > 0 else 0
    price_structure_score = min(100.0, max(0.0, 50.0 + abs(pct_above) * 5.0))

    market_cap_cr = last_price * avg_volume / 1_00_00_000

    factor_scores = {
        "gap_analysis": gap_score,
        "volume_surge": volume_surge_score,
        "relative_strength": relative_strength_score,
        "atr_expansion": atr_expansion_score,
        "price_structure": price_structure_score,
        "delivery_pct": 50.0,  # no historical delivery data — same fallback as production
        "candlestick_pattern": score_candlestick(df),
        "volume_profile": score_volume_profile(df),
        "sector_momentum": 50.0,  # all sectors "unknown" in this DB — matches production's actual state
    }
    composite = sum(factor_scores[k] * WEIGHTS[k] for k in WEIGHTS) / WEIGHT_NORM

    return {
        "last_price": last_price,
        "avg_volume": avg_volume,
        "trading_days": trading_days,
        "market_cap_cr": market_cap_cr,
        "composite_score": composite,
        "rs_excess": rs_excess,
        "factor_scores": factor_scores,
    }


def main():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    test_dates = get_test_dates(con)
    nifty_5d = get_nifty_5d_returns(con)

    print(f"Replaying Tier1 screener across {len(test_dates)} trading days "
          f"({test_dates[0]} to {test_dates[-1]})")

    all_candidates = []

    for i, d in enumerate(test_dates):
        window_start = d - timedelta(days=LOOKBACK_CALENDAR_DAYS)
        batch = con.execute(f"""
            SELECT symbol, timestamp, open, high, low, close, volume
            FROM candles
            WHERE interval = 'day'
            AND timestamp::DATE >= '{window_start}' AND timestamp::DATE < '{d}'
            AND symbol NOT IN ('NIFTY 50', 'INDIA VIX', 'NIFTY BANK')
            ORDER BY symbol, timestamp
        """).df()

        if batch.empty:
            continue

        nifty_5d_change = nifty_5d.get(d - timedelta(days=1))
        if nifty_5d_change is None or pd.isna(nifty_5d_change):
            # fall back to most recent available prior value
            prior_vals = [v for k, v in nifty_5d.items() if k < d and not pd.isna(v)]
            nifty_5d_change = prior_vals[-1] if prior_vals else 0.0

        scored = []
        for symbol, group in batch.groupby("symbol"):
            group = group.sort_values("timestamp").reset_index(drop=True)
            metrics = compute_factor_scores(group, nifty_5d_change)
            if metrics is None:
                continue
            # Liquidity filter (production ScreeningConfig defaults for 4L capital)
            if metrics["avg_volume"] < MIN_VOLUME:
                continue
            if not (MIN_PRICE <= metrics["last_price"] <= MAX_PRICE):
                continue
            if metrics["trading_days"] < MIN_TRADING_DAYS:
                continue
            scored.append({"symbol": symbol, **metrics})

        scored.sort(key=lambda s: s["composite_score"], reverse=True)
        top = scored[:TOP_N_PER_DAY]

        for s in top:
            direction = "long" if s["rs_excess"] >= 0 else "short"
            all_candidates.append({
                "date": str(d),
                "symbol": s["symbol"],
                "direction": direction,
                "composite_score": round(s["composite_score"], 2),
                "rs_excess": round(s["rs_excess"], 2),
                "last_price": round(s["last_price"], 2),
            })

        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(test_dates)} days processed, {len(all_candidates)} candidates so far")

    con.close()

    out_path = Path(__file__).parent / "output" / "tier1_replay_candidates.json"
    out_path.write_text(json.dumps(all_candidates, indent=2))

    print(f"\nDone. {len(all_candidates)} candidates across {len(test_dates)} days.")
    print(f"Saved to: {out_path}")

    longs = sum(1 for c in all_candidates if c["direction"] == "long")
    shorts = sum(1 for c in all_candidates if c["direction"] == "short")
    print(f"Direction split: {longs} long, {shorts} short")

    from collections import Counter
    sym_counts = Counter(c["symbol"] for c in all_candidates)
    print(f"Distinct symbols: {len(sym_counts)}")
    print(f"Top 10 most-selected: {sym_counts.most_common(10)}")


if __name__ == "__main__":
    main()
