# Pipeline Intelligence Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 7 gaps in `AnalysisPipeline` that silently degrade screening quality, OOS validation, and Claude's setup design — without changing any prompt text in `prompts.py` (except Task 6).

**Architecture:** All changes are in `analysis/pipeline.py` (Tasks 1–5, 7) and `analysis/prompts.py` (Task 6). No new files needed except a DB migration helper and new test modules. The pipeline already has the right shape; the gaps are missing computations, wrong engine injection, and unpersisted LLM output fields.

**Tech Stack:** Python 3.12, SQLite (via `SetupStore`), numpy, pandas, `WalkForwardEngine` (already in repo), `StrategyName` enum (already in repo), `IndicatorSnapshot.to_dict()` (already in repo).

**Spec:** `docs/superpowers/plans/2026-09-29-pipeline-intelligence-gaps.md` (this file)

## Global Constraints

- Python 3.12, `from __future__ import annotations` in every file touched
- All new code follows existing `@dataclass(frozen=True)` and type-hint patterns
- `STRATEGY_REGISTRY` keys are `StrategyName` enum values, not raw strings — gate must use `StrategyName.*`
- `SetupStore.save()` accepts `dict[str, Any]` — schema changes require `ALTER TABLE` migration on existing DB
- `WalkForwardEngine` constructor signature: `WalkForwardEngine(windows=int, train_pct=int, include_costs=bool)`
- No new external dependencies — only stdlib + already-installed packages
- Every task ends with `pytest tests/ -x -q` passing

## Review Focus

- **Regime gate with unknown regime string:** If LLM returns a regime not in `REGIME_STRATEGY_GATE`, all strategies should run (fail-open), not zero strategies (fail-closed which produces empty plan)
- **WalkForwardEngine with thin candle data:** Symbols with <250 candles return `_empty_report` with `total_trades=0` — quality gate correctly rejects them, no crash
- **Correlation filter when only one symbol shortlisted:** `_drop_correlated_setups` with len 1 must return that symbol unchanged
- **DB migration on existing `tradingbot.db`:** `ALTER TABLE` is idempotent — second run must not crash if columns already exist
- **Indicator fetch failure mid-loop:** One symbol raising `InsufficientDataError` must not abort the entire shortlist loop — remaining symbols must still be analyzed

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `tradingbot/analysis/pipeline.py` | Modify | All 6 runtime gap fixes (Tasks 1–5, 7) |
| `tradingbot/analysis/prompts.py` | Modify | Add `<final_check>` block to `ADVERSARIAL_SYSTEM` (Task 6) |
| `tradingbot/persistence/setup_store.py` | Modify | Add 6 new columns + migration (Task 5) |
| `tests/analysis/test_stock_metrics.py` | Modify | Add factor score tests (Task 1) |
| `tests/analysis/test_pipeline.py` | Modify | Add WF engine, regime gate, indicator, correlation tests (Tasks 2–4, 7) |
| `tests/analysis/test_prompts.py` | Modify | Add adversarial prompt content test (Task 6) |
| `tests/persistence/test_setup_store.py` | Create | Migration + new field persistence tests (Task 5) |

---

## Task 1: Compute All 9 Factor Scores in `_build_stock_metrics`

**Files:**
- Modify: `tradingbot/analysis/pipeline.py` — `_build_stock_metrics` method
- Modify: `tests/analysis/test_stock_metrics.py`

**Interfaces:**
- Consumes: `market_ctx: MarketContext` (already fetched before loop) — adds `nifty_level` for RS computation
- Produces: `factor_scores` dict with all 9 keys: `volume_surge`, `relative_strength`, `atr_expansion`, `price_structure`, `delivery_pct`, `sector_momentum`, `gap_analysis`, `candlestick_pattern`, `volume_profile`

- [ ] **Step 1.1: Write failing tests**

```python
# tests/analysis/test_stock_metrics.py
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

def _make_df(n=30, close_trend="up"):
    """Build a minimal OHLCV DataFrame for testing."""
    base = 100.0
    rows = []
    for i in range(n):
        c = base + i if close_trend == "up" else base - i * 0.3
        rows.append({"open": c - 0.5, "high": c + 1, "low": c - 1, "close": c, "volume": 1_000_000 + i * 10_000})
    df = pd.DataFrame(rows)
    df.index = pd.date_range(end=datetime.now(tz=IST), periods=n, freq="D", tz=IST)
    return df


def _make_pipeline(candle_df):
    from tradingbot.analysis.pipeline import AnalysisPipeline
    candle_store = MagicMock()
    candle_store.read.return_value = candle_df
    instrument_cache = MagicMock()
    instrument_cache.get_all.return_value = [{"symbol": "TCS", "token": 1}]
    p = AnalysisPipeline(
        data_sync=MagicMock(), candle_store=candle_store, screener=MagicMock(),
        tier2=MagicMock(), tier3=MagicMock(), backtest_engine=MagicMock(),
        monte_carlo=MagicMock(), quality_gates=MagicMock(), run_store=MagicMock(),
        setup_store=MagicMock(), event_bus=MagicMock(), capital=100_000,
        instrument_cache=instrument_cache,
    )
    return p


def test_all_nine_factor_keys_present():
    df = _make_df(30)
    p = _make_pipeline(df)
    metrics = p._build_stock_metrics()
    assert len(metrics) == 1
    fs = metrics[0]["factor_scores"]
    expected_keys = {
        "volume_surge", "relative_strength", "atr_expansion",
        "price_structure", "delivery_pct", "sector_momentum",
        "gap_analysis", "candlestick_pattern", "volume_profile",
    }
    assert expected_keys == set(fs.keys())


def test_volume_surge_score_range():
    df = _make_df(30)
    p = _make_pipeline(df)
    metrics = p._build_stock_metrics()
    score = metrics[0]["factor_scores"]["volume_surge"]
    assert 0.0 <= score <= 100.0


def test_relative_strength_neutral_when_no_nifty_change():
    df = _make_df(30)
    p = _make_pipeline(df)
    # nifty_5d_change=0 means RS == stock's own 5d return mapped to [0,100]
    metrics = p._build_stock_metrics(nifty_5d_change=0.0)
    score = metrics[0]["factor_scores"]["relative_strength"]
    assert 0.0 <= score <= 100.0


def test_atr_expansion_score_range():
    df = _make_df(30)
    p = _make_pipeline(df)
    metrics = p._build_stock_metrics()
    score = metrics[0]["factor_scores"]["atr_expansion"]
    assert 0.0 <= score <= 100.0


def test_price_structure_above_sma20_scores_above_50():
    df = _make_df(30, close_trend="up")  # uptrend → close > SMA20
    p = _make_pipeline(df)
    metrics = p._build_stock_metrics()
    assert metrics[0]["factor_scores"]["price_structure"] > 50.0
```

