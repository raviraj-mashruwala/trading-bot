# Incremental Backtester Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the O(n^2) bottleneck in the backtester by precomputing all indicator Series once on the full dataframe, then indexing per-candle instead of recomputing.

**Architecture:** Add a `precompute_snapshots()` function to `indicators.py` that runs every indicator once over the full df and returns a list of `IndicatorSnapshot` objects (one per candle from WARMUP to end). The `Backtester.run()` method uses these pre-built snapshots instead of calling `compute_snapshot()` per step. Support/resistance and volume_profile are recomputed every 25 steps (expensive, need full window context). After this, remove the 500-candle cap from `pipeline.py`.

**Tech Stack:** Python, pandas, pytest

**Spec:** Analysis from benchmarking: 500 candles takes 60s (current), target <3s. 2000 candles currently hangs (13+ min), target <10s.

## Global Constraints

- `IndicatorSnapshot` dataclass stays unchanged — it's used by strategies, LLM prompts, and the pipeline.
- `Strategy.generate_signal(df, snapshot)` signature stays unchanged — strategies still receive `df.iloc[:index]` for any raw-data lookups and a pre-built snapshot.
- `Backtester.run()` return type `BacktestResult` stays unchanged.
- Existing backtest tests must pass — they use fake strategies that ignore snapshot contents.
- `compute_snapshot()` stays as-is — it's still used by `_fetch_indicators_for_symbol` in the pipeline for single-point indicator computation.

## Review Focus

1. **NaN values at early indices** — indicators like SMA(200) produce NaN for the first 199 candles. The snapshot builder must handle this with safe defaults (same as `_lenient_snapshot` does today) rather than crashing.
2. **Support/resistance staleness** — recomputing every 25 steps means a stock could move significantly between recomputations. A reasonable person would expect levels to be roughly current. 25 steps = ~6 hours of 15m candles — acceptable for backtesting.
3. **Off-by-one on window slicing** — `strategy.generate_signal(df.iloc[:index], snapshot)` must receive data UP TO but not including the current candle (no lookahead). The precomputed snapshot at `index` must also use only data up to `index`.
4. **Volume profile bins shifting** — volume_profile uses histogram binning; the bins depend on price range. A precomputed profile from early in the data may have different bins than a late one. Recomputing every 25 steps mitigates this.
5. **DataFrame mutation** — the existing test `test_backtesting_never_mutates_the_candle_frame` must still pass. Precomputing adds columns or separate arrays but must not modify the input df.

---

### Task 1: Add `precompute_indicator_series()` to indicators.py

**Files:**
- Modify: `tradingbot/strategy/indicators.py` (add new function after `compute_snapshot`)
- Test: `tests/strategy/test_indicators.py` (add precompute tests)

**Interfaces:**
- Consumes: `df: pd.DataFrame` (OHLCV candles), `symbol: str`
- Produces: `precompute_indicator_series(symbol, df) -> dict[str, pd.Series | list]` — a dict of indicator name → full Series. Task 2's `build_snapshots_from_series()` consumes this dict.

- [ ] **Step 1: Write failing tests**

