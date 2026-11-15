"""
Analyze all trade plans against actual intraday data.
Downloads missing 1m/5m data, then checks if entries were hit,
computes indicators, and shows P&L outcome for each leg.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb
import pandas as pd
import numpy as np

# Load env
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

KITE_API_KEY = os.environ.get("KITE_API_KEY", "")
DB_PATH = Path(__file__).parent.parent / "candles.duckdb"
TOKEN_PATH = Path.home() / ".tradingbot" / "kite_token"

TRADE_PLANS = {
    "2026-10-08": [
        {"symbol": "NELCAST", "direction": "short", "entry": 149.37, "sl": 151.948, "entry_type": "limit"},
        {"symbol": "GLAND",   "direction": "short", "entry": 3154.2, "sl": 3172.5,  "entry_type": "limit"},
    ],
    "2026-10-09": [
        {"symbol": "ADANIENT",   "direction": "short", "entry": 2580.0, "sl": 2592.43, "entry_type": "limit"},
        {"symbol": "INDIAGLYCO", "direction": "short", "entry": 354.18, "sl": 356.95,  "entry_type": "limit"},
    ],
    "2026-10-12": [
        {"symbol": "KEC",        "direction": "short", "entry": 370.75, "sl": 374.86, "entry_type": "limit"},
        {"symbol": "SHANTIGOLD", "direction": "long",  "entry": 380.23, "sl": 376.05, "entry_type": "limit"},
    ],
    "2026-10-14": [
        {"symbol": "GOODLUCK",   "direction": "long", "entry": 148.4,  "sl": 147.6,  "entry_type": "limit"},
        {"symbol": "INDIAGLYCO", "direction": "long", "entry": 354.18, "sl": 351.4,  "entry_type": "limit"},
    ],
    "2026-10-15": [
        {"symbol": "DHAMPURSUG", "direction": "short", "entry": 206.1,  "sl": 207.05, "entry_type": "limit"},
        {"symbol": "IDBI",       "direction": "short", "entry": 90.25,  "sl": 91.1,   "entry_type": "limit"},
        {"symbol": "GOODLUCK",   "direction": "short", "entry": 594.57, "sl": 601.15, "entry_type": "limit"},
        {"symbol": "HCLTECH",    "direction": "short", "entry": 1330.0, "sl": 1335.0, "entry_type": "limit"},
    ],
}


# ── Indicators ────────────────────────────────────────────────────────────────

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # EMA 9, 21
    df["ema9"]  = df["close"].ewm(span=9,  adjust=False).mean()
    df["ema21"] = df["close"].ewm(span=21, adjust=False).mean()
    # RSI 14
    delta = df["close"].diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    df["rsi14"] = 100 - (100 / (1 + rs))
    # VWAP (reset per day)
    df["date"] = df["timestamp"].dt.date
    df["typical"] = (df["high"] + df["low"] + df["close"]) / 3
    df["tpv"] = df["typical"] * df["volume"]
    df["cum_tpv"] = df.groupby("date")["tpv"].cumsum()
    df["cum_vol"] = df.groupby("date")["volume"].cumsum()
    df["vwap"] = df["cum_tpv"] / df["cum_vol"]
    # ATR 14
    df["tr"] = np.maximum(
        df["high"] - df["low"],
        np.maximum(
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"]  - df["close"].shift(1)).abs(),
        )
    )
    df["atr14"] = df["tr"].ewm(span=14, adjust=False).mean()
    return df


# ── Data check / fetch ─────────────────────────────────────────────────────────

def check_missing() -> dict[str, list[str]]:
    """Return {symbol: [intervals_missing]} for each needed symbol/date."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    missing: dict[str, list[str]] = {}
    for trade_date, legs in TRADE_PLANS.items():
        for leg in legs:
            sym = leg["symbol"]
            for interval in ["1m", "5m"]:
                cnt = con.execute(f"""
                    SELECT COUNT(*) FROM candles
                    WHERE symbol='{sym}' AND interval='{interval}'
                    AND timestamp::DATE = '{trade_date}'
                """).fetchone()[0]
                if cnt == 0:
                    key = f"{sym}||{interval}"
                    if key not in missing:
                        missing[key] = []
                    missing[key].append(trade_date)
    con.close()
    return missing