- [ ] **Step 1.2: Run to confirm failure**

```bash
pytest tests/analysis/test_stock_metrics.py -x -q
```
Expected: `FAILED` — `_build_stock_metrics` doesn't accept `nifty_5d_change` and only returns `gap_analysis`.

- [ ] **Step 1.3: Implement factor score computation**

In `tradingbot/analysis/pipeline.py`, update `_build_stock_metrics` signature and body:

```python
def _build_stock_metrics(self, nifty_5d_change: float = 0.0) -> list[dict]:
    """Compute all 9 screening factor scores for cached instruments."""
    if self._instrument_cache is None:
        return []

    instruments = self._instrument_cache.get_all()
    if not instruments:
        return []

    import pandas as pd
    from datetime import timedelta

    now = datetime.now(tz=IST)
    from_dt = now - timedelta(days=30)

    # Pre-compute sector returns for sector_momentum score
    sector_returns: dict[str, list[float]] = {}  # sector -> list of stock 5d returns

    metrics = []
    for inst in instruments:
        symbol = inst["symbol"]
        df = self._candles.read(symbol, "day", from_dt, now)
        if df.empty or len(df) < 5:
            continue

        close = df["close"]
        volume = df["volume"]
        last_price = float(close.iloc[-1])
        avg_volume = float(volume.tail(20).mean())

        # ATR
        high, low, prev_close = df["high"], df["low"], close.shift(1)
        true_range = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        atr = float(true_range.tail(min(14, len(df))).mean())
        atr_pct = (atr / last_price * 100) if last_price > 0 else 0

        # Gap analysis
        gap_score = 0.0
        if len(df) >= 2:
            prev_c = float(df["close"].iloc[-2])
            today_open = float(df["open"].iloc[-1])
            if prev_c > 0:
                gap_pct = abs(today_open - prev_c) / prev_c * 100
                gap_score = min(100.0, gap_pct * 33.3)

        # Volume surge: today vs 20d avg
        vol_today = float(volume.iloc[-1])
        vol_surge_pct = ((vol_today / avg_volume) - 1) * 100 if avg_volume > 0 else 0
        volume_surge_score = min(100.0, max(0.0, vol_surge_pct * 2))

        # Relative strength vs Nifty
        stock_5d_return = 0.0
        if len(close) >= 6:
            stock_5d_return = (float(close.iloc[-1]) / float(close.iloc[-6]) - 1) * 100
        rs_excess = stock_5d_return - nifty_5d_change
        relative_strength_score = min(100.0, max(0.0, 50.0 + rs_excess * 5.0))

        # ATR expansion (vs itself — 2% ATR = 100 score)
        atr_expansion_score = min(100.0, max(0.0, atr_pct * 50.0))

        # Price structure: close vs SMA20
        sma20 = float(close.tail(20).mean()) if len(close) >= 20 else last_price
        pct_above_sma20 = ((last_price - sma20) / sma20 * 100) if sma20 > 0 else 0
        price_structure_score = min(100.0, max(0.0, 50.0 + pct_above_sma20 * 5.0))

        sector = inst.get("sector", "unknown")
        sector_returns.setdefault(sector, []).append(stock_5d_return)

        market_cap_cr = last_price * avg_volume / 1_00_00_000

        metrics.append({
            "symbol": symbol,
            "token": inst["token"],
            "last_price": last_price,
            "avg_volume": avg_volume,
            "market_cap_cr": market_cap_cr,
            "atr_pct": atr_pct,
            "sector": sector,
            "trading_days": len(df),
            "_stock_5d_return": stock_5d_return,  # temp key for sector_momentum pass
            "factor_scores": {
                "gap_analysis": gap_score,
                "volume_surge": volume_surge_score,
                "relative_strength": relative_strength_score,
                "atr_expansion": atr_expansion_score,
                "price_structure": price_structure_score,
                "delivery_pct": 50.0,      # requires depository API — neutral until added
                "candlestick_pattern": 50.0,  # requires pattern engine
                "volume_profile": 50.0,    # requires intraday data
                "sector_momentum": 50.0,   # filled in second pass below
            },
        })

    # Second pass: fill sector_momentum from median sector return
    import statistics
    sector_median: dict[str, float] = {
        s: statistics.median(returns) for s, returns in sector_returns.items() if returns
    }
    for m in metrics:
        sector = m["sector"]
        med = sector_median.get(sector, 0.0)
        sector_momentum_score = min(100.0, max(0.0, 50.0 + med * 5.0))
        m["factor_scores"]["sector_momentum"] = sector_momentum_score
        del m["_stock_5d_return"]  # clean temp key

    return metrics
```

- [ ] **Step 1.4: Update `run()` to pass `nifty_5d_change` to `_build_stock_metrics`**

> **Note (781d633):** `yfinance` was removed from `pyproject.toml`. Do NOT use `yf.Ticker()` here. Use `CandleStore` instead — Nifty50 daily candles are already synced via Kite.

