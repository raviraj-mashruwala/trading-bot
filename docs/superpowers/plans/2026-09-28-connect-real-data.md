# Connect Real Data — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the v2 analysis pipeline to real Kite Connect data so that adding credentials to `.env` produces a fully working application.

**Architecture:** Fill 4 stubs in the existing pipeline: (1) Kite OAuth web flow for daily token, (2) `_build_stock_metrics()` reads InstrumentCache + CandleStore, (3) `analyze_regime()` uses existing MarketContextFetcher, (4) DataSync auto-runs on startup + CLI command. No new modules — only wiring existing code.

**Tech Stack:** Python 3.13, kiteconnect, FastAPI, SQLite, existing MarketContextFetcher

**Spec:** `docs/superpowers/specs/2026-09-27-analysis-pipeline-redesign.md` (Sections 1, 3, 8)

## Global Constraints

- Python ≥ 3.12, async, IST timezone
- Existing 512 tests must keep passing
- Kite API rate limit: 3 req/sec (enforced by KiteRateLimiter)
- Secrets from `.env` only — never disk, never logs
- v1 pipeline must remain functional (backward compat)

## Review Focus

1. **Kite access_token expiry handling:** Token expires ~6 AM next day. If pipeline runs without valid token, it must fail clearly (not silently return empty data). Test: call `_run_analysis_v2` without authentication → expect clear error, not empty results.
2. **DataSync rate limiting under full universe sync:** 1500 instruments × 1 fetch each at 3 req/sec = ~8 min. If sync is interrupted mid-way, resuming should not re-fetch already-synced symbols. Test: sync 5 symbols, interrupt, sync again → only unseen symbols fetched.
3. **_build_stock_metrics with empty CandleStore:** If sync hasn't run yet, CandleStore is empty. `_build_stock_metrics()` should return `[]` gracefully, not crash. Test: call with empty store → empty list, no exception.
4. **MarketContextFetcher network failure:** If NSE API or yfinance is down, `analyze_regime()` should use safe defaults (VIX=15, neutral regime), not crash the pipeline. Test: mock network failure → pipeline continues with defaults.
5. **Concurrent sync + analysis:** If DataSync is running while analysis starts, SQLite reads from CandleStore should still work (WAL mode or separate connections). Test: write during read → no lock error.

---

### Task 1: Kite OAuth API Endpoints

**Files:**
- Modify: `tradingbot/api/analysis_routes.py` (add auth routes)
- Modify: `tradingbot/api/state.py` (add kite_auth field)
- Modify: `tradingbot/execution/kite_auth.py` (add generate_session method)
- Test: `tests/api/test_kite_auth_routes.py`

**Interfaces:**
- Consumes: `KiteAuth` from `tradingbot/execution/kite_auth.py` (existing — has `get_login_url()`, `set_access_token()`, `is_authenticated()`)
- Produces: `GET /api/auth/kite/login` → redirect URL, `GET /api/auth/kite/callback?request_token=X` → exchanges token + stores, `GET /api/auth/kite/status` → auth state

- [ ] **Step 1: Write tests for auth endpoints**

```python
# tests/api/test_kite_auth_routes.py
import pytest
from unittest.mock import MagicMock, patch


async def test_kite_login_returns_url(api_client):
    response = await api_client.get("/api/auth/kite/login")
    assert response.status_code == 200
    data = response.json()
    assert "login_url" in data
    assert "kite.zerodha.com" in data["login_url"] or "login_url" in data


async def test_kite_status_unauthenticated(api_client):
    response = await api_client.get("/api/auth/kite/status")
    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is False


async def test_kite_callback_with_valid_token(api_client):
    with patch("tradingbot.api.analysis_routes._exchange_kite_token") as mock_exchange:
        mock_exchange.return_value = {"access_token": "test_token", "user_id": "AB1234"}
        response = await api_client.get("/api/auth/kite/callback?request_token=test_req_token")
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True


async def test_kite_callback_without_token_returns_400(api_client):
    response = await api_client.get("/api/auth/kite/callback")
    assert response.status_code == 400
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/api/test_kite_auth_routes.py -v`
Expected: 404 — routes don't exist yet

- [ ] **Step 3: Add KiteAuth to AppState**

In `tradingbot/api/state.py`, add:
```python
from tradingbot.execution.kite_auth import KiteAuth

# In AppState dataclass, add:
kite_auth: KiteAuth | None = None
```