```python
# In tests/strategy/test_indicators.py — add these

import numpy as np
import pandas as pd
from tradingbot.strategy.indicators import precompute_indicator_series

def _make_ohlcv(n=300):
    """Generate n candles of synthetic OHLCV data."""
    np.random.seed(42)
    closes = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "open": closes - 0.2,
        "high": closes + 1.0,
        "low": closes - 1.0,
        "close": closes,
        "volume": np.random.randint(1000, 50000, n).astype(float),
    }, index=pd.date_range("2026-01-01 09:15", periods=n, freq="15min", tz="Asia/Kolkata"))


def test_precompute_returns_all_indicator_keys():
    df = _make_ohlcv(300)
    series = precompute_indicator_series("TEST", df)
    expected_keys = {"rsi_14", "macd", "macd_signal", "bb_upper", "bb_middle",
                     "bb_lower", "atr_14", "sma_20", "sma_50", "sma_200",
                     "ema_12", "ema_26", "ema_9", "sma_9", "vwap",
                     "adx_14", "supertrend", "supertrend_direction",
                     "bb_bandwidth", "vwap_upper_1", "vwap_lower_1", "pivot",
                     "last_close"}
    assert expected_keys.issubset(set(series.keys()))


def test_precompute_series_length_matches_input():
    df = _make_ohlcv(300)
    series = precompute_indicator_series("TEST", df)
    for key, val in series.items():
        if isinstance(val, pd.Series):
            assert len(val) == len(df), f"{key} length mismatch"


def test_precompute_handles_short_dataframe():
    df = _make_ohlcv(60)
    series = precompute_indicator_series("TEST", df)
    assert "rsi_14" in series
    assert len(series["rsi_14"]) == 60
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/strategy/test_indicators.py -v -k "precompute" --tb=short`
Expected: FAIL — `precompute_indicator_series` not defined.

- [ ] **Step 3: Implement `precompute_indicator_series`**

Add after `compute_snapshot` in `tradingbot/strategy/indicators.py`:

```python
def precompute_indicator_series(symbol: str, df: pd.DataFrame) -> dict[str, Any]:
    """Compute all indicator Series once over the full dataframe.

    Returns a dict of indicator_name -> pd.Series (same length as df).
    Used by the backtester to avoid recomputing per candle.
    """
    close = df["close"]

    macd_line, signal_line = macd(close)
    upper, middle, lower = bollinger_bands(close)
    atr_series = atr(df)
    adx_series = adx(df, period=14)
    st_upper, st_lower, st_dir = supertrend(df, period=10, multiplier=3.0)
    bb_bw = bollinger_bandwidth(close)
    vwap_line, vwap_u1, vwap_l1, _, _ = vwap_bands(df)
    pivots = pivot_points(df)

    return {
        "last_close": close.astype(float),
        "rsi_14": rsi(close),
        "macd": macd_line,
        "macd_signal": signal_line,
        "bb_upper": upper,
        "bb_middle": middle,
        "bb_lower": lower,
        "atr_14": atr_series,
        "sma_9": sma(close, 9),
        "sma_20": sma(close, 20),
        "sma_50": sma(close, 50),
        "sma_200": sma(close, 200),
        "ema_9": ema(close, 9),
        "ema_12": ema(close, 12),
        "ema_26": ema(close, 26),
        "vwap": vwap_line,
        "vwap_upper_1": vwap_u1,
        "vwap_lower_1": vwap_l1,
        "pivot": pd.Series(pivots["pivot"], index=df.index),
        "adx_14": adx_series,
        "supertrend": pd.Series(
            [float(st_upper.iloc[i]) if st_dir.iloc[i] == -1 else float(st_lower.iloc[i])
             for i in range(len(df))],
            index=df.index,
        ),
        "supertrend_direction": st_dir,
        "bb_bandwidth": bb_bw,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/strategy/test_indicators.py -v -k "precompute" --tb=short`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingbot/strategy/indicators.py tests/strategy/test_indicators.py
git commit -m "feat(indicators): add precompute_indicator_series for O(n) backtesting"
```

---

### Task 2: Rewrite Backtester.run() to use precomputed indicators

**Files:**
- Modify: `tradingbot/strategy/backtester.py:30-78` (rewrite `run` method)
- Modify: `tests/strategy/test_backtester.py` (add performance test)

**Interfaces:**
- Consumes: `precompute_indicator_series(symbol, df) -> dict[str, pd.Series]` from Task 1
- Produces: Same `BacktestResult` as before. Same `Backtester.run(symbol, df, strategy)` signature.

- [ ] **Step 1: Write failing performance test**

```python
# In tests/strategy/test_backtester.py — add

import time