async def fetch_missing_data():
    """Fetch all missing intraday data via Kite."""
    missing = check_missing()
    if not missing:
        print("All intraday data already present.")
        return

    print(f"\nMissing data for {len(missing)} symbol/interval combos. Fetching from Kite...\n")

    if not KITE_API_KEY:
        print("ERROR: KITE_API_KEY not set.")
        return
    if not TOKEN_PATH.exists():
        print("ERROR: No kite token found at ~/.tradingbot/kite_token")
        return

    try:
        from kiteconnect import KiteConnect
    except ImportError:
        print("ERROR: kiteconnect not installed.")
        return

    from tradingbot.data.kite_client import KiteClient
    from tradingbot.data.candle_store import CandleStore
    from tradingbot.data.instrument_cache import InstrumentCache
    from tradingbot.data.kite_data_sync import KiteDataSync, INTERVAL_MAP, KITE_LIMITS, _date_chunks, _kite_rows_to_df

    kite = KiteConnect(api_key=KITE_API_KEY)
    kite.set_access_token(TOKEN_PATH.read_text().strip())
    kite_client = KiteClient(kite)
    store = CandleStore(DB_PATH)
    instruments_db = Path(__file__).parent.parent / "instruments.db"
    instruments_cache = InstrumentCache(instruments_db)

    # Refresh instruments
    print("Refreshing instrument cache...")
    try:
        raw = await asyncio.to_thread(kite_client.fetch_instruments, "NSE")
        instruments_cache.refresh(raw)
        print(f"  {len(raw)} instruments loaded")
    except Exception as e:
        print(f"  Instrument refresh failed: {e}")
        return

    # Group by symbol → intervals → dates
    by_sym: dict[str, dict[str, list[str]]] = {}
    for key, dates in missing.items():
        sym, interval = key.split("||")
        by_sym.setdefault(sym, {}).setdefault(interval, []).extend(dates)

    for sym, intervals in by_sym.items():
        for interval, dates in intervals.items():
            kite_interval = INTERVAL_MAP[interval]
            max_days = KITE_LIMITS[kite_interval]
            sorted_dates = sorted(set(dates))
            from_date = date.fromisoformat(sorted_dates[0])
            to_date   = date.fromisoformat(sorted_dates[-1]) + timedelta(days=1)

            print(f"Fetching {sym} {interval}: {from_date} → {to_date}")
            chunks = _date_chunks(from_date, to_date, max_days)
            total = 0
            for cf, ct in chunks:
                try:
                    token = instruments_cache.get_token(sym)
                    raw = await asyncio.to_thread(
                        kite_client.fetch_historical, token, kite_interval, cf, ct
                    )
                    df = _kite_rows_to_df(raw)
                    written = await asyncio.to_thread(store.write, sym, interval, df)
                    total += written
                    print(f"  chunk {cf}→{ct}: {written} rows")
                    await asyncio.sleep(0.5)
                except Exception as e:
                    print(f"  FAILED {cf}→{ct}: {e}")
            print(f"  Total: {total} rows written for {sym}/{interval}\n")


# ── Analysis ──────────────────────────────────────────────────────────────────