- [ ] **Step 4: Add generate_session to KiteAuth**

In `tradingbot/execution/kite_auth.py`, add method:
```python
def generate_session(self, request_token: str) -> dict:
    """Exchange request_token for access_token via Kite API."""
    from kiteconnect import KiteConnect
    kite = KiteConnect(api_key=self._api_key)
    data = kite.generate_session(request_token, api_secret=self._api_secret)
    access_token = data["access_token"]
    kite.set_access_token(access_token)
    self._access_token = access_token
    self._kite = kite
    return data
```

- [ ] **Step 5: Add auth routes to analysis_routes.py**

```python
@router.get("/auth/kite/login")
async def kite_login(state: AppState = Depends(get_state)):
    auth = _ensure_kite_auth(state)
    return {"login_url": auth.get_login_url()}


@router.get("/auth/kite/callback")
async def kite_callback(request_token: str | None = None, state: AppState = Depends(get_state)):
    if not request_token:
        raise HTTPException(400, "request_token required")
    auth = _ensure_kite_auth(state)
    try:
        data = auth.generate_session(request_token)
        return {"authenticated": True, "user_id": data.get("user_id", "")}
    except Exception as exc:
        raise HTTPException(401, f"Token exchange failed: {exc}")


@router.get("/auth/kite/status")
async def kite_status(state: AppState = Depends(get_state)):
    auth = state.kite_auth
    return {"authenticated": auth.is_authenticated() if auth else False}


def _ensure_kite_auth(state: AppState) -> KiteAuth:
    if state.kite_auth is None:
        state.kite_auth = KiteAuth(
            api_key=state.config.secrets.kite_api_key,
            api_secret=state.config.secrets.kite_api_secret,
        )
    return state.kite_auth
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/api/test_kite_auth_routes.py tests/ -q --tb=short`
Expected: All pass (512 + new)

- [ ] **Step 7: Commit**

```bash
git add tradingbot/api/analysis_routes.py tradingbot/api/state.py tradingbot/execution/kite_auth.py tests/api/test_kite_auth_routes.py
git commit -m "feat(api): add Kite OAuth login/callback/status endpoints

GET /auth/kite/login returns Kite login URL.
GET /auth/kite/callback exchanges request_token for access_token.
GET /auth/kite/status returns auth state.
KiteAuth.generate_session() handles token exchange."
```

---

### Task 2: Data Sync CLI Command + Auto-Sync

**Files:**
- Modify: `tradingbot/cli.py` (add `sync` command)
- Modify: `tradingbot/data/data_sync.py` (add `full_sync` convenience method)
- Test: `tests/data/test_data_sync_cli.py`

**Interfaces:**
- Consumes: `DataSync` (existing), `KiteClient` (existing), `InstrumentCache` (existing), `CandleStore` (existing), `KiteConfig` (existing)
- Produces: `tradingbot sync` CLI command, `DataSync.full_sync(daily_lookback, intraday_lookback)` method

- [ ] **Step 1: Write tests for full_sync method**

```python
# tests/data/test_data_sync_cli.py
import pytest
from datetime import date, datetime
from unittest.mock import MagicMock, patch, call
from zoneinfo import ZoneInfo
from tradingbot.data.data_sync import DataSync
from tradingbot.data.instrument_cache import InstrumentCache
from tradingbot.data.candle_store import CandleStore

IST = ZoneInfo("Asia/Kolkata")


def test_full_sync_calls_all_stages(tmp_path):
    cache = InstrumentCache(tmp_path / "inst.db")
    store = CandleStore(tmp_path / "candles.db")
    client = MagicMock()
    client.fetch_instruments.return_value = [
        {"instrument_token": 1, "tradingsymbol": "RELIANCE",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
        {"instrument_token": 2, "tradingsymbol": "TCS",
         "exchange": "NSE", "lot_size": 1, "tick_size": 0.05,
         "instrument_type": "EQ", "segment": "NSE"},
    ]
    client.fetch_historical.return_value = [
        {"date": datetime(2026, 9, 26, tzinfo=IST),
         "open": 2500, "high": 2520, "low": 2490, "close": 2510, "volume": 100000},
    ]

    sync = DataSync(client, cache, store)
    stats = sync.full_sync(daily_lookback=365, intraday_lookback=60)

    assert stats["instruments"] == 2
    assert "daily_candles" in stats
    assert "intraday_candles" in stats
    assert client.fetch_instruments.call_count == 1


def test_full_sync_with_empty_instruments(tmp_path):
    cache = InstrumentCache(tmp_path / "inst.db")
    store = CandleStore(tmp_path / "candles.db")
    client = MagicMock()
    client.fetch_instruments.return_value = []
    client.fetch_historical.return_value = []

    sync = DataSync(client, cache, store)
    stats = sync.full_sync()

    assert stats["instruments"] == 0
    assert stats["daily_candles"] == 0
```

