# yfinance Data Layer Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Kite-based data sync with yfinance for all historical OHLCV, eliminating the 35-minute sync step and enabling 5+ years of backtest data.

**Architecture:** New `MarketDataProvider` wraps yfinance with the same DataFrame contract the pipeline expects. Pipeline takes a provider instead of CandleStore/InstrumentCache. Kite stays for live trading only (orders, positions, margins, ticks). No local DB for market data — all fetched on demand, optionally cached in memory for same-session re-use.

**Tech Stack:** yfinance 1.7+, pandas, existing pipeline/screening/backtest code unchanged.

**Spec:** This plan implements the analysis from the preceding conversation — replacing Kite sync with yfinance while keeping all screening, strategy, backtesting, and execution code intact.

## Global Constraints

- Python 3.13, yfinance 1.7.0 already installed in .venv
- yfinance NSE symbols use `.NS` suffix (e.g., `RELIANCE.NS`)
- yfinance index tickers: `^NSEI` (NIFTY 50), `^NSEBANK` (NIFTY BANK), `^INDIAVIX` (India VIX)
- yfinance returns capitalized columns (`Open, High, Low, Close, Volume`) — all downstream code expects lowercase
- yfinance intraday limited to 60 days history; daily unlimited
- Kite `instruments("NSE")` still used for stock universe (1 API call, fast) since yfinance has no stock list endpoint
- Batch `yf.download()` for OHLCV — never per-stock sequential calls
- No new DB files — market data lives in memory, not SQLite

## Review Focus

1. **Symbol mapping failures** — yfinance uses `RELIANCE.NS` but some NSE symbols have special characters (e.g., `M&M` → `M%26M.NS` or `M&M.NS`). Test with known problematic tickers.
2. **Market hours data availability** — yfinance may return partial data for the current trading day. Pipeline should handle today's row being incomplete (NaN volume).
3. **Rate limiting / Yahoo blocks** — yfinance can get rate-limited under aggressive batch usage. Provider should handle HTTP 429 with backoff.
4. **DataFrame column mismatch** — If `.rename(columns=str.lower)` misses a column (e.g., `Adj Close`), downstream code that does `df["close"]` would KeyError.
5. **Empty data for delisted/renamed symbols** — yfinance returns empty DataFrame for symbols it doesn't recognize. Screening should skip gracefully, not crash.

---

### Task 1: MarketDataProvider — yfinance wrapper

**Files:**
- Create: `tradingbot/data/market_data_provider.py`
- Create: `tests/data/test_market_data_provider.py`
- Create: `tests/data/__init__.py`

**Interfaces:**
- Consumes: yfinance library, stock symbol strings
- Produces: `MarketDataProvider` with methods:
  - `get_universe() -> list[dict]` — returns instrument list from Kite (1 call)
  - `get_daily_batch(symbols: list[str], days: int) -> dict[str, pd.DataFrame]` — batch daily OHLCV
  - `get_intraday(symbol: str, interval: str, days: int) -> pd.DataFrame` — single stock intraday
  - `get_intraday_batch(symbols: list[str], interval: str, days: int) -> dict[str, pd.DataFrame]` — batch intraday
  - `get_index(name: str, days: int) -> pd.DataFrame` — index/VIX data
  - `to_nse_symbol(symbol: str) -> str` — convert `RELIANCE` to `RELIANCE.NS`
  - `from_nse_symbol(yf_symbol: str) -> str` — convert `RELIANCE.NS` to `RELIANCE`

All DataFrames have lowercase columns (`open, high, low, close, volume`) and DatetimeIndex.

- [ ] **Step 1: Write failing tests for symbol mapping**