def load_day_candles(sym: str, trade_date: str, interval: str) -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    df = con.execute(f"""
        SELECT timestamp, open, high, low, close, volume
        FROM candles
        WHERE symbol='{sym}' AND interval='{interval}'
        AND timestamp::DATE = '{trade_date}'
        ORDER BY timestamp
    """).df()
    con.close()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def analyze_leg(leg: dict, trade_date: str) -> dict:
    sym       = leg["symbol"]
    direction = leg["direction"]
    entry_px  = leg["entry"]
    sl_px     = leg["sl"]
    risk      = abs(entry_px - sl_px)
    r1        = entry_px + risk if direction == "long" else entry_px - risk   # 1R target
    r2        = entry_px + 2*risk if direction == "long" else entry_px - 2*risk  # 2R target
    r3        = entry_px + 3*risk if direction == "long" else entry_px - 3*risk  # 3R target

    result: dict = {
        "symbol": sym,
        "date": trade_date,
        "direction": direction,
        "entry_px": entry_px,
        "sl_px": sl_px,
        "risk": round(risk, 2),
        "r1": round(r1, 2),
        "r2": round(r2, 2),
        "r3": round(r3, 2),
    }

    # Load 1m and 5m
    df1m = load_day_candles(sym, trade_date, "1m")
    df5m = load_day_candles(sym, trade_date, "5m")

    if df1m.empty:
        result["status"] = "NO_DATA"
        return result

    df1m_ind = add_indicators(df1m)
    df5m_ind = add_indicators(df5m) if not df5m.empty else None

    # Day open, high, low, close
    result["day_open"]  = round(float(df1m["open"].iloc[0]), 2)
    result["day_high"]  = round(float(df1m["high"].max()), 2)
    result["day_low"]   = round(float(df1m["low"].min()), 2)
    result["day_close"] = round(float(df1m["close"].iloc[-1]), 2)

    # Market open first 5 candles (9:15-9:19)
    open_candles = df1m[df1m["timestamp"].dt.hour == 9]
    open_candles = open_candles[open_candles["timestamp"].dt.minute < 20]
    if not open_candles.empty:
        result["open_range_high"] = round(float(open_candles["high"].max()), 2)
        result["open_range_low"]  = round(float(open_candles["low"].min()), 2)

    # Was entry price touched? For limit entry:
    #   long:  entry is hit if day_low <= entry_px (price came down to limit)
    #   short: entry is hit if day_high >= entry_px (price came up to limit)
    if direction == "long":
        entry_hit = df1m["low"].min() <= entry_px
    else:
        entry_hit = df1m["high"].max() >= entry_px

    result["entry_hit"] = entry_hit

    if not entry_hit:
        result["status"] = "ENTRY_NOT_HIT"
        result["note"] = f"Price never reached {entry_px}. Day range: {result['day_low']}–{result['day_high']}"
        return result

    # Find first candle where entry was hit
    if direction == "long":
        entry_candles = df1m[df1m["low"] <= entry_px]
    else:
        entry_candles = df1m[df1m["high"] >= entry_px]

    if entry_candles.empty:
        result["status"] = "ENTRY_NOT_HIT"
        return result

    first_entry = entry_candles.iloc[0]
    result["entry_time"] = str(first_entry["timestamp"].time())
    result["entry_candle_open"]  = round(float(first_entry["open"]), 2)
    result["entry_candle_high"]  = round(float(first_entry["high"]), 2)
    result["entry_candle_low"]   = round(float(first_entry["low"]), 2)
    result["entry_candle_close"] = round(float(first_entry["close"]), 2)

    # Indicators at entry time
    entry_row = df1m_ind[df1m_ind["timestamp"] == first_entry["timestamp"]]
    if not entry_row.empty:
        result["rsi_at_entry"]  = round(float(entry_row["rsi14"].iloc[0]), 1)
        result["vwap_at_entry"] = round(float(entry_row["vwap"].iloc[0]), 2)
        result["ema9_at_entry"] = round(float(entry_row["ema9"].iloc[0]), 2)
        result["ema21_at_entry"]= round(float(entry_row["ema21"].iloc[0]), 2)
        result["atr_at_entry"]  = round(float(entry_row["atr14"].iloc[0]), 2)

        vwap = float(entry_row["vwap"].iloc[0])
        ema9 = float(entry_row["ema9"].iloc[0])
        ema21 = float(entry_row["ema21"].iloc[0])
        rsi  = float(entry_row["rsi14"].iloc[0])

        # Signal alignment check
        signals = []
        if direction == "short":
            if entry_px < vwap:  signals.append("price<VWAP ✓")
            else: signals.append("price>VWAP ✗")
            if ema9 < ema21: signals.append("EMA9<EMA21 ✓")
            else: signals.append("EMA9>EMA21 ✗")
            if rsi < 50: signals.append(f"RSI={rsi:.0f}<50 ✓")
            else: signals.append(f"RSI={rsi:.0f}>50 ✗")
        else:
            if entry_px > vwap: signals.append("price>VWAP ✓")
            else: signals.append("price<VWAP ✗")
            if ema9 > ema21: signals.append("EMA9>EMA21 ✓")
            else: signals.append("EMA9<EMA21 ✗")
            if rsi > 50: signals.append(f"RSI={rsi:.0f}>50 ✓")
            else: signals.append(f"RSI={rsi:.0f}<50 ✗")
        result["signal_alignment"] = " | ".join(signals)

    # After entry: trace 1m candles to find SL hit or target hit
    after_entry = df1m[df1m["timestamp"] >= first_entry["timestamp"]].copy()

    sl_hit    = None
    r1_hit    = None
    r2_hit    = None
    r3_hit    = None
    exit_time = None
    exit_px   = None
    outcome   = None

    for _, c in after_entry.iterrows():
        if direction == "short":
            # SL = price goes above sl_px
            if sl_hit is None and c["high"] >= sl_px:
                sl_hit = c["timestamp"]
            # targets = price goes below target levels
            if r1_hit is None and c["low"] <= r1:
                r1_hit = c["timestamp"]
            if r2_hit is None and c["low"] <= r2:
                r2_hit = c["timestamp"]
            if r3_hit is None and c["low"] <= r3:
                r3_hit = c["timestamp"]
        else:
            if sl_hit is None and c["low"] <= sl_px:
                sl_hit = c["timestamp"]
            if r1_hit is None and c["high"] >= r1:
                r1_hit = c["timestamp"]
            if r2_hit is None and c["high"] >= r2:
                r2_hit = c["timestamp"]
            if r3_hit is None and c["high"] >= r3:
                r3_hit = c["timestamp"]

    # Determine outcome
    if sl_hit and (r1_hit is None or sl_hit <= r1_hit):
        outcome = "SL_HIT"
        exit_time = str(sl_hit.time()) if hasattr(sl_hit, "time") else str(sl_hit)
        exit_px   = sl_px
        result["pnl_r"] = -1.0
    elif r3_hit:
        outcome = "3R"
        exit_time = str(r3_hit.time()) if hasattr(r3_hit, "time") else str(r3_hit)
        exit_px   = r3
        result["pnl_r"] = 3.0
    elif r2_hit:
        outcome = "2R"
        exit_time = str(r2_hit.time()) if hasattr(r2_hit, "time") else str(r2_hit)
        exit_px   = r2
        result["pnl_r"] = 2.0
    elif r1_hit:
        outcome = "1R"
        exit_time = str(r1_hit.time()) if hasattr(r1_hit, "time") else str(r1_hit)
        exit_px   = r1
        result["pnl_r"] = 1.0
    else:
        # Forced exit at close
        outcome = "EOD_EXIT"
        last_close = float(after_entry["close"].iloc[-1])
        exit_time  = str(after_entry["timestamp"].iloc[-1].time())
        exit_px    = last_close
        if direction == "short":
            result["pnl_r"] = round((entry_px - last_close) / risk, 2) if risk else 0
        else:
            result["pnl_r"] = round((last_close - entry_px) / risk, 2) if risk else 0

    result["outcome"]    = outcome
    result["exit_time"]  = exit_time
    result["exit_px"]    = round(exit_px, 2) if exit_px else None
    result["sl_hit_time"]= str(sl_hit.time()) if sl_hit and hasattr(sl_hit, "time") else str(sl_hit) if sl_hit else None
    result["r1_hit_time"]= str(r1_hit.time()) if r1_hit and hasattr(r1_hit, "time") else str(r1_hit) if r1_hit else None
    result["r2_hit_time"]= str(r2_hit.time()) if r2_hit and hasattr(r2_hit, "time") else str(r2_hit) if r2_hit else None
    result["r3_hit_time"]= str(r3_hit.time()) if r3_hit and hasattr(r3_hit, "time") else str(r3_hit) if r3_hit else None

    result["status"] = "ANALYZED"

    # 5m context at entry
    if df5m_ind is not None and not df5m_ind.empty:
        entry_ts = first_entry["timestamp"]
        close_5m = df5m_ind[df5m_ind["timestamp"] <= entry_ts]
        if not close_5m.empty:
            row5 = close_5m.iloc[-1]
            result["5m_rsi_at_entry"]  = round(float(row5["rsi14"]), 1)
            result["5m_ema9_at_entry"] = round(float(row5["ema9"]), 2)
            result["5m_ema21_at_entry"]= round(float(row5["ema21"]), 2)
            result["5m_vwap_at_entry"] = round(float(row5["vwap"]), 2)

    return result