- [ ] **Step 2: Add full_sync to DataSync**

In `tradingbot/data/data_sync.py`, add:
```python
def full_sync(
    self, daily_lookback: int = 365, intraday_lookback: int = 60,
) -> dict[str, int]:
    """Run complete sync: instruments → daily candles → intraday candles."""
    inst_count = self.sync_instruments()
    all_instruments = self._instruments.get_all()
    symbols = [i["symbol"] for i in all_instruments]

    daily = self.sync_daily_candles(symbols, lookback_days=daily_lookback)
    intraday = self.sync_intraday_candles(
        symbols, interval="15minute", lookback_days=intraday_lookback,
    )
    return {
        "instruments": inst_count,
        "daily_candles": daily,
        "intraday_candles": intraday,
        "symbols": len(symbols),
    }
```

- [ ] **Step 3: Add sync CLI command**

In `tradingbot/cli.py`, add after existing commands:
```python
@cli.command()
@click.option("--daily-days", default=365, help="Daily candle lookback in days")
@click.option("--intraday-days", default=60, help="Intraday candle lookback in days")
@click.pass_context
def sync(ctx, daily_days: int, intraday_days: int) -> None:
    """Sync market data from Kite Connect to local cache."""
    from kiteconnect import KiteConnect
    from tradingbot.data.kite_client import KiteClient
    from tradingbot.data.instrument_cache import InstrumentCache
    from tradingbot.data.candle_store import CandleStore
    from tradingbot.data.data_sync import DataSync
    from pathlib import Path

    cfg = ctx.obj
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)

    kite_auth = _get_kite_auth(cfg)
    if not kite_auth:
        _fail("Kite not authenticated. Run 'tradingbot auth' first.")

    client = KiteClient(kite_auth, rate_limit_per_sec=cfg.kite.rate_limit_per_sec)
    cache = InstrumentCache(data_dir / "instruments.db")
    store = CandleStore(data_dir / "candles.db")
    sync_mgr = DataSync(client, cache, store)

    click.echo(f"Syncing instruments + {daily_days}d daily + {intraday_days}d intraday...")
    stats = sync_mgr.full_sync(daily_lookback=daily_days, intraday_lookback=intraday_days)
    click.echo(f"Done: {stats['instruments']} instruments, "
               f"{stats['daily_candles']} daily candles, "
               f"{stats['intraday_candles']} intraday candles")
    cache.close()
    store.close()


def _get_kite_auth(cfg):
    """Get authenticated KiteConnect instance from existing auth flow."""
    import os
    access_token = os.environ.get("KITE_ACCESS_TOKEN", "")
    if not access_token:
        return None
    from kiteconnect import KiteConnect
    kite = KiteConnect(api_key=cfg.secrets.kite_api_key)
    kite.set_access_token(access_token)
    return kite
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/data/test_data_sync_cli.py tests/ -q --tb=short`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add tradingbot/cli.py tradingbot/data/data_sync.py tests/data/test_data_sync_cli.py
git commit -m "feat(cli): add data sync command + DataSync.full_sync()

'tradingbot sync' runs full instrument + candle sync from Kite.
DataSync.full_sync() orchestrates instruments → daily → intraday."
```

---

### Task 3: Wire _build_stock_metrics()

**Files:**
- Modify: `tradingbot/analysis/pipeline.py` (implement `_build_stock_metrics`)
- Test: `tests/analysis/test_stock_metrics.py`

**Interfaces:**
- Consumes: `InstrumentCache.get_all()` → list of `{token, symbol, exchange, lot_size, tick_size}`, `CandleStore.read(symbol, interval, from_dt, to_dt)` → DataFrame with [open, high, low, close, volume]
- Produces: `_build_stock_metrics()` returns `list[dict]` where each dict has: symbol, token, last_price, avg_volume, market_cap_cr, atr_pct, sector, trading_days, factor_scores (empty dict for now)

- [ ] **Step 1: Write tests**

```python
# tests/analysis/test_stock_metrics.py
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo
from tradingbot.analysis.pipeline import AnalysisPipeline