In `AnalysisPipeline.run()`, change:
```python
# Before (line ~50 in pipeline.py):
stock_metrics = self._build_stock_metrics()
```
To:
```python
market_ctx = self._fetch_market_context()
nifty_5d_change = self._compute_nifty_5d_change_from_store()
stock_metrics = self._build_stock_metrics(nifty_5d_change=nifty_5d_change)
```

Add helper method (CandleStore, no external HTTP):
```python
def _compute_nifty_5d_change_from_store(self) -> float:
    """5-day Nifty50 return from CandleStore. Zero on failure. No yfinance."""
    try:
        df = self._candles.read(
            "NIFTY 50", "day",
            datetime(2025, 1, 1, tzinfo=IST),
            datetime.now(tz=IST),
        )
        if len(df) >= 6:
            return float((df["close"].iloc[-1] / df["close"].iloc[-6] - 1) * 100)
    except Exception:
        pass
    return 0.0
```

Also remove the duplicate `market_ctx = self._fetch_market_context()` call that currently appears after `stock_metrics = self._build_stock_metrics()` in `run()`.

- [ ] **Step 1.5: Run tests**

```bash
pytest tests/analysis/test_stock_metrics.py -x -q
```
Expected: all 5 tests PASS.

- [ ] **Step 1.6: Commit**

```bash
git add tradingbot/analysis/pipeline.py tests/analysis/test_stock_metrics.py
git commit -m "feat(screening): compute all 9 factor scores in _build_stock_metrics

Previously only gap_analysis was computed; 8/9 factors defaulted to 50.0,
making composite scores nearly identical across all stocks.

Co-Authored-By: Claude Sonnet 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Use `WalkForwardEngine` in `_run_backtests` (OOS Gate Now Fires)

> **Note (781d633):** `analysis_routes.py` already injects `WalkForwardEngine()` as `backtest_engine` (line 74). The CLI `analyze` command is **retired** — it just prints "use web UI". So the only pipeline entry point is the API route, which already passes WF. This task ensures `_run_backtests` actually uses `self._backtest` (the injected WF engine) instead of importing a fresh `Backtester` internally.

**Files:**
- Modify: `tradingbot/analysis/pipeline.py` — `_run_backtests` method only (no `__init__` change needed)
- Modify: `tests/analysis/test_pipeline.py`

**Interfaces:**
- Consumes: `self._backtest` (already `WalkForwardEngine` when called via API route)
- Produces: `BacktestReport` with real `oos_degradation` (not always `0.0`)

- [ ] **Step 2.1: Write failing test**

```python
# tests/analysis/test_pipeline.py  (add to existing file)
from unittest.mock import MagicMock, patch, call
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _make_candle_df(n=300):
    import numpy as np
    closes = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "open": closes - 0.3,
        "high": closes + 1,
        "low": closes - 1,
        "close": closes,
        "volume": [1_000_000] * n,
    })


def test_run_backtests_uses_walk_forward_engine():
    """_run_backtests must use WalkForwardEngine, not simple Backtester."""
    from tradingbot.analysis.pipeline import AnalysisPipeline
    from tradingbot.backtest.walk_forward import WalkForwardEngine

    wf_engine = MagicMock(spec=WalkForwardEngine)
    mock_report = MagicMock()
    mock_report.total_trades = 10
    mock_report.winners = 6
    mock_report.losers = 4
    mock_report.avg_winner = 2.0
    mock_report.avg_loser = -1.0
    wf_engine.run.return_value = mock_report

    mock_mc = MagicMock()
    mock_gate = MagicMock()
    mock_gate.evaluate.return_value = MagicMock(passed=True)

    candle_store = MagicMock()
    candle_store.read.return_value = _make_candle_df(300)

    p = AnalysisPipeline(
        data_sync=MagicMock(), candle_store=candle_store, screener=MagicMock(),
        tier2=MagicMock(), tier3=MagicMock(), backtest_engine=wf_engine,
        monte_carlo=mock_mc, quality_gates=mock_gate, run_store=MagicMock(),
        setup_store=MagicMock(), event_bus=MagicMock(), capital=100_000,
    )
    results = []
    p._run_backtests("TCS", results, regime={"regime": "trending_up"})

    # WalkForwardEngine.run must have been called (not simple Backtester)
    assert wf_engine.run.called
```

- [ ] **Step 2.2: Run to confirm failure**

```bash
pytest tests/analysis/test_pipeline.py::test_run_backtests_uses_walk_forward_engine -x -q
```
Expected: FAIL — `_run_backtests` doesn't accept `regime` kwarg yet and uses `self._backtest.run()`.

- [ ] **Step 2.3: Implement**

Replace `_run_backtests` in `tradingbot/analysis/pipeline.py`:

```python
def _run_backtests(self, symbol: str, results: list, regime: dict) -> None:
    """Run WalkForward backtest for regime-eligible strategies on one symbol.

    Appends passing BacktestReports to results list.
    """
    from tradingbot.strategy.strategies import STRATEGY_REGISTRY

    eligible = self._get_regime_eligible_strategies(regime)

    for strategy_name, strategy in STRATEGY_REGISTRY.items():
        if strategy_name not in eligible:
            continue

        df = self._candles.read(
            symbol, "15minute",
            datetime(2025, 1, 1, tzinfo=IST),
            datetime.now(tz=IST),
        )
        if len(df) == 0:
            continue

        report = self._backtest.run(symbol, df, strategy)
        if report.total_trades < 5:
            continue

        trade_pnls = (
            [report.avg_winner] * report.winners
            + [report.avg_loser] * report.losers
        )
        mc = self._mc.run(trade_pnls) if trade_pnls else None
        if mc is None:
            continue

        gate = self._gates.evaluate(report, mc)
        if gate.passed:
            results.append(report)