def test_backtest_2000_candles_completes_under_15_seconds():
    """Regression test: 2000 candles previously took 13+ min due to O(n^2)."""
    df = make_candles(np.arange(100, 2100, dtype=float))
    start = time.monotonic()
    result = Backtester().run("PERF", df, AlwaysLongStrategy())
    elapsed = time.monotonic() - start
    assert elapsed < 15.0, f"Backtest took {elapsed:.1f}s, expected < 15s"
    assert result.trades > 0
```

- [ ] **Step 2: Run test to verify it fails (or times out)**

Run: `.venv/bin/python3 -m pytest tests/strategy/test_backtester.py::test_backtest_2000_candles_completes_under_15_seconds -v --timeout=120`
Expected: FAIL — takes 13+ min (will timeout at 120s).

- [ ] **Step 3: Rewrite `Backtester.run()` with precomputed indicators**

Replace the `run` method in `tradingbot/strategy/backtester.py`:

```python
    def run(self, symbol: str, df: pd.DataFrame, strategy: Strategy) -> BacktestResult:
        """Score one strategy on one symbol over the supplied candles."""
        if len(df) <= WARMUP_CANDLES:
            return BacktestResult(
                symbol=symbol,
                strategy=strategy.name,
                trades=0,
                wins=0,
                win_rate=0.0,
                avg_reward_risk=0.0,
            )

        from tradingbot.strategy.indicators import precompute_indicator_series

        indicator_series = precompute_indicator_series(symbol, df)

        trades = 0
        wins = 0
        reward_risks: list[float] = []
        index = WARMUP_CANDLES
        last_sr_index = -SUPPORT_RESISTANCE_INTERVAL
        supports: list[float] = []
        resistances: list[float] = []
        vol_prof = {"poc": 0.0, "vah": 0.0, "val": 0.0}

        while index < len(df):
            if index - last_sr_index >= SUPPORT_RESISTANCE_INTERVAL:
                from tradingbot.strategy.indicators import support_resistance, volume_profile
                window = df.iloc[:index]
                try:
                    supports, resistances = support_resistance(window)
                except Exception:
                    supports, resistances = [], []
                try:
                    vol_prof = volume_profile(window)
                except Exception:
                    vol_prof = {"poc": 0.0, "vah": 0.0, "val": 0.0}
                last_sr_index = index

            snapshot = self._snapshot_at(symbol, indicator_series, index,
                                         supports, resistances, vol_prof)

            signal = strategy.generate_signal(df.iloc[:index], snapshot)
            if signal is None:
                index += 1
                continue

            outcome, exit_index = self._resolve(df, index, signal)
            if outcome is None:
                break

            trades += 1
            wins += 1 if outcome else 0
            risk = abs(signal.entry_price - signal.stop_loss)
            if risk > 0:
                reward_risks.append(abs(signal.target_1 - signal.entry_price) / risk)

            index = exit_index + 1

        return BacktestResult(
            symbol=symbol,
            strategy=strategy.name,
            trades=trades,
            wins=wins,
            win_rate=wins / trades if trades else 0.0,
            avg_reward_risk=sum(reward_risks) / len(reward_risks) if reward_risks else 0.0,
        )