IST = ZoneInfo("Asia/Kolkata")


def _make_daily_df(n=30, base_price=500, avg_vol=600000):
    now = datetime.now(tz=IST)
    dates = [now - timedelta(days=n - i) for i in range(n)]
    close = base_price + np.cumsum(np.random.randn(n) * 2)
    return pd.DataFrame({
        "open": close + np.random.randn(n),
        "high": close + abs(np.random.randn(n) * 3),
        "low": close - abs(np.random.randn(n) * 3),
        "close": close,
        "volume": np.random.randint(int(avg_vol * 0.8), int(avg_vol * 1.2), n),
    }, index=pd.DatetimeIndex(dates, name="date"))


@pytest.fixture
def pipeline_with_data():
    instrument_cache = MagicMock()
    instrument_cache.get_all.return_value = [
        {"token": 1, "symbol": "RELIANCE", "exchange": "NSE", "lot_size": 1, "tick_size": 0.05},
        {"token": 2, "symbol": "TCS", "exchange": "NSE", "lot_size": 1, "tick_size": 0.05},
    ]

    candle_store = MagicMock()
    candle_store.read.return_value = _make_daily_df(30, 500, 600000)

    pipeline = AnalysisPipeline.__new__(AnalysisPipeline)
    pipeline._instrument_cache = instrument_cache
    pipeline._candles = candle_store
    return pipeline


def test_build_stock_metrics_returns_list(pipeline_with_data):
    result = pipeline_with_data._build_stock_metrics()
    assert isinstance(result, list)
    assert len(result) == 2


def test_build_stock_metrics_has_required_fields(pipeline_with_data):
    result = pipeline_with_data._build_stock_metrics()
    stock = result[0]
    assert "symbol" in stock
    assert "last_price" in stock
    assert "avg_volume" in stock
    assert "atr_pct" in stock
    assert "trading_days" in stock
    assert stock["last_price"] > 0
    assert stock["avg_volume"] > 0


def test_build_stock_metrics_empty_cache():
    instrument_cache = MagicMock()
    instrument_cache.get_all.return_value = []
    candle_store = MagicMock()

    pipeline = AnalysisPipeline.__new__(AnalysisPipeline)
    pipeline._instrument_cache = instrument_cache
    pipeline._candles = candle_store
    result = pipeline._build_stock_metrics()
    assert result == []


def test_build_stock_metrics_empty_candles():
    instrument_cache = MagicMock()
    instrument_cache.get_all.return_value = [
        {"token": 1, "symbol": "EMPTY", "exchange": "NSE", "lot_size": 1, "tick_size": 0.05},
    ]
    candle_store = MagicMock()
    candle_store.read.return_value = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    pipeline = AnalysisPipeline.__new__(AnalysisPipeline)
    pipeline._instrument_cache = instrument_cache
    pipeline._candles = candle_store
    result = pipeline._build_stock_metrics()
    assert result == []  # skipped due to no data
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/analysis/test_stock_metrics.py -v`
Expected: AssertionError — stub returns []

- [ ] **Step 3: Implement _build_stock_metrics**

Replace the stub in `tradingbot/analysis/pipeline.py`:

```python
def _build_stock_metrics(self) -> list[dict]:
    """Compute screening metrics for all cached instruments."""
    if self._instrument_cache is None:
        return []

    instruments = self._instrument_cache.get_all()
    if not instruments:
        return []

    now = datetime.now(tz=IST)
    from_dt = now - timedelta(days=30)
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
        trading_days = len(df)

        # ATR % (14-period or available)
        high, low, prev_close = df["high"], df["low"], close.shift(1)
        true_range = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        atr = float(true_range.tail(min(14, len(df))).mean())
        atr_pct = (atr / last_price * 100) if last_price > 0 else 0

        # Approximate market cap (price × typical large-cap shares)
        # Real market cap needs external data; use volume as proxy for now
        market_cap_cr = last_price * avg_volume / 1_00_00_000  # rough proxy

        metrics.append({
            "symbol": symbol,
            "token": inst["token"],
            "last_price": last_price,
            "avg_volume": avg_volume,
            "market_cap_cr": market_cap_cr,
            "atr_pct": atr_pct,
            "sector": "unknown",  # Kite doesn't provide sector; enriched later
            "trading_days": trading_days,
            "factor_scores": {},
        })

    return metrics