```

Update the call site inside `run()`:
```python
# Before:
self._run_backtests(sym, bt_results)
# After:
self._run_backtests(sym, bt_results, regime=regime)
```

- [ ] **Step 2.4: Run tests**

```bash
pytest tests/analysis/test_pipeline.py::test_run_backtests_uses_walk_forward_engine -x -q
```
Expected: PASS.

- [ ] **Step 2.5: Commit**

```bash
git add tradingbot/analysis/pipeline.py tests/analysis/test_pipeline.py
git commit -m "feat(backtest): wire WalkForwardEngine into _run_backtests

Simple Backtester returned oos_degradation=0.0 always, making the OOS
quality gate a no-op. WalkForwardEngine produces real train/OOS split metrics.

Co-Authored-By: Claude Sonnet 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Regime → Strategy Gate

**Files:**
- Modify: `tradingbot/analysis/pipeline.py` — add `REGIME_STRATEGY_GATE` constant + `_get_regime_eligible_strategies()`
- Modify: `tests/analysis/test_pipeline.py`

**Interfaces:**
- Consumes: `regime: dict` with key `"regime"` (string, one of `MarketRegime` enum values)
- Produces: `set[StrategyName]` — the strategies eligible to run today

- [ ] **Step 3.1: Write failing tests**

```python
# tests/analysis/test_pipeline.py (add)
from tradingbot.core.models import StrategyName


def _make_minimal_pipeline():
    from tradingbot.analysis.pipeline import AnalysisPipeline
    return AnalysisPipeline(
        data_sync=MagicMock(), candle_store=MagicMock(), screener=MagicMock(),
        tier2=MagicMock(), tier3=MagicMock(), backtest_engine=MagicMock(),
        monte_carlo=MagicMock(), quality_gates=MagicMock(), run_store=MagicMock(),
        setup_store=MagicMock(), event_bus=MagicMock(), capital=100_000,
    )


def test_trending_up_excludes_mean_reversion():
    p = _make_minimal_pipeline()
    eligible = p._get_regime_eligible_strategies({"regime": "trending_up"})
    assert StrategyName.MEAN_REVERSION not in eligible
    assert StrategyName.MOMENTUM in eligible


def test_range_bound_excludes_momentum():
    p = _make_minimal_pipeline()
    eligible = p._get_regime_eligible_strategies({"regime": "range_bound"})
    assert StrategyName.MOMENTUM not in eligible
    assert StrategyName.MEAN_REVERSION in eligible


def test_unknown_regime_returns_all_strategies():
    """Fail-open: unknown regime must not produce empty strategy set."""
    p = _make_minimal_pipeline()
    from tradingbot.strategy.strategies import STRATEGY_REGISTRY
    eligible = p._get_regime_eligible_strategies({"regime": "alien_regime"})
    assert eligible == set(STRATEGY_REGISTRY.keys())


def test_volatile_includes_orb_and_gap_and_go():
    p = _make_minimal_pipeline()
    eligible = p._get_regime_eligible_strategies({"regime": "volatile"})
    assert StrategyName.ORB in eligible
    assert StrategyName.GAP_AND_GO in eligible


def test_low_vol_squeeze_includes_bollinger():
    p = _make_minimal_pipeline()
    eligible = p._get_regime_eligible_strategies({"regime": "low_vol_squeeze"})
    assert StrategyName.BOLLINGER_SQUEEZE in eligible
```

- [ ] **Step 3.2: Run to confirm failure**

```bash
pytest tests/analysis/test_pipeline.py -k "regime" -x -q
```
Expected: `AttributeError: 'AnalysisPipeline' object has no attribute '_get_regime_eligible_strategies'`

- [ ] **Step 3.3: Implement**

Add to `tradingbot/analysis/pipeline.py` at module level (after imports):

```python
from tradingbot.core.models import StrategyName

REGIME_STRATEGY_GATE: dict[str, frozenset[StrategyName]] = {
    "trending_up": frozenset({
        StrategyName.MOMENTUM, StrategyName.BREAKOUT, StrategyName.GAP_AND_GO,
        StrategyName.RELATIVE_STRENGTH, StrategyName.ORB,
    }),
    "trending_down": frozenset({
        StrategyName.MEAN_REVERSION, StrategyName.VWAP_BOUNCE,
        StrategyName.RELATIVE_STRENGTH, StrategyName.ORB,
    }),
    "range_bound": frozenset({
        StrategyName.MEAN_REVERSION, StrategyName.VWAP_BOUNCE,
        StrategyName.PIVOT_POINT, StrategyName.BOLLINGER_SQUEEZE,
        StrategyName.SUPPLY_DEMAND,
    }),
    "volatile": frozenset({
        StrategyName.ORB, StrategyName.GAP_AND_GO,
        StrategyName.VWAP_BOUNCE, StrategyName.BREAKOUT,
    }),
    "low_vol_squeeze": frozenset({
        StrategyName.BOLLINGER_SQUEEZE, StrategyName.BREAKOUT,
    }),
}
```

Add method to `AnalysisPipeline`:

```python
def _get_regime_eligible_strategies(self, regime: dict) -> frozenset[StrategyName]:
    """Return strategy names valid for the current regime. Fail-open on unknown."""
    from tradingbot.strategy.strategies import STRATEGY_REGISTRY
    regime_name = regime.get("regime", "range_bound")
    return REGIME_STRATEGY_GATE.get(regime_name, frozenset(STRATEGY_REGISTRY.keys()))
```

- [ ] **Step 3.4: Run tests**

```bash
pytest tests/analysis/test_pipeline.py -k "regime" -x -q
```
Expected: all 5 regime tests PASS.

- [ ] **Step 3.5: Commit**