```python
# tests/data/test_market_data_provider.py
import pytest
from tradingbot.data.market_data_provider import MarketDataProvider


def test_to_nse_symbol():
    p = MarketDataProvider()
    assert p.to_nse_symbol("RELIANCE") == "RELIANCE.NS"
    assert p.to_nse_symbol("M&M") == "M&M.NS"
    assert p.to_nse_symbol("RELIANCE.NS") == "RELIANCE.NS"  # idempotent


def test_from_nse_symbol():
    p = MarketDataProvider()
    assert p.from_nse_symbol("RELIANCE.NS") == "RELIANCE"
    assert p.from_nse_symbol("M&M.NS") == "M&M"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/data/test_market_data_provider.py -v`
Expected: FAIL with "No module named"

- [ ] **Step 3: Write MarketDataProvider core**

```python
# tradingbot/data/market_data_provider.py
"""Market data provider using yfinance for historical OHLCV."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

_INDEX_MAP = {
    "NIFTY 50": "^NSEI",
    "NIFTY BANK": "^NSEBANK",
    "INDIA VIX": "^INDIAVIX",
}


class MarketDataProvider:
    """Fetches OHLCV data from yfinance. All DataFrames use lowercase columns."""

    def __init__(self, kite_client: Any = None):
        self._kite = kite_client
        self._cache: dict[str, pd.DataFrame] = {}

    @staticmethod
    def to_nse_symbol(symbol: str) -> str:
        if symbol.endswith(".NS"):
            return symbol
        return f"{symbol}.NS"

    @staticmethod
    def from_nse_symbol(yf_symbol: str) -> str:
        return yf_symbol.removesuffix(".NS")

    @staticmethod
    def _normalize(df: pd.DataFrame) -> pd.DataFrame:
        df = df.rename(columns=str.lower)
        keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
        return df[keep]

    def get_universe(self) -> list[dict[str, Any]]:
        """Get NSE equity instrument list from Kite (1 API call).
        Falls back to empty list if Kite not available."""
        if self._kite is None:
            log.warning("No Kite client — universe unavailable")
            return []
        try:
            raw = self._kite.kite.instruments("NSE")
            return [
                {
                    "symbol": i["tradingsymbol"],
                    "token": i["instrument_token"],
                    "exchange": "NSE",
                    "lot_size": i.get("lot_size", 1),
                    "tick_size": i.get("tick_size", 0.05),
                    "sector": i.get("industry_type") or "unknown",
                }
                for i in raw
                if i.get("instrument_type") == "EQ" and i.get("segment") == "NSE"
            ]
        except Exception as exc:
            log.error("Failed to fetch instruments from Kite: %s", exc)
            return []

    def get_daily_batch(
        self, symbols: list[str], days: int = 365
    ) -> dict[str, pd.DataFrame]:
        """Batch download daily OHLCV for multiple symbols."""
        if not symbols:
            return {}
        yf_symbols = [self.to_nse_symbol(s) for s in symbols]
        period = f"{days}d" if days <= 730 else f"{days // 365}y"
        try:
            raw = yf.download(
                yf_symbols, period=period, interval="1d",
                progress=False, threads=True,
            )
        except Exception as exc:
            log.error("yfinance batch download failed: %s", exc)
            return {}

        result: dict[str, pd.DataFrame] = {}
        if isinstance(raw.columns, pd.MultiIndex):
            for yf_sym in yf_symbols:
                try:
                    df = raw.xs(yf_sym, level=1, axis=1).dropna(how="all")
                    if not df.empty:
                        result[self.from_nse_symbol(yf_sym)] = self._normalize(df)
                except KeyError:
                    continue
        elif len(yf_symbols) == 1:
            df = raw.dropna(how="all")
            if not df.empty:
                result[symbols[0]] = self._normalize(df)
        return result

    def get_intraday(
        self, symbol: str, interval: str = "15m", days: int = 60
    ) -> pd.DataFrame:
        """Fetch intraday candles for a single symbol."""
        cache_key = f"{symbol}:{interval}:{days}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        yf_sym = self.to_nse_symbol(symbol)
        try:
            ticker = yf.Ticker(yf_sym)
            df = ticker.history(period=f"{days}d", interval=interval)
            df = self._normalize(df)
            self._cache[cache_key] = df
            return df
        except Exception as exc:
            log.warning("Intraday fetch failed for %s: %s", symbol, exc)
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    def get_intraday_batch(
        self, symbols: list[str], interval: str = "15m", days: int = 60
    ) -> dict[str, pd.DataFrame]:
        """Batch download intraday candles."""
        if not symbols:
            return {}
        yf_symbols = [self.to_nse_symbol(s) for s in symbols]
        try:
            raw = yf.download(
                yf_symbols, period=f"{days}d", interval=interval,
                progress=False, threads=True,
            )
        except Exception as exc:
            log.error("yfinance intraday batch failed: %s", exc)
            return {}

        result: dict[str, pd.DataFrame] = {}
        if isinstance(raw.columns, pd.MultiIndex):
            for yf_sym in yf_symbols:
                try:
                    df = raw.xs(yf_sym, level=1, axis=1).dropna(how="all")
                    if not df.empty:
                        result[self.from_nse_symbol(yf_sym)] = self._normalize(df)
                except KeyError:
                    continue
        elif len(yf_symbols) == 1:
            df = raw.dropna(how="all")
            if not df.empty:
                result[symbols[0]] = self._normalize(df)
        return result

    def get_index(self, name: str, days: int = 120) -> pd.DataFrame:
        """Fetch index or VIX daily data."""
        yf_sym = _INDEX_MAP.get(name, name)
        try:
            ticker = yf.Ticker(yf_sym)
            df = ticker.history(period=f"{days}d")
            return self._normalize(df)
        except Exception as exc:
            log.warning("Index fetch failed for %s: %s", name, exc)
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    def clear_cache(self) -> None:
        self._cache.clear()
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/data/test_market_data_provider.py -v`
Expected: PASS