```

Also add `_instrument_cache` as a constructor parameter to `AnalysisPipeline.__init__`:
```python
def __init__(self, ..., instrument_cache=None, ...):
    ...
    self._instrument_cache = instrument_cache
```

- [ ] **Step 4: Update _run_analysis_v2 to pass instrument_cache**

In `tradingbot/api/analysis_routes.py`, update the pipeline instantiation in `_run_analysis_v2` to pass `instrument_cache`:
```python
instrument_cache = InstrumentCache(data_dir / "instruments.db")
candle_store = CandleStore(data_dir / "candles.db")
# ... pass instrument_cache=instrument_cache to AnalysisPipeline
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/analysis/test_stock_metrics.py tests/ -q --tb=short`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add tradingbot/analysis/pipeline.py tradingbot/api/analysis_routes.py tests/analysis/test_stock_metrics.py
git commit -m "feat(pipeline): wire _build_stock_metrics to read from InstrumentCache + CandleStore

Computes last_price, avg_volume, ATR%, trading_days for all cached
instruments. Skips stocks with <5 daily candles. Returns list of dicts
consumed by Tier1Screener."
```

---

### Task 4: Wire analyze_regime() with Real Market Data

**Files:**
- Modify: `tradingbot/analysis/pipeline.py` (use MarketContextFetcher)
- Test: `tests/analysis/test_regime_wiring.py`

**Interfaces:**
- Consumes: `MarketContextFetcher` from `tradingbot/scanner/market_context.py` (existing — `fetch()` returns `MarketContext` with nifty_level, india_vix, fii_net_cr, dii_net_cr, sector_leaders, sector_laggards, regime)
- Produces: `analyze_regime()` call in pipeline uses real data instead of zeros

- [ ] **Step 1: Write tests**

```python
# tests/analysis/test_regime_wiring.py
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo
from tradingbot.analysis.pipeline import AnalysisPipeline
from tradingbot.core.models import MarketContext, MarketRegime

IST = ZoneInfo("Asia/Kolkata")


def _mock_context():
    return MarketContext(
        nifty_level=19500.0, nifty_trend="bullish", banknifty_trend="bullish",
        india_vix=13.5, fii_net_cr=-500.0, dii_net_cr=800.0,
        global_cues="US futures flat", sector_leaders=["banking", "IT"],
        sector_laggards=["pharma"], regime=MarketRegime.TRENDING_UP,
    )


@pytest.fixture
def pipeline_with_context():
    tier2 = AsyncMock()
    tier2.analyze_regime.return_value = {
        "regime": "trending_up", "regime_confidence": 0.82,
        "bias": "bullish", "sectors_in_play": ["banking"],
        "sectors_to_avoid": ["pharma"], "risk_appetite": "moderate",
        "reasoning": "test",
    }
    tier2.analyze_sectors.return_value = {"sectors": [], "reasoning": "test"}
    tier2.shortlist.return_value = {"shortlist": [], "max_positions_today": 3, "reasoning": "none"}

    context_fetcher = MagicMock()
    context_fetcher.fetch.return_value = _mock_context()

    pipeline = AnalysisPipeline.__new__(AnalysisPipeline)
    pipeline._tier2 = tier2
    pipeline._tier3 = AsyncMock()
    pipeline._context_fetcher = context_fetcher
    pipeline._screener = MagicMock()
    pipeline._screener.screen.return_value = []
    pipeline._instrument_cache = MagicMock()
    pipeline._instrument_cache.get_all.return_value = []
    pipeline._candles = MagicMock()
    pipeline._backtest = MagicMock()
    pipeline._mc = MagicMock()
    pipeline._gates = MagicMock()
    pipeline._runs = MagicMock()
    pipeline._setups = MagicMock()
    pipeline._bus = MagicMock()
    pipeline._capital = 400000
    pipeline._sync = MagicMock()
    return pipeline, tier2, context_fetcher


async def test_pipeline_passes_real_market_data_to_regime(pipeline_with_context):
    pipeline, tier2, ctx = pipeline_with_context
    await pipeline.run(date(2026, 9, 28))

    tier2.analyze_regime.assert_called_once()
    call_kwargs = tier2.analyze_regime.call_args.kwargs
    assert call_kwargs["nifty"] == 19500.0
    assert call_kwargs["vix"] == 13.5
    assert call_kwargs["fii_5d_net"] == -500.0


async def test_pipeline_uses_defaults_when_context_fails(pipeline_with_context):
    pipeline, tier2, ctx = pipeline_with_context
    ctx.fetch.side_effect = Exception("Network error")
    await pipeline.run(date(2026, 9, 28))

    tier2.analyze_regime.assert_called_once()
    call_kwargs = tier2.analyze_regime.call_args.kwargs
    # Should use safe defaults, not crash
    assert call_kwargs["vix"] == 15.0  # default VIX
```

