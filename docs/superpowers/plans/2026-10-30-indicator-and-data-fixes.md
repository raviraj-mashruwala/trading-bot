# Indicator and Data Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give the analysis pipeline correct indicators and real data, so that tier-2 and tier-3 reasoning rests on facts. The first real run (2026-11-02 plan) produced 0 legs because of the defects below, not because of the market.

**Spec:** No separate spec. The requirement is the user's words, 2026-10-30: "fix all 4 defects ... not just handling the nan and data not available, we need data for proper analysis". Evidence for each defect is the first-run log plus the code reads and probes listed here.

## Defects and root causes (verified)

1. **Supertrend is NaN and always "up".** `strategy/indicators.py supertrend()`: the first ATR values are NaN, `lower > final_lower[i-1]` is False against NaN, so the final bands copy NaN forever; direction comparisons against NaN are False, so direction stays at its initial `+1`. Reproduced on a synthetic downtrend (bands `nan`, direction never `-1`).
2. **VWAP and volume profile are not intraday.** `vwap()`, `vwap_bands()` accumulate over the whole frame (60 days of 15m candles); `volume_profile()` bins every close in it. Snapshot: NOCIL close 136 vs "VWAP" 178.7; synthetic stock at 50 vs "VWAP" 125. Support/resistance clusters the same 60 days, so levels are often far or empty when price sits at a multi-week extreme.
3. **Shortlist prompt has no direction and includes ETFs.** Tier 1 factor scores are magnitudes (`abs()` inside RS, price structure, gap); the prompt carries no signed change, RSI or trend. Nine of 11 picks were deep downtrends passed on as "long". Six silver ETFs sat in the top 30 (`get_universe` filters only series junk, not ETFs).
4. **Data gaps.**
   - 4a. Delivery %: `delivery_fetcher._date_str` builds `29OCT2026`; NSE's file is `sec_bhavdata_full_29102026.csv` (probed: HTTP 200 for 28-30 Oct 2026 on both hosts). The lookback also counts calendar days, so a Monday target only tries Thursday and Friday. Result: `delivery_pct` is 50.0 for every stock, always.
   - 4b. Market context: `MarketContextFetcher(market_data_provider=...)` is built without `candle_store` (`analysis_routes.py:134`), and `_read_index` only reads the candle store, so NIFTY 50, NIFTY BANK and INDIA VIX always read 0 rows (VIX defaults to 15). The data is present in `candles.duckdb` (about 2,930 daily rows each, to 2026-10-30). `_read_index` also calls the legacy `read(symbol, "day", from_dt, to_dt)`, which does not match `CandleStore.read(symbol, interval, days=...)`.
   - 4c. Regime inputs are zeroed: `banknifty=0`, `advance_decline=0`, `sector_data={}` in `pipeline.py` (`_regime_args`).

## Rulings (the plan's design choices; reversible)

- **Session** = the trading date of a 15m candle's timestamp. VWAP and bands reset each session. The snapshot reports the **last session in the data** (after hours that is the day just finished, a sound reference for tomorrow).
- **Volume profile and S/R window** = last 10 sessions (was ~60 days). Chosen so levels are intraday-relevant; constant `PROFILE_SESSIONS = 10`.
- **Reference levels** added to the snapshot so price always has structure nearby: last-session high/low/close, 5-session high/low, 20-session high/low.
- **Signed Tier-1 signals** shown in the shortlist prompt: 1-day change %, 5-day change %, daily RSI(14), % vs SMA20, % vs SMA50, signed gap %, volume vs 20-day average (ratio).
- **ETF/fund exclusion** is name-based on the Kite instrument `name` (regex `ETF|BEES|FUND|LIQUID|GILT`) plus symbols ending `BEES`/`ETF`.
- **Sector mapping is out of scope**: Kite instruments carry no sector, so every stock is `sector="unknown"` and sector momentum is the neutral 50 for all. Fixing it needs an external mapping (for example NSE index constituents); flagged, not built here.
- Backtester `precompute_indicator_series` shares `vwap_bands`; it picks up the anchored VWAP.

## Global Constraints

- Defaults and the web API path keep working; no new required config.
- `uv run pytest -q` passes (1084 tests) before and after every task.
- Commits use git `user.email` = `raviraj.mashruwala@outlook.com`.

## Review Focus

1. Supertrend must match the textbook algorithm on a known series, including flips, and never return NaN after warmup.
2. Session anchoring must handle frames without a timestamp column (existing tests/backtester pass plain frames) and DST-free IST data.
3. Windowing to 10 sessions must not break `compute_snapshot` for stocks with fewer than 10 sessions (MIN_CANDLES=200 still applies).
4. Every new snapshot field must reach the tier-3 prompt text, not just the dataclass.
5. Delivery lookback must never request a date after today, and must tolerate a not-yet-published latest file.

---

### Task 1: Supertrend

**Files:** `tradingbot/strategy/indicators.py` (`supertrend`); Test `tests/strategy/test_indicators_supertrend.py` (new; check `tests/strategy/` naming).