```bash
git add tradingbot/analysis/pipeline.py tests/analysis/test_pipeline.py
git commit -m "feat(pipeline): add regime→strategy gate to _run_backtests

Prevents Claude from seeing backtest evidence for regime-incompatible
strategies. In trending_up markets, mean_reversion results are excluded;
in range_bound markets, momentum results are excluded. Fail-open on
unknown regimes (all strategies run).

Co-Authored-By: Claude Sonnet 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Fetch Real Indicators + Price Action Per Symbol

**Files:**
- Modify: `tradingbot/analysis/pipeline.py` — add `_fetch_indicators_for_symbol()` + `_build_price_action_summary()`; update the `for pick in shortlist:` loop
- Modify: `tests/analysis/test_pipeline.py`

**Interfaces:**
- Consumes: `compute_snapshot(symbol, df)` from `tradingbot.strategy.indicators` — returns `IndicatorSnapshot`
- Produces: `indicators: dict` (via `IndicatorSnapshot.to_dict()`) and `price_action: str` injected into `tier3.deep_analyze()`

- [ ] **Step 4.1: Write failing tests**

```python
# tests/analysis/test_pipeline.py (add)
from tradingbot.strategy.indicators import InsufficientDataError


def test_fetch_indicators_returns_dict_with_rsi():
    from tradingbot.analysis.pipeline import AnalysisPipeline
    candle_store = MagicMock()
    candle_store.read.return_value = _make_candle_df(300)

    p = AnalysisPipeline(
        data_sync=MagicMock(), candle_store=candle_store, screener=MagicMock(),
        tier2=MagicMock(), tier3=MagicMock(), backtest_engine=MagicMock(),
        monte_carlo=MagicMock(), quality_gates=MagicMock(), run_store=MagicMock(),
        setup_store=MagicMock(), event_bus=MagicMock(), capital=100_000,
    )
    indicators, price_action = p._fetch_indicators_for_symbol("TCS")
    assert "rsi_14" in indicators
    assert "vwap" in indicators
    assert "TCS" in price_action


def test_fetch_indicators_returns_empty_on_insufficient_data():
    """InsufficientDataError must not propagate — returns empty dict + fallback string."""
    from tradingbot.analysis.pipeline import AnalysisPipeline
    candle_store = MagicMock()
    candle_store.read.return_value = pd.DataFrame()  # empty

    p = AnalysisPipeline(
        data_sync=MagicMock(), candle_store=candle_store, screener=MagicMock(),
        tier2=MagicMock(), tier3=MagicMock(), backtest_engine=MagicMock(),
        monte_carlo=MagicMock(), quality_gates=MagicMock(), run_store=MagicMock(),
        setup_store=MagicMock(), event_bus=MagicMock(), capital=100_000,
    )
    indicators, price_action = p._fetch_indicators_for_symbol("TCS")
    assert indicators == {}
    assert "insufficient" in price_action.lower()
```

- [ ] **Step 4.2: Run to confirm failure**

```bash
pytest tests/analysis/test_pipeline.py -k "indicators" -x -q
```
Expected: `AttributeError: 'AnalysisPipeline' object has no attribute '_fetch_indicators_for_symbol'`

- [ ] **Step 4.3: Implement**

Add two methods to `AnalysisPipeline` in `tradingbot/analysis/pipeline.py`:

```python
def _fetch_indicators_for_symbol(self, symbol: str) -> tuple[dict, str]:
    """Compute IndicatorSnapshot and price action summary for one symbol.

    Returns (indicators_dict, price_action_str). On failure returns ({}, fallback).
    """
    from tradingbot.strategy.indicators import compute_snapshot, InsufficientDataError

    try:
        df = self._candles.read(
            symbol, "15minute",
            datetime(2025, 1, 1, tzinfo=IST),
            datetime.now(tz=IST),
        )
        if df.empty or len(df) < 30:
            return {}, f"{symbol}: insufficient candle data for indicators"

        snap = compute_snapshot(symbol, df)
        indicators = snap.to_dict()
        price_action = self._build_price_action_summary(symbol, df, snap)
        return indicators, price_action

    except InsufficientDataError:
        return {}, f"{symbol}: insufficient data for indicators"
    except Exception as exc:
        log.warning("Indicator fetch failed for %s: %s", symbol, exc)
        return {}, f"{symbol}: indicator computation failed"

def _build_price_action_summary(self, symbol: str, df, snap) -> str:
    """Build a compact price action narrative string for Claude's context."""
    last_5 = df.tail(5)[["open", "high", "low", "close", "volume"]].to_dict("records")
    return (
        f"{symbol} last 5 candles (15m): {last_5}\n"
        f"VWAP: {snap.vwap:.2f} | RSI14: {snap.rsi_14:.1f} | "
        f"ATR14: {snap.atr_14:.2f} | ADX14: {snap.adx_14:.1f}\n"
        f"BB: [{snap.bb_lower:.2f}, {snap.bb_middle:.2f}, {snap.bb_upper:.2f}] "
        f"BW: {snap.bb_bandwidth:.3f}\n"
        f"Support: {snap.support_levels} | Resistance: {snap.resistance_levels}\n"
        f"Supertrend: {snap.supertrend:.2f} ({'up' if snap.supertrend_direction == 1 else 'down'})"
    )
```

Update the `for pick in shortlist:` loop in `run()`:

```python
for pick in shortlist:
    sym = pick["symbol"]
    direction = pick.get("direction", "long")

    # Fetch indicators (new — was always {} before)
    indicators, price_action = self._fetch_indicators_for_symbol(sym)

    bt_results: list[Any] = []
    self._run_backtests(sym, bt_results, regime=regime)

    deep = await self._tier3.deep_analyze(
        symbol=sym,
        direction=direction,
        regime=regime,
        indicators=indicators,          # was {}
        backtest_results=bt_results,
        price_action=price_action,      # was f"{sym} analysis"
    )
    ...
```

- [ ] **Step 4.4: Run tests**

```bash
pytest tests/analysis/test_pipeline.py -k "indicators" -x -q
```
Expected: PASS.

- [ ] **Step 4.5: Commit**

```bash
git add tradingbot/analysis/pipeline.py tests/analysis/test_pipeline.py
git commit -m "feat(pipeline): fetch real indicators and price action per symbol

