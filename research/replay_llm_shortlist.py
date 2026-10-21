"""
Gate 0 (design doc): test whether the REAL LLM shortlist judgment has any
edge, since the crude RS-sign proxy tested in backtest_replay_holdout.py
failed hard on 435 candidates (18% win rate, -0.26R avg on holdout).

Runs the actual production Tier2Analyzer (real Claude calls: regime ->
sectors -> shortlist) against point-in-time-correct Tier1-scored candidates,
for a subset of historical days spread across the same tuning/holdout
windows used before. FII/DII net flows aren't available historically and
default to 0 (neutral) — the same fallback production uses when the live
NSE API is unavailable. Sector data is empty (all "unknown" sector in this
DB, same as production's actual current state).

This costs real Anthropic API calls (~3 per day x ~22 days = ~66 calls).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb
import pandas as pd

from tradingbot.screening.candlestick import score_patterns as score_candlestick
from tradingbot.screening.volume_profile_score import score_volume_profile
from tradingbot.core.config import LLMConfig
from tradingbot.core.llm.anthropic_provider import AnthropicProvider
from tradingbot.analysis.tier2_analyzer import Tier2Analyzer

DB_PATH = Path(__file__).parent.parent / "candles.duckdb"

env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

MIN_VOLUME = 500_000
MIN_PRICE = 50.0
MAX_PRICE = 5_000.0
MIN_TRADING_DAYS = 10
TOP_N_FOR_LLM = 50  # matches build_shortlist_user_prompt's scored_stocks[:50]

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
SAMPLE_EVERY_NTH = 4  # pick every 4th day within each window to spread LLM spend

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
    sample = tuning[::SAMPLE_EVERY_NTH] + holdout[::SAMPLE_EVERY_NTH]
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
        "gap_analysis": gap_score, "volume_surge": volume_surge_score,
        "relative_strength": relative_strength_score, "atr_expansion": atr_expansion_score,
        "price_structure": price_structure_score, "delivery_pct": 50.0,
        "candlestick_pattern": score_candlestick(df), "volume_profile": score_volume_profile(df),
        "sector_momentum": 50.0,
    }
    composite = sum(factor_scores[k] * WEIGHTS[k] for k in WEIGHTS) / WEIGHT_NORM

    return {
        "last_price": last_price, "avg_volume": avg_volume, "trading_days": trading_days,
        "market_cap_cr": market_cap_cr, "composite_score": composite,
        "factor_scores": factor_scores,
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


async def main():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    all_dates = get_test_dates(con)
    sample_dates = pick_sample_dates(all_dates)

    print(f"Sampling {len(sample_dates)} of {len(all_dates)} days for real-LLM replay "
          f"(spread across tuning + holdout windows)")

    nifty_df = get_index_series(con, "NIFTY 50")
    vix_df = get_index_series(con, "INDIA VIX")
    banknifty_df = get_index_series(con, "NIFTY BANK")

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not anthropic_key:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return

    llm_config = LLMConfig(provider="anthropic", model="claude-sonnet-4-6", timeout_sec=300, max_retries=3)
    provider = AnthropicProvider(llm_config, api_key=anthropic_key)
    tier2 = Tier2Analyzer(provider)

    all_picks = []
    total_cost = 0.0

    for i, d in enumerate(sample_dates):
        prior_nifty = nifty_df[nifty_df["d"] < d]
        prior_vix = vix_df[vix_df["d"] < d]
        prior_bn = banknifty_df[banknifty_df["d"] < d]

        if prior_nifty.empty or prior_vix.empty:
            print(f"  {d}: skipping, no prior index data")
            continue

        nifty_level = float(prior_nifty["close"].iloc[-1])
        nifty_5d_change = float(prior_nifty["ret_5d"].iloc[-1]) if not pd.isna(prior_nifty["ret_5d"].iloc[-1]) else 0.0
        vix = float(prior_vix["close"].iloc[-1])
        banknifty_level = float(prior_bn["close"].iloc[-1]) if not prior_bn.empty else 0.0

        scored_stocks = build_scored_stocks_for_day(con, d, nifty_5d_change)
        if not scored_stocks:
            print(f"  {d}: no scored stocks, skipping")
            continue

        try:
            regime = await tier2.analyze_regime(
                nifty=nifty_level, banknifty=banknifty_level, vix=vix,
                nifty_5d_change=nifty_5d_change, fii_5d_net=0.0, dii_5d_net=0.0,
                advance_decline=1.0, sector_data={},
            )
            if isinstance(regime.get("_usage"), object) and hasattr(regime.get("_usage"), "cost_usd"):
                total_cost += regime.pop("_usage").cost_usd()

            sectors = await tier2.analyze_sectors(regime, {}, {})
            if isinstance(sectors.get("_usage"), object) and hasattr(sectors.get("_usage"), "cost_usd"):
                total_cost += sectors.pop("_usage").cost_usd()

            shortlist_result = await tier2.shortlist(regime, sectors, scored_stocks)
            if isinstance(shortlist_result.get("_usage"), object) and hasattr(shortlist_result.get("_usage"), "cost_usd"):
                total_cost += shortlist_result.pop("_usage").cost_usd()

        except Exception as e:
            print(f"  {d}: LLM call failed: {e}")
            continue

        picks = shortlist_result.get("shortlist", [])
        for p in picks:
            all_picks.append({
                "date": str(d),
                "symbol": p["symbol"],
                "direction": p["direction"],
                "conviction": p.get("conviction"),
            })

        print(f"  [{i+1}/{len(sample_dates)}] {d}: regime={regime.get('regime')}, "
              f"{len(picks)} picks (cost so far: ${total_cost:.3f})")

    con.close()

    out_path = Path(__file__).parent / "output" / "llm_replay_candidates.json"
    out_path.write_text(json.dumps(all_picks, indent=2))

    print(f"\nDone. {len(all_picks)} real-LLM candidates across {len(sample_dates)} days.")
    print(f"Total estimated API cost: ${total_cost:.2f}")
    print(f"Saved to: {out_path}")

    longs = sum(1 for p in all_picks if p["direction"] == "long")
    shorts = sum(1 for p in all_picks if p["direction"] == "short")
    print(f"Direction split: {longs} long, {shorts} short")


if __name__ == "__main__":
    asyncio.run(main())
