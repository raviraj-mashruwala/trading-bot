"""
Gate 0, no-API-key variant: computes the same point-in-time Tier1 scored-stock
data and market context that scripts/replay_llm_shortlist.py would have sent
to the Anthropic API — but just prints it as a dossier instead of calling the
API. The acting agent (already a Claude model) reads the dossier and performs
the real shortlist judgment directly, using the SAME rubric as
tradingbot/analysis/prompts.py:SHORTLIST_SYSTEM, with no separate API billing.

No network calls. No API key needed. Pure local DB queries + the existing
production factor-scoring code.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb
import pandas as pd

from tradingbot.screening.candlestick import score_patterns as score_candlestick
from tradingbot.screening.volume_profile_score import score_volume_profile

DB_PATH = Path(__file__).parent.parent / "candles.duckdb"

MIN_VOLUME = 500_000
MIN_PRICE = 50.0
MAX_PRICE = 5_000.0
MIN_TRADING_DAYS = 10
TOP_N_FOR_LLM = 50

WEIGHTS = {
    "volume_surge": 15, "relative_strength": 15, "atr_expansion": 10,
    "price_structure": 15, "delivery_pct": 10, "sector_momentum": 10,
    "gap_analysis": 10, "candlestick_pattern": 10, "volume_profile": 5,
}
WEIGHT_NORM = sum(WEIGHTS.values())

START_DATE = date(2026, 6, 1)
END_DATE = date(2026, 10, 2)
EXCLUDE_DATES = {date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7),
                  date(2026, 10, 8), date(2026, 10, 9)}
TUNING_FRACTION = 0.6
SAMPLE_EVERY_NTH = 7  # fewer days than the API-call version — this is manual-reasoning cost, not $ cost

LOOKBACK_CALENDAR_DAYS = 40


def get_test_dates(con) -> list[date]:
    rows = con.execute(f"""
        SELECT DISTINCT timestamp::DATE AS d FROM candles
        WHERE symbol = 'NIFTY 50' AND interval = 'day'
        AND timestamp::DATE >= '{START_DATE}' AND timestamp::DATE <= '{END_DATE}'
        ORDER BY d
    """).df()
    dates = [pd.Timestamp(d).date() for d in rows["d"].tolist() if pd.Timestamp(d).date() not in EXCLUDE_DATES]
    return dates


def pick_sample_dates(all_dates: list[date]) -> list[date]:
    split_idx = int(len(all_dates) * TUNING_FRACTION)
    tuning = all_dates[:split_idx]
    holdout = all_dates[split_idx:]
    sample = [(d, "tuning") for d in tuning[::SAMPLE_EVERY_NTH]] + \
             [(d, "holdout") for d in holdout[::SAMPLE_EVERY_NTH]]
    return sample


def get_index_series(con, symbol: str) -> pd.DataFrame:
    df = con.execute(
        "SELECT timestamp::DATE AS d, close FROM candles WHERE symbol=? AND interval='day' ORDER BY d",
        [symbol],
    ).df()
    df["d"] = pd.to_datetime(df["d"]).dt.date
    df["ret_5d"] = (df["close"] / df["close"].shift(5) - 1) * 100
    return df


def compute_factor_scores(df: pd.DataFrame, nifty_5d_change: float) -> dict | None:
    if df.empty or len(df) < 20:
        return None
    close = df["close"]
    volume = df["volume"]
    last_price = float(close.iloc[-1])
    avg_volume = float(volume.tail(20).mean())
    trading_days = len(df)

    high, low, prev_close_s = df["high"], df["low"], close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close_s).abs(), (low - prev_close_s).abs()], axis=1,
    ).max(axis=1)
    atr = float(true_range.tail(min(14, len(df))).mean())
    atr_pct = (atr / last_price * 100) if last_price > 0 else 0

    gap_score = 0.0
    signed_gap_pct = 0.0
    if len(df) >= 2:
        prev_c = float(close.iloc[-2])
        today_open = float(df["open"].iloc[-1])
        if prev_c > 0:
            signed_gap_pct = (today_open - prev_c) / prev_c * 100
            gap_score = min(100.0, abs(signed_gap_pct) * 33.3)

    vol_today = float(volume.iloc[-1])
    vol_surge_pct = ((vol_today / avg_volume) - 1) * 100 if avg_volume > 0 else 0
    volume_surge_score = min(100.0, max(0.0, vol_surge_pct * 2))

    stock_5d_return = 0.0
    if len(close) >= 6:
        stock_5d_return = (float(close.iloc[-1]) / float(close.iloc[-6]) - 1) * 100
    rs_excess = stock_5d_return - nifty_5d_change
    relative_strength_score = min(100.0, max(0.0, 50.0 + abs(rs_excess) * 5.0))

    # Recalibrated: original *50.0 saturated at atr_pct=2%, which sat BELOW the
    # 10th percentile of this universe's actual ATR% distribution (median ~4%,
    # p90 ~6.3%) — contributed zero signal for 96% of candidates. *15.87
    # saturates at ~6.3% (p90), matching the saturation rate of other factors
    # (price_structure 14%, relative_strength 12%). See design doc Gate-0
    # saturation diagnostic.
    atr_expansion_score = min(100.0, max(0.0, atr_pct * 15.87))

    sma20 = float(close.tail(20).mean()) if len(close) >= 20 else last_price
    pct_above = ((last_price - sma20) / sma20 * 100) if sma20 > 0 else 0
    price_structure_score = min(100.0, max(0.0, 50.0 + abs(pct_above) * 5.0))

    market_cap_cr = last_price * avg_volume / 1_00_00_000

    factor_scores = {
        "gap_analysis": gap_score, "volume_surge": volume_surge_score,
        "relative_strength": relative_strength_score, "atr_expansion": atr_expansion_score,
        "price_structure": price_structure_score, "delivery_pct": 50.0,
        "candlestick_pattern": score_candlestick(df), "volume_profile": score_volume_profile(df),
        "sector_momentum": 50.0,
    }
    composite = sum(factor_scores[k] * WEIGHTS[k] for k in WEIGHTS) / WEIGHT_NORM

    # Keep signed versions too — for MY OWN reasoning (not sent to a scripted
    # API call), so I can actually judge direction instead of re-deriving it
    # from a proxy. The real LLM prompt doesn't get these signed values either
    # (production has the same limitation) but since I'm doing the judgment
    # myself with DB access, there's no reason to blind myself the same way.
    return {
        "last_price": last_price, "avg_volume": avg_volume, "trading_days": trading_days,
        "market_cap_cr": market_cap_cr, "composite_score": composite,
        "factor_scores": factor_scores,
        "_signed_gap_pct": signed_gap_pct,
        "_signed_rs_excess": rs_excess,
        "_signed_pct_above_sma20": pct_above,
    }


def build_scored_stocks_for_day(con, d: date, nifty_5d_change: float) -> list[dict]:
    window_start = d - timedelta(days=LOOKBACK_CALENDAR_DAYS)
    batch = con.execute("""
        SELECT symbol, timestamp, open, high, low, close, volume
        FROM candles
        WHERE interval = 'day'
        AND timestamp::DATE >= ? AND timestamp::DATE < ?
        AND symbol NOT IN ('NIFTY 50', 'INDIA VIX', 'NIFTY BANK')
        ORDER BY symbol, timestamp
    """, [str(window_start), str(d)]).df()
    if batch.empty:
        return []

    scored = []
    for symbol, group in batch.groupby("symbol"):
        group = group.sort_values("timestamp").reset_index(drop=True)
        metrics = compute_factor_scores(group, nifty_5d_change)
        if metrics is None:
            continue
        if metrics["avg_volume"] < MIN_VOLUME:
            continue
        if not (MIN_PRICE <= metrics["last_price"] <= MAX_PRICE):
            continue
        if metrics["trading_days"] < MIN_TRADING_DAYS:
            continue
        scored.append({"symbol": symbol, "sector": "unknown", **metrics})

    scored.sort(key=lambda s: s["composite_score"], reverse=True)
    return scored[:TOP_N_FOR_LLM]


def main():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    all_dates = get_test_dates(con)
    sample = pick_sample_dates(all_dates)

    nifty_df = get_index_series(con, "NIFTY 50")
    vix_df = get_index_series(con, "INDIA VIX")
    banknifty_df = get_index_series(con, "NIFTY BANK")

    dossiers = []
    for d, split in sample:
        prior_nifty = nifty_df[nifty_df["d"] < d]
        prior_vix = vix_df[vix_df["d"] < d]
        prior_bn = banknifty_df[banknifty_df["d"] < d]
        if prior_nifty.empty or prior_vix.empty:
            continue

        nifty_level = float(prior_nifty["close"].iloc[-1])
        nifty_5d_change = float(prior_nifty["ret_5d"].iloc[-1]) if not pd.isna(prior_nifty["ret_5d"].iloc[-1]) else 0.0
        vix = float(prior_vix["close"].iloc[-1])
        banknifty_level = float(prior_bn["close"].iloc[-1]) if not prior_bn.empty else 0.0

        scored_stocks = build_scored_stocks_for_day(con, d, nifty_5d_change)
        if not scored_stocks:
            continue

        dossiers.append({
            "date": str(d),
            "split": split,
            "market_context": {
                "nifty_level": round(nifty_level, 0),
                "nifty_5d_change_pct": round(nifty_5d_change, 2),
                "vix": round(vix, 1),
                "banknifty_level": round(banknifty_level, 0),
            },
            "candidates": [
                {
                    "symbol": s["symbol"],
                    "last_price": round(s["last_price"], 2),
                    "composite_score": round(s["composite_score"], 1),
                    "factor_scores": {k: round(v, 1) for k, v in s["factor_scores"].items()},
                    "signed_gap_pct": round(s["_signed_gap_pct"], 2),
                    "signed_rs_excess": round(s["_signed_rs_excess"], 2),
                    "signed_pct_above_sma20": round(s["_signed_pct_above_sma20"], 2),
                }
                for s in scored_stocks[:25]  # top 25 per day keeps this reviewable
            ],
        })

    con.close()

    out_path = Path(__file__).parent / "output" / "llm_dossiers.json"
    out_path.write_text(json.dumps(dossiers, indent=2))

    print(f"Prepared {len(dossiers)} day dossiers (top 25 candidates each, no API calls made).")
    print(f"Saved to: {out_path}")
    for dd in dossiers:
        print(f"  {dd['date']} ({dd['split']}): nifty_5d={dd['market_context']['nifty_5d_change_pct']:+.1f}%, "
              f"vix={dd['market_context']['vix']}, {len(dd['candidates'])} candidates")


if __name__ == "__main__":
    main()