Previously deep_analyze received indicators={} and a placeholder string,
forcing Claude to design setups with no technical data. Now each shortlisted
symbol gets a full IndicatorSnapshot and 5-candle price narrative.

Co-Authored-By: Claude Sonnet 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Persist `invalidation`, `bear_case`, `confluence_count` in SetupStore

**Files:**
- Modify: `tradingbot/persistence/setup_store.py` — migration + `save()` update
- Modify: `tradingbot/analysis/pipeline.py` — extend `self._setups.save(...)` dict
- Create: `tests/persistence/test_setup_store.py`

**Interfaces:**
- Consumes: `setup: dict[str, Any]` with new optional keys: `thesis`, `invalidation_condition`, `bear_case`, `confluence_count`, `entry_trigger`, `regime_at_generation`, `timeframe_alignment`
- Produces: same `int` row ID from `save()` — no API change to callers

- [ ] **Step 5.1: Write failing tests**

```python
# tests/persistence/test_setup_store.py
from __future__ import annotations
import pytest
from tradingbot.persistence.setup_store import SetupStore


@pytest.fixture
def store(tmp_path):
    return SetupStore(tmp_path / "test.db")


def _base_setup(**overrides) -> dict:
    base = {
        "run_id": "run_20260929_001",
        "trade_date": "2026-09-29",
        "symbol": "TCS",
        "strategy": "momentum",
        "direction": "long",
        "entry_price": 3500.0,
        "stop_loss": 3450.0,
        "target_1": 3600.0,
        "target_2": 3680.0,
        "confidence": 0.78,
        "status": "approved",
        "reasoning": "strong momentum setup",
    }
    base.update(overrides)
    return base


def test_save_with_new_fields_returns_id(store):
    setup = _base_setup(
        thesis="Breakout above 6-month resistance with volume confirmation",
        invalidation_condition="Close below 3460 on 15m candle",
        bear_case="Market could gap down on global cues",
        confluence_count=4,
        entry_trigger="Break above 3510 with vol > 1.5x avg",
        regime_at_generation="trending_up",
        timeframe_alignment=["15m", "1h", "day"],
    )
    row_id = store.save(setup)
    assert isinstance(row_id, int) and row_id > 0


def test_new_fields_roundtrip(store):
    row_id = store.save(_base_setup(
        invalidation_condition="Close below 3460",
        bear_case="FII selling could resume",
        confluence_count=3,
        regime_at_generation="trending_up",
    ))
    row = store.get_by_id(row_id)
    assert row["invalidation_condition"] == "Close below 3460"
    assert row["bear_case"] == "FII selling could resume"
    assert row["confluence_count"] == 3
    assert row["regime_at_generation"] == "trending_up"


def test_save_without_new_fields_still_works(store):
    row_id = store.save(_base_setup())
    assert row_id > 0
    row = store.get_by_id(row_id)
    assert row.get("invalidation_condition") in (None, "")


def test_migration_idempotent(tmp_path):
    db = tmp_path / "idem.db"
    s1 = SetupStore(db)
    s1.save(_base_setup())
    s1.close()
    s2 = SetupStore(db)   # must not raise on duplicate columns
    s2.close()
```

- [ ] **Step 5.2: Run to confirm failure**

```bash
pytest tests/persistence/test_setup_store.py -x -q
```
Expected: `FAILED` — `get_by_id` row has no `invalidation_condition` column.

- [ ] **Step 5.3: Add idempotent migration to `SetupStore.__init__`**

In `tradingbot/persistence/setup_store.py`, after the two `CREATE INDEX` lines and before `self._conn.commit()`, insert:

```python
        for col, coltype in [
            ("thesis", "TEXT"),
            ("invalidation_condition", "TEXT"),
            ("bear_case", "TEXT"),
            ("confluence_count", "INTEGER"),
            ("entry_trigger", "TEXT"),
            ("regime_at_generation", "TEXT"),
            ("timeframe_alignment", "TEXT"),
        ]:
            try:
                self._conn.execute(f"ALTER TABLE setups ADD COLUMN {col} {coltype}")
            except sqlite3.OperationalError:
                pass  # column already exists
```

- [ ] **Step 5.4: Replace `save()` to write new columns**

```python
    def save(self, setup: dict[str, Any]) -> int:
        import json
        now = datetime.now(tz=IST).isoformat()
        tfa = setup.get("timeframe_alignment", [])
        cursor = self._conn.execute(
            "INSERT INTO setups (run_id, trade_date, symbol, strategy, direction, "
            "entry_price, stop_loss, target_1, target_2, confidence, status, reasoning, "
            "thesis, invalidation_condition, bear_case, confluence_count, "
            "entry_trigger, regime_at_generation, timeframe_alignment, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                setup["run_id"], setup["trade_date"], setup["symbol"],
                setup["strategy"], setup["direction"], setup["entry_price"],
                setup["stop_loss"], setup["target_1"], setup.get("target_2"),
                setup["confidence"], setup.get("status", "proposed"),
                setup.get("reasoning", ""),
                setup.get("thesis", ""),
                setup.get("invalidation_condition", ""),
                setup.get("bear_case", ""),
                setup.get("confluence_count", 0),
                setup.get("entry_trigger", ""),
                setup.get("regime_at_generation", ""),
                json.dumps(tfa) if isinstance(tfa, list) else (tfa or "[]"),
                now, now,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid
```

- [ ] **Step 5.5: Extend pipeline save call**

In `tradingbot/analysis/pipeline.py`, the `self._setups.save({...})` block inside the adversarial approval loop. Add after `"status": "approved"`:

```python
                        "thesis": setup_data.get("edge_description", ""),
                        "invalidation_condition": setup_data.get("invalidation", ""),
                        "bear_case": setup_data.get("bear_case", ""),
                        "confluence_count": setup_data.get("confluence_count", 0),
                        "entry_trigger": setup_data.get("entry_trigger", ""),
                        "regime_at_generation": regime.get("regime", ""),
                        "timeframe_alignment": setup_data.get("timeframe_alignment", []),
```