def print_results(results: list[dict]):
    """Pretty-print analysis."""
    total_r   = 0.0
    analyzed  = 0

    print("\n" + "="*90)
    print("TRADE PLAN ANALYSIS — ENTRY SIMULATION vs ACTUAL INTRADAY DATA")
    print("="*90)

    by_date: dict[str, list[dict]] = {}
    for r in results:
        by_date.setdefault(r["date"], []).append(r)

    for d in sorted(by_date):
        legs = by_date[d]
        print(f"\n{'─'*90}")
        print(f"  DATE: {d}")
        print(f"{'─'*90}")
        for r in legs:
            print(f"\n  [{r['direction'].upper()}] {r['symbol']}  entry={r['entry_px']}  sl={r['sl_px']}  risk={r['risk']}")
            print(f"  Targets: 1R={r['r1']}  2R={r['r2']}  3R={r['r3']}")

            if r.get("status") == "NO_DATA":
                print("  ⚠  NO INTRADAY DATA AVAILABLE")
                continue

            print(f"  Day: open={r.get('day_open')} high={r.get('day_high')} low={r.get('day_low')} close={r.get('day_close')}")
            if "open_range_high" in r:
                print(f"  Opening range (9:15–9:19): H={r['open_range_high']} L={r['open_range_low']}")

            if not r.get("entry_hit"):
                print(f"  ✗ ENTRY NOT HIT — {r.get('note', '')}")
                continue

            print(f"  ✓ Entry hit @ {r.get('entry_time')}  candle=[O={r.get('entry_candle_open')} H={r.get('entry_candle_high')} L={r.get('entry_candle_low')} C={r.get('entry_candle_close')}]")
            print(f"  1m indicators: RSI={r.get('rsi_at_entry')}  VWAP={r.get('vwap_at_entry')}  EMA9={r.get('ema9_at_entry')}  EMA21={r.get('ema21_at_entry')}  ATR={r.get('atr_at_entry')}")
            if "5m_rsi_at_entry" in r:
                print(f"  5m indicators: RSI={r.get('5m_rsi_at_entry')}  VWAP={r.get('5m_vwap_at_entry')}  EMA9={r.get('5m_ema9_at_entry')}  EMA21={r.get('5m_ema21_at_entry')}")
            print(f"  Signal alignment: {r.get('signal_alignment', 'N/A')}")

            outcome = r.get("outcome", "?")
            pnl_r   = r.get("pnl_r", 0)

            icon = "✓" if pnl_r > 0 else "✗" if pnl_r < 0 else "~"
            print(f"  {icon} Outcome: {outcome}  exit={r.get('exit_px')} @ {r.get('exit_time')}  P&L={pnl_r:+.1f}R")
            if r.get("sl_hit_time"):  print(f"     SL hit: {r['sl_hit_time']}")
            if r.get("r1_hit_time"): print(f"     1R hit: {r['r1_hit_time']}")
            if r.get("r2_hit_time"): print(f"     2R hit: {r['r2_hit_time']}")
            if r.get("r3_hit_time"): print(f"     3R hit: {r['r3_hit_time']}")

            total_r += pnl_r
            analyzed += 1

    print(f"\n{'='*90}")
    print(f"SUMMARY: {analyzed} trades analyzed | Total P&L: {total_r:+.1f}R")
    wins   = sum(1 for r in results if r.get("pnl_r", 0) > 0)
    losses = sum(1 for r in results if r.get("pnl_r", 0) < 0)
    entry_hit = sum(1 for r in results if r.get("entry_hit"))
    no_entry  = sum(1 for r in results if not r.get("entry_hit") and r.get("status") != "NO_DATA")
    print(f"  Entry hit: {entry_hit} | Entry not hit: {no_entry} | Wins: {wins} | Losses: {losses}")
    if analyzed > 0:
        print(f"  Win rate: {wins/analyzed*100:.0f}%  |  Avg R: {total_r/analyzed:+.2f}R")
    print("="*90)


async def main():
    print("Step 1: Checking and fetching missing intraday data...")
    await fetch_missing_data()

    print("\nStep 2: Analyzing all trade plans against actual intraday data...")
    results = []
    for trade_date, legs in TRADE_PLANS.items():
        for leg in legs:
            r = analyze_leg(leg, trade_date)
            results.append(r)

    print_results(results)


if __name__ == "__main__":
    asyncio.run(main())