- [ ] **Step 5: Write integration test that hits yfinance**

```python
# tests/data/test_market_data_provider.py (append)
import pandas as pd


@pytest.mark.integration
def test_get_daily_batch_real():
    p = MarketDataProvider()
    result = p.get_daily_batch(["RELIANCE", "TCS"], days=30)
    assert "RELIANCE" in result
    assert "TCS" in result
    df = result["RELIANCE"]
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) > 15


@pytest.mark.integration
def test_get_index_real():
    p = MarketDataProvider()
    df = p.get_index("NIFTY 50", days=30)
    assert len(df) > 15
    assert "close" in df.columns


@pytest.mark.integration
def test_get_intraday_real():
    p = MarketDataProvider()
    df = p.get_intraday("RELIANCE", interval="15m", days=10)
    assert len(df) > 10
    assert "close" in df.columns
```

- [ ] **Step 6: Run integration tests**

Run: `pytest tests/data/test_market_data_provider.py -v -m integration`
Expected: PASS (requires internet)

- [ ] **Step 7: Commit**

```bash
git add tradingbot/data/market_data_provider.py tests/data/
git commit -m "feat(data): add MarketDataProvider wrapping yfinance"
```

---

### Task 2: Refactor MarketContextFetcher to use provider

**Files:**
- Modify: `tradingbot/scanner/market_context.py` — replace CandleStore with MarketDataProvider
- Modify: `tests/analysis/test_pipeline.py` (if it tests market context)

**Interfaces:**
- Consumes: `MarketDataProvider.get_index(name, days)` from Task 1
- Produces: Same `MarketContext` as before — no downstream changes

- [ ] **Step 1: Write failing test**

```python
# tests/scanner/test_market_context_provider.py
from unittest.mock import MagicMock
import pandas as pd
import pytest
from tradingbot.scanner.market_context import MarketContextFetcher


def _mock_provider():
    provider = MagicMock()
    dates = pd.date_range("2026-08-01", periods=60, freq="B")
    nifty_close = pd.Series([24000 + i * 10 for i in range(60)], index=dates)
    df = pd.DataFrame({
        "open": nifty_close - 50,
        "high": nifty_close + 50,
        "low": nifty_close - 100,
        "close": nifty_close,
        "volume": [1000000] * 60,
    }, index=dates)
    provider.get_index.return_value = df
    return provider


def test_fetch_uses_provider():
    provider = _mock_provider()
    fetcher = MarketContextFetcher(market_data_provider=provider)
    ctx = fetcher.fetch()
    assert ctx.nifty_level > 0
    assert provider.get_index.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/scanner/test_market_context_provider.py -v`