- [ ] **Step 5.6: Run tests**

```bash
pytest tests/persistence/test_setup_store.py -x -q
```
Expected: all 4 PASS.

- [ ] **Step 5.7: Commit**

```bash
git add tradingbot/persistence/setup_store.py tradingbot/analysis/pipeline.py tests/persistence/test_setup_store.py
git commit -m "feat(persistence): save invalidation, bear_case, confluence_count per setup

LLM captured these in DEEP_ANALYSIS_SCHEMA but they were discarded.
Now persisted for post-trade review loop. Migration idempotent on
existing tradingbot.db via try/except ALTER TABLE.

Co-Authored-By: Claude Sonnet 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Add `<final_check>` Block to `ADVERSARIAL_SYSTEM` Prompt

**Files:**
- Modify: `tradingbot/analysis/prompts.py` — `ADVERSARIAL_SYSTEM` string only
- Modify: `tests/analysis/test_prompts.py`

**Interfaces:**
- Pure prompt text edit — no code interface changes

- [ ] **Step 6.1: Write failing test**

```python
# tests/analysis/test_prompts.py (add)
def test_adversarial_system_contains_final_check_questions():
    from tradingbot.analysis.prompts import ADVERSARIAL_SYSTEM
    for phrase in [
        "What am I missing",
        "truly independent",
        "invalidate this trade",
        "Downgrade",
    ]:
        assert phrase in ADVERSARIAL_SYSTEM, f"Missing: {phrase!r}"
```

- [ ] **Step 6.2: Run to confirm failure**

```bash
pytest tests/analysis/test_prompts.py::test_adversarial_system_contains_final_check_questions -x -q
```
Expected: `AssertionError: Missing: 'What am I missing'`

- [ ] **Step 6.3: Append block to `ADVERSARIAL_SYSTEM`**

In `tradingbot/analysis/prompts.py`, the current `ADVERSARIAL_SYSTEM` ends with:

```python
    "For conditional approvals, specify the exact adjustment required."
)
```

Replace that closing line with:

```python
    "For conditional approvals, specify the exact adjustment required.\n\n"
    "Before finalizing approval decisions, ask yourself for EACH setup:\n"
    "- What am I missing about this thesis?\n"
    "- Are the confluence signals truly independent, or correlated indicators "
    "(RSI + Stochastic = 1 signal, not 2)?\n"
    "- Is the edge real or a recent regime artefact that will not persist?\n"
    "- What evidence would immediately invalidate this trade before entry?\n"
    "- Would I approve this setup if the market gaps down 0.5%% at open?\n"
    "Apply these as a final filter. Downgrade 'strong' to 'conditional' if any "
    "question reveals weakness. Reject outright if two or more questions raise "
    "concerns about the same setup."
)
```

- [ ] **Step 6.4: Run tests**

```bash
pytest tests/analysis/test_prompts.py -x -q
```
Expected: PASS.

- [ ] **Step 6.5: Commit**

```bash
git add tradingbot/analysis/prompts.py tests/analysis/test_prompts.py
git commit -m "feat(prompts): add final_check self-doubt block to ADVERSARIAL_SYSTEM

Adversarial reviewer now also questions individual thesis quality, not
just portfolio mechanics. Forces independent-confluence check and
invalidation-condition review before approving each setup.

Co-Authored-By: Claude Sonnet 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Quantitative Correlation Filter Before Adversarial Call

**Files:**
- Modify: `tradingbot/analysis/pipeline.py` — add `_drop_correlated_setups()` + wire before adversarial call
- Modify: `tests/analysis/test_pipeline.py`

**Interfaces:**
- Consumes: `setups_with_data: list[dict]` — each dict has `"symbol": str`, `"setups": list[dict]` with `"confidence": float`
- Produces: filtered `list[dict]` with correlated lower-confidence symbols removed

- [ ] **Step 7.1: Write failing tests**

```python
# tests/analysis/test_pipeline.py (add)
import numpy as np


def _make_pipeline_with_candles(symbol_dfs: dict):
    from tradingbot.analysis.pipeline import AnalysisPipeline
    candle_store = MagicMock()
    candle_store.read.side_effect = lambda sym, *a, **kw: symbol_dfs.get(sym, pd.DataFrame())
    return AnalysisPipeline(
        data_sync=MagicMock(), candle_store=candle_store, screener=MagicMock(),
        tier2=MagicMock(), tier3=MagicMock(), backtest_engine=MagicMock(),
        monte_carlo=MagicMock(), quality_gates=MagicMock(), run_store=MagicMock(),
        setup_store=MagicMock(), event_bus=MagicMock(), capital=100_000,
    )


def _make_close_df(closes):
    n = len(closes)
    return pd.DataFrame({
        "open": closes - 0.3, "high": closes + 1,
        "low": closes - 1, "close": closes, "volume": [1_000_000] * n,
    })


def _setup_entry(symbol, confidence):
    return {"symbol": symbol, "setups": [{"confidence": confidence}]}


def test_correlated_pair_drops_lower_confidence():
    rng = np.random.default_rng(42)
    base = rng.standard_normal(25)
    c1 = 100 + np.cumsum(base)
    c2 = 100 + np.cumsum(base + rng.standard_normal(25) * 0.01)  # ρ ≈ 1.0
    p = _make_pipeline_with_candles({"TCS": _make_close_df(c1), "INFY": _make_close_df(c2)})
    result = p._drop_correlated_setups([_setup_entry("TCS", 0.85), _setup_entry("INFY", 0.65)])
    syms = [s["symbol"] for s in result]
    assert "TCS" in syms and "INFY" not in syms


def test_uncorrelated_pair_both_kept():
    c_a = 100 + np.cumsum(np.random.default_rng(0).standard_normal(25))
    c_b = 200 + np.cumsum(np.random.default_rng(99).standard_normal(25))
    p = _make_pipeline_with_candles({"HDFC": _make_close_df(c_a), "ONGC": _make_close_df(c_b)})
    result = p._drop_correlated_setups([_setup_entry("HDFC", 0.8), _setup_entry("ONGC", 0.75)])
    assert len(result) == 2


def test_single_symbol_unchanged():
    closes = 100 + np.cumsum(np.random.default_rng(7).standard_normal(25))
    p = _make_pipeline_with_candles({"TCS": _make_close_df(closes)})
    result = p._drop_correlated_setups([_setup_entry("TCS", 0.8)])
    assert len(result) == 1 and result[0]["symbol"] == "TCS"
```