```

Add the constant and helper method:

```python
SUPPORT_RESISTANCE_INTERVAL = 25

    @staticmethod
    def _snapshot_at(
        symbol: str,
        series: dict,
        index: int,
        supports: list[float],
        resistances: list[float],
        vol_prof: dict,
    ):
        from tradingbot.core.models import IndicatorSnapshot
        import numpy as np

        def safe(s, idx, fallback=0.0):
            if isinstance(s, pd.Series) and idx < len(s):
                val = s.iloc[idx]
                return float(val) if not (isinstance(val, float) and np.isnan(val)) else fallback
            return fallback

        last_close = safe(series["last_close"], index, 100.0)
        return IndicatorSnapshot(
            symbol=symbol,
            last_close=last_close,
            rsi_14=safe(series["rsi_14"], index, 50.0),
            macd=safe(series["macd"], index),
            macd_signal=safe(series["macd_signal"], index),
            bb_upper=safe(series["bb_upper"], index, last_close),
            bb_middle=safe(series["bb_middle"], index, last_close),
            bb_lower=safe(series["bb_lower"], index, last_close),
            atr_14=safe(series["atr_14"], index, 1.0),
            sma_9=safe(series.get("sma_9", pd.Series(dtype=float)), index, last_close),
            sma_20=safe(series["sma_20"], index, last_close),
            sma_50=safe(series["sma_50"], index, last_close),
            sma_200=safe(series["sma_200"], index, last_close),
            ema_9=safe(series.get("ema_9", pd.Series(dtype=float)), index, last_close),
            ema_12=safe(series["ema_12"], index, last_close),
            ema_26=safe(series["ema_26"], index, last_close),
            vwap=safe(series["vwap"], index, last_close),
            pivot=safe(series["pivot"], index, last_close),
            support_levels=supports,
            resistance_levels=resistances,
            adx_14=safe(series["adx_14"], index),
            supertrend=safe(series["supertrend"], index),
            supertrend_direction=int(safe(series["supertrend_direction"], index, 1)),
            bb_bandwidth=safe(series["bb_bandwidth"], index),
            vwap_upper_1=safe(series["vwap_upper_1"], index),
            vwap_lower_1=safe(series["vwap_lower_1"], index),
            poc=vol_prof.get("poc", 0.0),
            vah=vol_prof.get("vah", 0.0),
            val=vol_prof.get("val", 0.0),
        )
```

- [ ] **Step 4: Run performance test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/strategy/test_backtester.py::test_backtest_2000_candles_completes_under_15_seconds -v --timeout=120`
Expected: PASS in <15s.

- [ ] **Step 5: Run all existing backtester tests**

Run: `.venv/bin/python3 -m pytest tests/strategy/test_backtester.py -v --tb=short`
Expected: All PASS — existing tests use fake strategies that don't inspect snapshot deeply.

- [ ] **Step 6: Commit**

```bash
git add tradingbot/strategy/backtester.py tests/strategy/test_backtester.py
git commit -m "perf(backtest): precompute indicators once, O(n) instead of O(n²)"
```

---

### Task 3: Remove backtest candle cap and run full benchmark

**Files:**
- Modify: `tradingbot/analysis/pipeline.py` (remove 500-candle cap)
- Test: manual benchmark with real data

**Interfaces:**
- Consumes: Precomputed backtester from Task 2
- Produces: Pipeline runs full backtest without hanging

- [ ] **Step 1: Remove the 500-candle cap**

In `tradingbot/analysis/pipeline.py`, remove:
```python
        if len(df) > 500:
            df = df.tail(500).reset_index(drop=True)
```

- [ ] **Step 2: Benchmark with real DuckDB data**

```bash
.venv/bin/python3 -c "
import sys, time
sys.path.insert(0, '.')
from tradingbot.data.candle_store import CandleStore
from tradingbot.strategy.strategies import STRATEGY_REGISTRY
from tradingbot.strategy.backtester import Backtester

store = CandleStore('candles.duckdb')
engine = Backtester()
df = store.read('SCI', '15m', days=60)
print(f'SCI 15m: {len(df)} rows (no cap)')

total = 0
for name, strategy in STRATEGY_REGISTRY.items():
    start = time.monotonic()
    report = engine.run('SCI', df, strategy)
    elapsed = time.monotonic() - start
    total += elapsed
    print(f'  {name.value:25s} {elapsed:6.2f}s  trades={report.trades}')

print(f'Total: {total:.1f}s for 10 strategies')
store.close()
"
```

Expected: Full data (~2000+ rows), all 10 strategies complete in <30s total.

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/python3 -m pytest tests/strategy/ tests/analysis/test_prompts.py -v --tb=short`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add tradingbot/analysis/pipeline.py
git commit -m "perf(pipeline): remove 500-candle backtest cap — O(n) backtester handles full data"
```