- [ ] **Step 1: Tests (RED):** `test_supertrend_has_no_nan_after_warmup`, `test_supertrend_direction_is_down_in_a_steady_downtrend` (direction last == -1, and -1 occurs), `test_supertrend_direction_is_up_in_a_steady_uptrend`, `test_supertrend_flips_when_trend_reverses` (down then up: both directions appear, last == +1), `test_supertrend_band_follows_price_side` (when direction == -1, price <= upper band; when +1, price >= lower band), `test_snapshot_supertrend_value_is_finite` (via `compute_snapshot` on a 300-row frame).
- [ ] **Step 2: Run** `uv run pytest tests/strategy/test_indicators_supertrend.py -q`. Expected: fail.
- [ ] **Step 3: Implement** the standard algorithm: Wilder ATR (`atr(df, period)`), `basic_upper/lower = hl2 ± multiplier*ATR`, start the recursion at the first index where ATR is valid (earlier rows get NaN and direction +1 by convention), final bands tighten only in their favourable direction unless the previous close broke them, direction flips when close crosses the opposite final band.
- [ ] **Step 4: Run** the same file plus `uv run pytest tests/strategy -q`. Expected: pass.
- [ ] **Step 5: Commit** `fix: supertrend returned NaN bands and a constant up direction`.

### Task 2: Session-anchored VWAP, windowed volume profile and S/R, reference levels

**Files:** `tradingbot/strategy/indicators.py` (`vwap`, `vwap_bands`, `volume_profile`, `support_resistance`, `compute_snapshot`, `precompute_indicator_series`, `IndicatorSnapshot` in `tradingbot/core/models.py` or where defined); `tradingbot/analysis/pipeline.py` (`_build_price_action_summary`, ~L880); Test `tests/strategy/test_indicators_sessions.py` (new).

**Interfaces:**
- `sessions(df) -> pd.Series`: the session key per row (date of `df["timestamp"]` or of a DatetimeIndex); `None`-safe: a frame with neither is a single session.
- `vwap(df)` and `vwap_bands(df)` reset per session via `sessions(df)`.
- `volume_profile(df)` and `support_resistance(df)` use only the last `PROFILE_SESSIONS = 10` sessions.
- New snapshot fields: `last_session_high/low/close`, `high_5d`, `low_5d`, `high_20d`, `low_20d` (floats), included in `to_dict()` and printed in the price-action summary the LLM reads.

- [ ] **Step 1: Tests (RED):** `test_vwap_resets_each_session` (two sessions with very different prices: the second session's first VWAP equals its own first typical price, not a blend), `test_vwap_last_value_is_the_last_sessions_vwap`, `test_vwap_bands_are_anchored_per_session`, `test_vwap_without_timestamp_is_one_session` (existing behaviour kept), `test_volume_profile_uses_only_recent_sessions` (old-session volume at a distant price does not move POC), `test_support_resistance_ignores_sessions_older_than_the_window`, `test_snapshot_vwap_is_near_price_for_a_trending_multi_week_frame` (reproduces the NOCIL case: price 136 after a fall from 250, VWAP within the last session's range), `test_snapshot_exposes_reference_levels` (values equal the expected session aggregates), `test_price_action_summary_mentions_reference_levels` (pipeline text contains `last_session_high` or its label).
- [ ] **Step 2: Run** `uv run pytest tests/strategy/test_indicators_sessions.py -q`. Expected: fail.
- [ ] **Step 3: Implement** `sessions`, the per-session VWAP via `groupby(sessions).cumsum()`, the window helper, the new fields, and the summary text. Keep `vwap()` returning a Series aligned to `df`.
- [ ] **Step 4: Run** `uv run pytest tests/strategy tests/analysis -q` (the backtester shares `vwap_bands`). Expected: pass.
- [ ] **Step 5: Commit** `fix: anchor VWAP and volume profile to sessions, add reference levels`.

### Task 3: Delivery percentage

**Files:** `tradingbot/data/delivery_fetcher.py`; Test `tests/data/test_delivery_fetcher.py` (extend; exists).