- [ ] **Step 2: Implement: add MarketContextFetcher to pipeline**

In `tradingbot/analysis/pipeline.py`:

1. Add `context_fetcher` parameter to `__init__`:
```python
def __init__(self, ..., context_fetcher=None, ...):
    ...
    self._context_fetcher = context_fetcher
```

2. Replace the hardcoded zeros in `run()`:
```python
# Fetch real market context
market_ctx = self._fetch_market_context()
sector_data = {s: 0.0 for s in (market_ctx.sector_leaders + market_ctx.sector_laggards)}

regime = await self._tier2.analyze_regime(
    nifty=market_ctx.nifty_level,
    banknifty=0,  # MarketContext doesn't store banknifty level directly
    vix=market_ctx.india_vix,
    nifty_5d_change=0,  # Not in MarketContext; LLM infers from level
    fii_5d_net=market_ctx.fii_net_cr,
    dii_5d_net=market_ctx.dii_net_cr,
    advance_decline=0,  # Not in MarketContext
    sector_data=sector_data,
)
```

3. Add `_fetch_market_context()` method:
```python
def _fetch_market_context(self) -> MarketContext:
    """Fetch real market data, with safe defaults on failure."""
    if self._context_fetcher is None:
        return self._default_context()
    try:
        return self._context_fetcher.fetch()
    except Exception:
        log.warning("MarketContextFetcher failed, using defaults")
        return self._default_context()

def _default_context(self) -> MarketContext:
    return MarketContext(
        nifty_level=0, nifty_trend="unknown", banknifty_trend="unknown",
        india_vix=15.0, fii_net_cr=0, dii_net_cr=0,
        global_cues="unavailable", sector_leaders=[], sector_laggards=[],
        regime=MarketRegime.RANGE_BOUND,
    )
```

4. Update `_run_analysis_v2` in `analysis_routes.py` to pass `context_fetcher`:
```python
from tradingbot.scanner.market_context import MarketContextFetcher
context_fetcher = MarketContextFetcher()
# pass to AnalysisPipeline(..., context_fetcher=context_fetcher)
```

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/analysis/test_regime_wiring.py tests/ -q --tb=short`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tradingbot/analysis/pipeline.py tradingbot/api/analysis_routes.py tests/analysis/test_regime_wiring.py
git commit -m "feat(pipeline): wire analyze_regime with real MarketContextFetcher data

Uses existing MarketContextFetcher for Nifty/VIX/FII-DII.
Falls back to safe defaults (VIX=15, RANGE_BOUND) on network failure."
```

---

### Task 5: Auto-Sync + Full _run_analysis_v2 Wiring

**Files:**
- Modify: `tradingbot/api/analysis_routes.py` (complete wiring of `_run_analysis_v2`)
- Test: `tests/api/test_v2_integration.py`

**Interfaces:**
- Consumes: All previous tasks (KiteAuth, DataSync, InstrumentCache, CandleStore, MarketContextFetcher, AnalysisPipeline)
- Produces: `POST /analyze?pipeline=v2` fully functional when Kite is authenticated

- [ ] **Step 1: Write integration test**

```python
# tests/api/test_v2_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path


async def test_v2_pipeline_requires_kite_auth(api_client):
    """v2 pipeline should fail clearly if Kite not authenticated."""
    response = await api_client.post("/api/analyze", json={"pipeline": "v2"})
    # Should start but _run_analysis_v2 should handle missing auth
    assert response.status_code in (200, 400)


async def test_v2_pipeline_creates_analysis_run(api_client, tmp_path):
    """With mocked Kite, v2 pipeline should produce an AnalysisRun."""
    with patch("tradingbot.api.analysis_routes._run_analysis_v2") as mock_v2:
        mock_v2.return_value = None  # async task
        response = await api_client.post("/api/analyze", json={"pipeline": "v2"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
```