Expected: FAIL (MarketContextFetcher doesn't accept market_data_provider yet)

- [ ] **Step 3: Refactor MarketContextFetcher**

Update `__init__` to accept `market_data_provider` and use it for `_fetch_index_trend` and `_fetch_vix`. Keep `candle_store` as deprecated fallback for backward compat.

```python
# In market_context.py, update __init__:
def __init__(
    self,
    http_client: httpx.Client | None = None,
    candle_store: Any = None,
    market_data_provider: Any = None,
) -> None:
    self.http_client = http_client or httpx.Client(headers=BROWSER_HEADERS, timeout=10.0)
    self._candles = candle_store
    self._provider = market_data_provider

# Update _fetch_index_trend:
def _fetch_index_trend(self, symbol: str) -> tuple[float, bool, bool]:
    if self._provider is not None:
        try:
            df = self._provider.get_index(symbol, days=INDEX_LOOKBACK_DAYS)
            if df.empty or len(df) < 50:
                return 0.0, False, False
            closes = df["close"]
            last = float(closes.iloc[-1])
            sma20 = float(closes.rolling(20).mean().iloc[-1])
            sma50 = float(closes.rolling(50).mean().iloc[-1])
            return last, last > sma20, last > sma50
        except Exception as exc:
            logger.warning("Provider index fetch failed for %s: %s", symbol, exc)
    # Fallback to candle_store (deprecated path)
    if self._candles is not None:
        # ... existing code ...

# Update _fetch_vix similarly.
```

- [ ] **Step 4: Run test**

Run: `pytest tests/scanner/test_market_context_provider.py -v`
Expected: PASS

- [ ] **Step 5: Run existing tests to verify no regression**

Run: `pytest tests/ -x --tb=short -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add tradingbot/scanner/market_context.py tests/scanner/
git commit -m "refactor(scanner): MarketContextFetcher accepts MarketDataProvider"
```

---

### Task 3: Refactor AnalysisPipeline to use provider

**Files:**
- Modify: `tradingbot/analysis/pipeline.py` — replace CandleStore/InstrumentCache reads with provider calls
- Create: `tests/analysis/test_pipeline_provider.py`

**Interfaces:**
- Consumes: `MarketDataProvider` from Task 1 — `get_universe()`, `get_daily_batch()`, `get_intraday()`, `get_index()`
- Produces: Same `AnalysisRun` — no downstream changes

The three methods that read from CandleStore:
1. `_build_stock_metrics()` — reads daily candles per stock → use `get_daily_batch()` for all at once
2. `_fetch_indicators_for_symbol()` — reads 15min candles → use `get_intraday()`
3. `_run_backtests()` — reads 15min candles → use `get_intraday()` (cached from step 2)
4. `_compute_nifty_5d_change_from_store()` — reads NIFTY daily → use `get_index()`

- [ ] **Step 1: Write failing test**

```python
# tests/analysis/test_pipeline_provider.py
from unittest.mock import MagicMock, AsyncMock
import pandas as pd
import pytest
from tradingbot.data.market_data_provider import MarketDataProvider


def test_pipeline_accepts_provider():
    """Pipeline constructor should accept market_data_provider kwarg."""
    from tradingbot.analysis.pipeline import AnalysisPipeline
    provider = MagicMock(spec=MarketDataProvider)
    pipeline = AnalysisPipeline(
        data_sync=None, candle_store=None, screener=MagicMock(),
        tier2=MagicMock(), tier3=MagicMock(), backtest_engine=MagicMock(),
        monte_carlo=MagicMock(), quality_gates=MagicMock(),
        run_store=MagicMock(), setup_store=MagicMock(),
        event_bus=MagicMock(), capital=100000,
        market_data_provider=provider,
    )
    assert pipeline._provider is provider
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/analysis/test_pipeline_provider.py -v`

- [ ] **Step 3: Add provider to pipeline constructor**

In `pipeline.py.__init__`, add `market_data_provider: Any = None` parameter:

```python
def __init__(
    self,
    data_sync: Any,
    candle_store: Any,
    screener: Any,
    # ... existing params ...
    market_data_provider: Any = None,
):
    # ... existing assignments ...
    self._provider = market_data_provider
```

- [ ] **Step 4: Refactor `_build_stock_metrics` to use batch download**

Replace the per-stock `self._candles.read()` loop with:

```python
def _build_stock_metrics(self, nifty_5d_change=0.0, delivery_data=None):
    # Get universe
    if self._provider is not None:
        instruments = self._provider.get_universe()
    elif self._instrument_cache is not None:
        instruments = self._instrument_cache.get_all()
    else:
        return []

    if not instruments:
        return []

    symbols = [inst["symbol"] for inst in instruments]

    # Batch fetch 30d daily candles for all symbols at once
    if self._provider is not None:
        daily_data = self._provider.get_daily_batch(symbols, days=30)
    else:
        # Legacy CandleStore path
        daily_data = {}
        for sym in symbols:
            df = self._candles.read(sym, "day", from_dt, now)
            if not df.empty:
                daily_data[sym] = df

    # ... rest of metrics computation stays the same,
    # but reads from daily_data[symbol] instead of self._candles.read()
```

- [ ] **Step 5: Refactor `_fetch_indicators_for_symbol` and `_run_backtests`**

Both methods read 15min candles. Replace `self._candles.read()` with `self._provider.get_intraday()`:

```python
def _fetch_indicators_for_symbol(self, symbol: str) -> tuple[dict, str]:
    if self._provider is not None:
        df = self._provider.get_intraday(symbol, "15m", days=60)
    else:
        df = self._candles.read(symbol, "15minute", ...)
    # ... rest stays the same
```

- [ ] **Step 6: Refactor `_compute_nifty_5d_change_from_store`**

```python
def _compute_nifty_5d_change(self) -> float:
    try:
        if self._provider is not None:
            df = self._provider.get_index("NIFTY 50", days=10)
        else:
            df = self._candles.read("NIFTY 50", "day", ...)
        if len(df) >= 6:
            return float((df["close"].iloc[-1] / df["close"].iloc[-6] - 1) * 100)
    except Exception:
        pass
    return 0.0
```

- [ ] **Step 7: Remove `deep_fetch` call**

Line 159-160: `if symbols and hasattr(self._sync, "deep_fetch")` — skip when provider is set:

```python
if self._provider is None and symbols and hasattr(self._sync, "deep_fetch"):
    self._sync.deep_fetch(symbols)
```

- [ ] **Step 8: Run all tests**

Run: `pytest tests/ --tb=short -q`
Expected: All pass (both old CandleStore path and new provider path work)

- [ ] **Step 9: Commit**

```bash
git add tradingbot/analysis/pipeline.py tests/analysis/
git commit -m "refactor(pipeline): support MarketDataProvider for OHLCV data"
```

---

### Task 4: Wire provider in API routes + remove sync endpoint

**Files:**
- Modify: `tradingbot/api/analysis_routes.py` — wire provider, remove sync routes
- Modify: `tradingbot/api/state.py` — remove sync fields
- Modify: `web/src/app/analysis/page.tsx` — remove SyncButton
- Modify: `web/src/lib/api.ts` — remove sync API calls
- Remove: `web/src/components/analysis/sync-button.tsx`

**Interfaces:**
- Consumes: `MarketDataProvider` from Task 1, refactored pipeline from Task 3
- Produces: Same API responses — frontend sees no change except sync button gone

- [ ] **Step 1: Update `_run_analysis` to create provider instead of CandleStore/InstrumentCache**

In `analysis_routes.py`, replace:
```python
instrument_cache = InstrumentCache(data_dir / "instruments.db")
candle_store = CandleStore(data_dir / "candles.db")
```
With:
```python
from tradingbot.data.market_data_provider import MarketDataProvider
kite_for_universe = None
if state.kite_auth and state.kite_auth.is_authenticated():
    from tradingbot.data.kite_client import KiteClient
    kite_for_universe = KiteClient(
        state.kite_auth.kite,
        rate_limit_per_sec=config.kite.rate_limit_per_sec,
    )
provider = MarketDataProvider(kite_client=kite_for_universe)
```

Update pipeline construction:
```python
pipeline = AnalysisPipeline(
    data_sync=None,
    candle_store=None,
    screener=Tier1Screener(config.screening, candle_store=None),
    # ... other params unchanged ...
    market_data_provider=provider,
    context_fetcher=MarketContextFetcher(market_data_provider=provider),
)
```

- [ ] **Step 2: Remove sync endpoint and state fields**

Delete from `analysis_routes.py`:
- `start_sync()` function and route
- `sync_status()` function and route
- `_run_sync_subprocess()` and `_sync_worker()`

Delete from `state.py`:
- `sync_status`, `sync_task`, `sync_progress` fields

- [ ] **Step 3: Remove SyncButton from frontend**

Remove the `<SyncButton />` component from `analysis/page.tsx`.
Remove `web/src/components/analysis/sync-button.tsx`.
Remove `postSync` and `getSyncStatus` from `web/src/lib/api.ts`.
Remove `SyncStatus` from `web/src/types.ts` (if defined there).

- [ ] **Step 4: Run tests**

Run: `pytest tests/ --tb=short -q`
Expected: All pass

- [ ] **Step 5: Build frontend**

Run: `cd web && npx next build`
Expected: Clean build

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(data): wire yfinance provider, remove Kite sync endpoint

Analysis pipeline now fetches OHLCV from yfinance on demand (~30s)
instead of pre-syncing from Kite (~35 min). No more Sync Data button.
Kite used only for stock universe list and live trading.
"
```

---

### Task 5: Cleanup — remove obsolete data files

**Files:**
- Remove: `tradingbot/data/data_sync.py`
- Remove: `tradingbot/data/instrument_cache.py`
- Remove: `tradingbot/data/candle_store.py`
- Modify: `tradingbot/data/__init__.py` (if it re-exports removed modules)
- Remove: related tests for sync/cache/store
- Modify: `tradingbot/screening/screener.py` — remove CandleStore constructor param if unused

**Interfaces:**
- Consumes: nothing new
- Produces: cleaner codebase — no dead code

- [ ] **Step 1: Grep for remaining imports of removed modules**

```bash
grep -rn "from tradingbot.data.data_sync\|from tradingbot.data.candle_store\|from tradingbot.data.instrument_cache" tradingbot/ tests/ --include="*.py"
```

Fix any remaining imports. The pipeline and market_context should already use provider (Tasks 2-4). Any remaining references are dead code.

- [ ] **Step 2: Remove files**

```bash
rm tradingbot/data/data_sync.py
rm tradingbot/data/instrument_cache.py
rm tradingbot/data/candle_store.py
```

- [ ] **Step 3: Run all tests**

Run: `pytest tests/ --tb=short -q`
Expected: All pass — no test should depend on removed files after Tasks 1-4

- [ ] **Step 4: Build frontend**

Run: `cd web && npx next build`
Expected: Clean build

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove obsolete Kite sync data layer

Removed data_sync.py, instrument_cache.py, candle_store.py.
All OHLCV data now flows through MarketDataProvider (yfinance).
instruments.db and candles.db files no longer created or needed.
"
```