- [ ] **Step 1: Tests (RED):** `test_url_uses_numeric_ddmmyyyy_date` (`29102026`), `test_walks_back_over_trading_days_not_calendar_days` (target Monday, only Friday's file exists: found), `test_never_requests_a_date_after_today` (target in the future starts from today), `test_returns_empty_when_no_file_in_the_window` (all 404), `test_parses_deliv_per_for_eq_series_only` (existing behaviour kept), `test_lookback_covers_a_long_weekend` (7 calendar days).
- [ ] **Step 2: Run** `uv run pytest tests/data/test_delivery_fetcher.py -q`. Expected: fail.
- [ ] **Step 3: Implement:** `_date_str` returns `DDMMYYYY`; start at `min(target, today)`; loop calendar days back up to `_MAX_LOOKBACK_DAYS = 7`, skipping weekends; keep the browser headers.
- [ ] **Step 4: Run** the same file. Expected: pass. **Step 5: Commit** `fix: delivery bhavcopy URL used the wrong date format`.

### Task 4: Market context from the candle store, and real regime inputs

**Files:** `tradingbot/scanner/market_context.py` (`_read_index`); `tradingbot/api/analysis_routes.py` (~L134, pass `candle_store=state.candle_store`); `tradingbot/analysis/pipeline.py` (`_regime_args`); Test `tests/scanner/test_market_context.py` (extend), `tests/analysis/test_regime_wiring.py` (extend).

- [ ] **Step 1: Tests (RED):** `test_index_trend_reads_the_duckdb_store_signature` (a fake store whose `read(symbol, interval, days=...)` returns a frame; legacy signature must not be required), `test_vix_comes_from_the_store_when_present` (not 15.0), `test_context_fetcher_is_built_with_the_candle_store` (analysis route builds it with `candle_store`), `test_regime_args_carry_banknifty_level_and_breadth` (non-zero `banknifty`, `advance_decline` computed from Tier-1 metrics: advancers minus decliners on the last session).
- [ ] **Step 2: Run** the two files. Expected: fail.
- [ ] **Step 3: Implement:** `_read_index` calls `self._candles.read(symbol, "day", days=days)`; pass the store in `_run_analysis`; compute BANKNIFTY level via the same `_fetch_index_trend`; add `breadth` to the pipeline from `stock_metrics` (add `change_1d_pct` in Task 5, so compute breadth from it) and pass `advance_decline`.
- [ ] **Step 4: Run** `uv run pytest tests/scanner tests/analysis tests/api -q`. Expected: pass. **Step 5: Commit** `fix: market context reads index and VIX data from the candle store`.

### Task 5: Shortlist prompt with signed signals, ETF exclusion

**Files:** `tradingbot/analysis/pipeline.py` (`_build_stock_metrics_from_instruments`, `scored_dicts`); `tradingbot/screening/intelligent_screener.py` and `tradingbot/core/models.py` (`ScoredStock` carries `signals: dict`); `tradingbot/analysis/prompts.py` (`build_shortlist_user_prompt`, task text); `tradingbot/data/market_data_provider.py` (`get_universe`); Test `tests/analysis/test_stock_metrics.py`, `tests/analysis/test_prompts.py`, `tests/data/test_market_data_provider.py` (extend or create).

**Interfaces:** each metrics dict gains `signals = {change_1d_pct, change_5d_pct, rsi_14, vs_sma20_pct, vs_sma50_pct, gap_pct, vol_ratio}` (signed, from the daily frame). `ScoredStock.signals` carries it through both screeners. `scored_dicts` includes `signals`. The prompt prints one extra line per stock: `change_1d=-4.2%, change_5d=-11.0%, rsi14=27, vs_sma20=-8.1%, vs_sma50=-12.4%, gap=-1.3%, vol_ratio=2.4`.

- [ ] **Step 1: Tests (RED):** `test_metrics_include_signed_signals` (a falling frame gives negative change and `vs_sma20_pct`; a rising frame positive), `test_signals_survive_both_screeners` (deterministic and intelligent), `test_shortlist_prompt_shows_signed_signals_per_stock`, `test_shortlist_prompt_tells_the_model_direction_comes_from_the_signed_lines`, `test_universe_excludes_etfs_and_funds` (names `NIPPON INDIA SILVER ETF`, symbols `SILVERBEES`, `GOLDBEES`, `LIQUIDBEES` dropped; `RELIANCE` kept), `test_universe_keeps_normal_equities_whose_name_contains_fund_as_a_word_fragment` (guard against over-matching: `FUNDAMENTAL INDUSTRIES` is not excluded if the regex is word-bounded).
- [ ] **Step 2: Run** the three files. Expected: fail.
- [ ] **Step 3: Implement** the signals, the model field, the prompt line and task wording ("the signed lines give direction; the scores give strength"), and the ETF filter. Check the real instruments cache (`instruments.db`) for the `name` field before writing the regex.
- [ ] **Step 4: Run** `uv run pytest tests/analysis tests/screening tests/data -q`. Expected: pass. **Step 5: Commit** `feat: shortlist prompt carries signed signals; ETFs excluded from the universe`.

### Task 6: Verify against the real data

No new production code. Read-only verification so the claims are not just unit-tested:

- [ ] Run `compute_snapshot` on the cached 15m candles for NOCIL, GENESYS and INTELLECT (the three stocks from the failed run) and assert in a scratch script: supertrend is finite, direction is `-1` for the downtrending ones, VWAP lies inside the last session's low-high range, reference levels are present and bracket or sit near the close.
- [ ] Run `fetch_delivery_pct(date(2026, 11, 2))` and confirm it returns thousands of symbols (the 10-30 file).
- [ ] Run the context fetcher against `candles.duckdb` and confirm NIFTY level, both trends and VIX are real (VIX is not 15.0).
- [ ] Report the numbers. Run the full suite `uv run pytest -q`.

---

## Not in this plan

- Sector mapping for stocks (needs an external source); `sector_data` for the regime prompt stays empty and `sectors_in_play` stays Jev's call.
- Re-running the analysis for 2026-11-02 (the user runs it: delete `llm_queue/2026-11-02/` first, since cached answers were produced from the broken indicators).
- Changing tier-3 rules (3 confluences, 1.5:1 R:R); they were reasonable given the data.