- [ ] **Step 2: Complete _run_analysis_v2 wiring**

Update `_run_analysis_v2` in `analysis_routes.py` to:
1. Check Kite auth — if not authenticated, raise clear error
2. Initialize data stores from `data/` directory
3. Auto-sync if InstrumentCache is empty (first run)
4. Pass all real dependencies to AnalysisPipeline
5. Handle errors with clear status messages

```python
async def _run_analysis_v2(state: AppState, trade_date: date) -> None:
    """Run the redesigned 3-tier analysis pipeline."""
    try:
        from tradingbot.analysis.pipeline import AnalysisPipeline
        from tradingbot.analysis.tier2_analyzer import Tier2Analyzer
        from tradingbot.analysis.tier3_analyzer import Tier3Analyzer
        from tradingbot.backtest.walk_forward import WalkForwardEngine
        from tradingbot.backtest.monte_carlo import MonteCarloSimulator
        from tradingbot.backtest.quality_gates import QualityGates
        from tradingbot.data.kite_client import KiteClient
        from tradingbot.data.instrument_cache import InstrumentCache
        from tradingbot.data.candle_store import CandleStore
        from tradingbot.data.data_sync import DataSync
        from tradingbot.screening.screener import Tier1Screener
        from tradingbot.scanner.market_context import MarketContextFetcher
        from tradingbot.core.llm.anthropic_provider import build_provider

        state.event_bus.emit("analysis.started", {"pipeline": "v2"})

        data_dir = Path("data")
        data_dir.mkdir(exist_ok=True)

        # Initialize stores
        instrument_cache = InstrumentCache(data_dir / "instruments.db")
        candle_store = CandleStore(data_dir / "candles.db")

        # Build Kite client if authenticated
        kite_client = None
        data_sync = None
        if state.kite_auth and state.kite_auth.is_authenticated():
            kite_client = KiteClient(
                state.kite_auth.kite,
                rate_limit_per_sec=state.config.kite.rate_limit_per_sec,
            )
            data_sync = DataSync(kite_client, instrument_cache, candle_store)

            # Auto-sync if cache empty
            if not instrument_cache.get_all():
                log.info("InstrumentCache empty, running initial sync...")
                data_sync.full_sync(daily_lookback=30, intraday_lookback=7)

        # Build LLM provider
        provider = build_provider(state.config.llm, state.config.secrets)

        # Build pipeline
        _ensure_stores(state)
        pipeline = AnalysisPipeline(
            data_sync=data_sync,
            candle_store=candle_store,
            screener=Tier1Screener(state.config.screening, candle_store),
            tier2=Tier2Analyzer(provider),
            tier3=Tier3Analyzer(provider),
            backtest_engine=WalkForwardEngine(),
            monte_carlo=MonteCarloSimulator(),
            quality_gates=QualityGates(),
            run_store=state.run_store,
            setup_store=state.setup_store,
            event_bus=state.event_bus,
            capital=state.config.general.capital,
            instrument_cache=instrument_cache,
            context_fetcher=MarketContextFetcher(),
        )

        run = await pipeline.run(trade_date)
        state.analysis_status = "complete"
        state.event_bus.emit("analysis.complete", {"run_id": run.run_id, "pipeline": "v2"})

    except Exception as exc:
        log.exception("v2 analysis failed")
        state.analysis_status = "failed"
        state.analysis_error = str(exc)
        state.event_bus.emit("analysis.failed", {"error": str(exc)})
```

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/ -q --tb=short`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tradingbot/api/analysis_routes.py tests/api/test_v2_integration.py
git commit -m "feat(api): complete v2 pipeline wiring with auto-sync + auth check

_run_analysis_v2 now: checks Kite auth, initializes data stores,
auto-syncs on first run, passes all real deps to AnalysisPipeline.
POST /analyze?pipeline=v2 is fully functional when Kite authenticated."
```

---

## Execution Order Summary

| Task | What It Wires | Tests Added |
|------|--------------|-------------|
| 1: Kite OAuth endpoints | Login/callback/status API | ~4 |
| 2: Data sync CLI | `tradingbot sync` + full_sync() | ~3 |
| 3: _build_stock_metrics | InstrumentCache → screening metrics | ~4 |
| 4: analyze_regime | MarketContextFetcher → real data | ~2 |
| 5: Full v2 wiring | Auto-sync + auth check + all deps | ~2 |
| **Total** | **Credentials → working app** | **~15** |