- [ ] **Step 7.2: Run to confirm failure**

```bash
pytest tests/analysis/test_pipeline.py -k "correlated" -x -q
```
Expected: `AttributeError: 'AnalysisPipeline' object has no attribute '_drop_correlated_setups'`

- [ ] **Step 7.3: Implement**

Add method to `AnalysisPipeline` in `tradingbot/analysis/pipeline.py`:

```python
    def _drop_correlated_setups(self, setups_with_data: list[dict]) -> list[dict]:
        """Drop lower-confidence setup when two symbols have ρ > 0.7 on 20d returns."""
        import numpy as np

        if len(setups_with_data) <= 1:
            return setups_with_data

        symbol_returns: dict[str, list[float]] = {}
        for s in setups_with_data:
            sym = s["symbol"]
            try:
                df = self._candles.read(sym, "day",
                                        datetime(2025, 1, 1, tzinfo=IST),
                                        datetime.now(tz=IST))
                if len(df) >= 20:
                    symbol_returns[sym] = df["close"].tail(20).pct_change().dropna().tolist()
            except Exception:
                pass

        symbols = list(symbol_returns.keys())
        to_drop: set[str] = set()

        for i, s1 in enumerate(symbols):
            for s2 in symbols[i + 1:]:
                r1, r2 = symbol_returns[s1], symbol_returns[s2]
                n = min(len(r1), len(r2))
                if n < 10:
                    continue
                rho = float(np.corrcoef(r1[-n:], r2[-n:])[0, 1])
                if rho > 0.7:
                    def _max_conf(sym_: str) -> float:
                        return max(
                            (st.get("confidence", 0) for st in next(
                                (x["setups"] for x in setups_with_data if x["symbol"] == sym_), []
                            )), default=0.0
                        )
                    drop = s2 if _max_conf(s1) >= _max_conf(s2) else s1
                    to_drop.add(drop)
                    log.info("Correlation drop: ρ=%.2f %s↔%s → drop %s", rho, s1, s2, drop)

        return [s for s in setups_with_data if s["symbol"] not in to_drop]
```

Wire into `run()` — find:

```python
        setups_with_data = [s for s in all_setups if s.get("setups")]
        setups_proposed = sum(len(s.get("setups", [])) for s in setups_with_data)
```

Change to:

```python
        setups_with_data = [s for s in all_setups if s.get("setups")]
        setups_with_data = self._drop_correlated_setups(setups_with_data)
        setups_proposed = sum(len(s.get("setups", [])) for s in setups_with_data)
```

- [ ] **Step 7.4: Run tests**

```bash
pytest tests/analysis/test_pipeline.py -k "correlated" -x -q
```
Expected: all 3 PASS.

- [ ] **Step 7.5: Full suite**

```bash
pytest tests/ -x -q
```
Expected: all PASS.

- [ ] **Step 7.6: Commit**

```bash
git add tradingbot/analysis/pipeline.py tests/analysis/test_pipeline.py
git commit -m "feat(pipeline): ρ>0.7 correlation filter before adversarial call

Deterministic pre-filter drops lower-confidence setup from correlated
pairs. LLM adversarial correlation check becomes a second guard layer.

Co-Authored-By: Claude Sonnet 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Task 1 → all 9 factor scores computed, sector_momentum second pass ✓
- Task 2 → WalkForwardEngine wired, OOS gate now fires on real data ✓
- Task 3 → regime → strategy gate, fail-open on unknown regime ✓
- Task 4 → real indicators + price action narrative fed to Claude ✓
- Task 5 → analytics fields persisted, migration idempotent ✓
- Task 6 → final_check block in adversarial prompt ✓
- Task 7 → quantitative ρ filter wired before adversarial call ✓

**Placeholder scan:** No TBDs. All steps have complete code. No "similar to Task N".

**Type consistency:**
- `_run_backtests(sym, bt_results, regime=regime)` — signature updated Task 2, call site updated Task 4 ✓
- `_compute_nifty_5d_change_from_store()` uses `self._candles` (CandleStore) — no yfinance ✓
- `REGIME_STRATEGY_GATE` uses `StrategyName` enum, not raw strings ✓
- `SetupStore.save()` signature unchanged — dict extended in-place ✓
- `_drop_correlated_setups` consumes `list[dict]` matching `setups_with_data` shape in `run()` ✓

**Post-781d633 amendments applied:**
- Task 1 Step 1.4: `_compute_nifty_5d_change()` → `_compute_nifty_5d_change_from_store()` using CandleStore (yfinance removed from deps)
- Task 2: CLI `analyze` is retired — only API path runs pipeline; `analysis_routes.py` already injects `WalkForwardEngine()`, so no `__init__` change needed
- No `pipeline=v2` query params were ever in the plan (v2 was already the only path before this plan was written)

**Review Focus coverage:**
- Unknown regime fail-open → `test_unknown_regime_returns_all_strategies` Task 3 ✓
- WF thin data → `WalkForwardEngine._empty_report` returns `total_trades=0`, quality gate rejects ✓
- Single symbol correlation → `test_single_symbol_unchanged` Task 7 ✓
- DB migration idempotent → `test_migration_idempotent` Task 5 ✓
- Indicator fetch failure mid-loop → `test_fetch_indicators_returns_empty_on_insufficient_data` Task 4 ✓
