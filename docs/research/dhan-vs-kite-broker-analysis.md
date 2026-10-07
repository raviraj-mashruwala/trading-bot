# Dhan vs Zerodha Kite: Broker & API Research for Trading Bot Migration

**Date:** 2026-10-06
**Author:** Research Analysis for Trading Bot Project
**Purpose:** Evaluate whether switching from Zerodha Kite Connect to Dhan (DhanHQ) improves data acquisition, reduces costs, and better serves our automated trading system.

---

## 1. Executive Summary

Dhan offers a compelling alternative to Zerodha Kite Connect for our trading bot, with **free trading APIs**, **higher order rate limits (25/sec vs 3/sec)**, and **comparable data costs**. However, it comes with **significant reliability concerns** reported throughout 2026, including authentication failures, data quality issues, and SSL errors. The historical data download bottleneck we face with Kite (3 req/sec) would improve with Dhan (5 req/sec for data APIs, 100K requests/day), but **not dramatically** — bulk data download remains a symbol-by-symbol affair on both platforms.

**Verdict:** Dhan is worth exploring as a secondary/parallel integration, but not a wholesale replacement yet. The reliability risks are too high for a production trading system. A dual-broker architecture or a third-party data provider may be the better path.

---

## 2. Our Current Pain Points (Kite Connect)

| Pain Point | Root Cause |
|-----------|------------|
| Slow data sync (~30+ min for full sync) | 3 req/sec rate limit on historical candles API, symbol-by-symbol fetching |
| Daily auth token refresh | Kite requires browser-based OAuth login every day |
| API cost | ₹2,000/month for Kite Connect (reduced to ₹500/mo for data-only since Mar 2025) |
| Rate limit 429 errors | Token-bucket limiter at 3 req/sec, 10s cooldown on throttle |
| No bulk endpoint | Must fetch each symbol + interval combination individually |

Our `KiteRateLimiter` in `kite_client.py` enforces 3 req/sec. For ~200 screened stocks across multiple intervals (day + 15m), this means:
- 200 stocks x 2 intervals = 400 requests minimum
- At 3 req/sec = ~133 seconds best case
- With retries and backoff = 5-10 minutes typical daily sync

For initial fill (all historical data): 30-60 minutes.

---

## 3. Dhan (DhanHQ) — Complete Profile

### 3.1 Company & Platform

- **Founded:** 2021, Mumbai
- **Parent:** Moneylicious Securities
- **SEBI Registered:** Yes (INZ000201338)
- **Users:** Growing rapidly, 500+ API-based traders, 50+ partners including TradingView, Smallcase
- **Focus:** Options trading, algo trading, developer-first API ecosystem

### 3.2 Account Opening

| Item | Cost |
|------|------|
| Account Opening | ₹0 |
| Annual Maintenance (AMC) | ₹0 |
| Demat AMC | ₹0 |
| Platform Fee | ₹0 |

Compared to Zerodha's ₹300/year demat AMC, Dhan is fully free.

**Documents needed:** PAN, Aadhaar, bank proof, signature. Digital KYC via DigiLocker — account opens in minutes.

### 3.3 Brokerage Charges

| Segment | Dhan | Zerodha |
|---------|------|---------|
| Equity Delivery | ₹0 | ₹0 |
| Equity Intraday | ₹20 or 0.03% | ₹20 or 0.03% |
| F&O | ₹20/order | ₹20/order |
| DP Charges (sell) | ₹12.5 + GST/scrip | ₹15.34/scrip |

**Notable:** 50% brokerage discount for women traders on Dhan.

### 3.4 API Pricing

| Feature | Dhan | Zerodha Kite Connect |
|---------|------|---------------------|
| Trading API (orders) | **₹0** | ₹0 (free since Mar 2025) |
| Data API (live + historical) | ₹499/mo (+taxes) | ₹500/mo |
| Data API free condition | Free if 25+ trades in last 30 days | No free condition |
| Total API cost | **₹0 to ₹499/mo** | **₹500/mo** |

**Cost difference is negligible.** Both ~₹500/month for data. Trading APIs free on both.

---

## 4. API Comparison — What Matters for Our Bot

### 4.1 Rate Limits

| Endpoint | Kite Connect | DhanHQ |
|----------|-------------|--------|
| Historical Data | 3 req/sec | 5 req/sec |
| Quote/LTP | 1 req/sec | 1 req/sec |
| Order Placement | 10 req/sec (200/min) | 25 req/sec |
| Daily Data Cap | None | 100,000 req/day |
| WebSocket Instruments | 3,000 | 5,000 per socket (5 sockets = 25,000) |

**For our data sync problem:**
- Kite: 3 req/sec = ~133s for 400 requests
- Dhan: 5 req/sec = ~80s for 400 requests
- **~40% faster**, but still symbol-by-symbol. Not a fundamental improvement.

**For execution:**
- Kite: 3 orders/sec — fine for our 2 trades/day max
- Dhan: 25 orders/sec — overkill for us but headroom for growth

### 4.2 Historical Data

| Feature | Kite Connect | DhanHQ |
|---------|-------------|--------|
| Intraday candles | Up to 60 days (minute), varies by interval | 5 years (all intervals) |
| Daily candles | Years of data | Since inception |
| Intervals | 1m, 3m, 5m, 10m, 15m, 30m, 60m, day | 1m, 5m, 15m, 25m, 60m, day |
| OI data | Yes | Yes (added in v2.2) |
| Expired options | No | Yes (v2.3) |
| Corporate action adjusted | Yes | Yes (daily) |

**Dhan wins on historical depth** — 5 years of intraday vs Kite's 60-day minute data. For our backtesting (`backtest_days = 30`), both work. For deeper research, Dhan is significantly better.

### 4.3 WebSocket / Live Market Feed

| Feature | Kite Connect | DhanHQ |
|---------|-------------|--------|
| Protocol | Binary (KiteTicker) | Binary (JSON request, binary response) |
| Max instruments | 3,000 | 25,000 (5 x 5,000) |
| Market depth | 5 levels | 20 levels (200 on premium) |
| Modes | LTP, Quote, Full | Ticker, Quote, Full |
| Reliability | Battle-tested, very stable | Good but some reported issues |

**For our execution engine:** We subscribe to ~2-5 instruments during execution. Both platforms handle this trivially. Kite's WebSocket is more battle-tested.

### 4.4 Authentication

| Feature | Kite Connect | DhanHQ |
|---------|-------------|--------|
| Token validity | 1 day (until 6 AM next day) | 24 hours |
| Auth method | OAuth redirect (browser) | OAuth OR API key + TOTP |
| Auto-renewal | Not possible | Possible via API key + TOTP |
| Static IP required | No | Yes (for order APIs only) |

**This is Dhan's biggest win for our use case.** Kite requires manual browser login daily. Dhan supports **programmatic token generation via API key + TOTP** — meaning our bot could auto-authenticate without human intervention. Critical for remote/cloud hosting.

However: Dhan requires **static IP for order APIs**. This complicates cloud/home hosting unless you have a fixed IP or use a tunnel with consistent egress.

---

## 5. Reliability Concerns (Dhan)

Research into MadeForTrade forum (Dhan's community) revealed **significant 2026 issues**:

| Issue | Date | Severity |
|-------|------|----------|
| `DH-901` Invalid Authentication errors, unresolvable | Feb 2026 | High |
| SSL errors (`UNEXPECTED_EOF_WHILE_READING`) on data endpoints | Jun 2026 | High |
| Data API stopped working despite active subscription | Oct 2026 | Critical |
| User post: "DO NOT buy Dhan API for Data" — data quality issues | Jun 2026 | High |
| Dhan Cloud Python version incompatibility | Jun 2026 | Medium |
| `DH-905` Invalid IP errors, unclear static IP rules | 2026 | Medium |
| Documentation gaps (Super Order API, UUID format issues) | 2026 | Low |
| User sentiment: "A year ago Dhan was best, now more issues day by day" | 2026 | Concerning |

**This is the critical risk factor.** For a trading bot handling real money, API reliability is non-negotiable. These aren't edge cases — they're core functionality failures.

Zerodha's Kite Connect, while slower and more expensive, has **years of battle-tested stability** and the largest developer community for troubleshooting.

---

## 6. Migration Effort Assessment

### What Would Change in Our Codebase

| Component | Current (Kite) | Dhan Equivalent | Effort |
|-----------|---------------|-----------------|--------|
| `kite_client.py` | KiteConnect SDK | DhanHQ SDK | Rewrite |
| `kite_data_sync.py` | Historical candle fetch | DhanHQ historical API | Rewrite |
| `kite_ticker.py` | KiteTicker WebSocket | DhanHQ Live Market Feed | Rewrite |
| `kite_auth.py` | Browser OAuth | API key + TOTP | Rewrite (simpler) |
| `instrument_cache.py` | Kite instrument list | Dhan instrument list (different format) | Modify |
| `execution_routes.py` | Kite order placement | Dhan order placement | Rewrite |
| `config.toml` | Kite settings | Dhan settings | Modify |
| `cli.py` (auth command) | Browser redirect | TOTP-based auth | Rewrite |

**Estimated effort:** 3-5 days for a full migration. All broker-touching code needs rewriting.

### Recommended Architecture: Broker Abstraction

Rather than hard-switching, build a broker abstraction layer:

```
BrokerInterface (abstract)
├── KiteBroker (existing)
├── DhanBroker (new)
└── config.toml: broker = "kite" | "dhan"
```

This lets you:
- Test Dhan in paper mode while keeping Kite for live
- Switch brokers via config, not code changes
- Add future brokers (Upstox, Fyers) with minimal effort

---

## 7. Alternative: Third-Party Data Providers

If the core problem is **data download speed**, consider decoupling data from broker:

| Provider | Data Type | Cost | Speed |
|----------|-----------|------|-------|
| **TrueData** | Real-time + historical | ₹500-1000/mo | Bulk download, fast |
| **Global Datafeeds** | Historical OHLCV | ₹300-600/mo | Pre-built CSV dumps |
| **NSE bhav copy** | EOD data | Free | Daily file download |
| **Yahoo Finance** | Daily OHLCV | Free | API, some gaps |
| **MotherDuck + Parquet** | Store & query | Free tier | N/A (storage) |

**Best approach:** Use broker API for orders + live ticks only. Use dedicated data provider for historical candles. Eliminates rate limit problem entirely.

---

## 8. Recommendations

### Short-Term (Do Now)
1. **Keep Kite for trading** — proven reliability for live orders
2. **Optimize current sync** — parallelize where possible within rate limits, cache aggressively, sync only delta (you already do this)
3. **Consider daily NSE bhav copy** for EOD data instead of API calls — free, fast, no rate limits

### Medium-Term (1-2 Weeks)
4. **Build broker abstraction layer** — `BrokerInterface` with Kite as default
5. **Open Dhan account** (free, zero risk) — test their API in paper mode
6. **Evaluate Dhan auth flow** — if programmatic TOTP works reliably, this alone justifies Dhan for cloud hosting

### Long-Term (If Dhan Proves Stable)
7. **Add DhanBroker implementation** behind abstraction
8. **Run parallel** — same signals, Kite live + Dhan paper, compare fills
9. **Switch data source** to Dhan only if 30-day parallel run shows no issues
10. **Keep Kite as fallback** — dual-broker resilience

### If Data Speed Is Primary Concern
11. **Decouple data from broker entirely** — use TrueData or bulk CSV sources for historical data, broker API only for orders + live feed

---

## 9. Decision Matrix

| Factor | Weight | Kite | Dhan | Notes |
|--------|--------|------|------|-------|
| API Reliability | 30% | 9/10 | 6/10 | Dhan has documented 2026 outages |
| Data Download Speed | 20% | 5/10 | 7/10 | Dhan faster but not dramatically |
| Cost | 10% | 7/10 | 9/10 | Both ~₹500/mo for data |
| Auth Automation | 15% | 3/10 | 8/10 | Dhan's TOTP auth is big win |
| Documentation | 10% | 9/10 | 6/10 | Kite docs are gold standard |
| WebSocket Quality | 10% | 9/10 | 7/10 | Kite more battle-tested |
| Community Support | 5% | 9/10 | 5/10 | Kite has larger ecosystem |
| **Weighted Score** | **100%** | **6.85** | **6.95** | **Effectively tied** |

---

## 10. Conclusion

Dhan is **not a clear upgrade** over Kite — it trades reliability for flexibility. The data speed improvement (3→5 req/sec) doesn't solve the fundamental problem of symbol-by-symbol fetching. The real wins are:

1. **Programmatic auth** (no daily browser login) — critical for cloud hosting
2. **Higher order rate limits** (25/sec) — useful for future scaling
3. **5 years intraday history** — better for deep backtesting
4. **Free trading API** — marginal cost savings

The real risks are:
1. **Documented reliability issues throughout 2026**
2. **Static IP requirement for order APIs**
3. **Smaller community for troubleshooting**
4. **Full codebase rewrite for broker integration**

**Final recommendation:** Open a Dhan account (free), build the broker abstraction layer, test in parallel. Don't hard-switch. If data speed is the #1 pain, look at third-party data providers instead — they solve the problem at the root rather than trading one set of rate limits for another.

---

## 11. Updated Findings from Official Dhan Documentation

After reviewing Dhan's official pages (dhanhq.co, docs, API playground), several corrections and new details:

### Corrected Rate Limits (from official docs, differs from third-party reports)

| Category | Per Second | Per Minute | Per Hour | Per Day |
|----------|-----------|------------|----------|---------|
| **Order APIs** | 10 | 250 | 1,000 | 7,000 |
| **Data APIs** | 5 | — | — | 100,000 |
| **Quote APIs** | 1 | Unlimited | Unlimited | Unlimited |
| **Non-Trading APIs** | 20 | Unlimited | Unlimited | Unlimited |

**Note:** Third-party sources claimed 25 orders/sec — official docs say **10 orders/sec**. Still higher than Kite's 3/sec for historical data, but not as dramatic as reported.

### Critical: 90-Day Intraday Data Limit Per Request

The intraday historical API (`/v2/charts/intraday`) returns a **maximum of 90 days per request** for any interval. While 5 years of data exists, you must paginate in 90-day windows. This means:

- For our 30-day `backtest_days`: 1 request per stock per interval (good)
- For initial fill (5 years of 15m data): ~20 requests per stock (5 years / 90 days)
- For 200 stocks: 200 × 20 = 4,000 requests at 5 req/sec = ~13 minutes
- **Comparable to Kite's initial fill time**

### Dhan WebSocket Specs (Official)

| Feature | Spec |
|---------|------|
| Max connections | 5 per user |
| Max instruments/connection | 5,000 |
| Max instruments/message | 100 (send multiple messages) |
| Protocol | JSON requests, binary responses (Little Endian) |
| Keep-alive | Server pings every 10s, auto-pong |
| Timeout | 40s without response = disconnect |
| Data modes | Ticker (LTP only), Quote (OHLCV + bid/ask qty), Full (+ 5-level depth + OI) |

### Dhan Algos Platform (algos.dhan.co)

Separate from the API — this is a **marketplace of pre-built algos**:
- 79 live algos available
- Fully hosted cloud execution (subscribe → deploy → auto-trade)
- All current algos from single provider (Stratzy)
- "AlgoBox" (portfolio of algos) coming soon
- **NOT relevant to our custom bot** — we build our own strategies

### Dhan Sandbox

Available at `sandbox.dhan.co` — test all APIs in a closed environment before live deployment. This is useful for our migration testing.

### Dhan Python SDK (DhanHQ-py v2.1.0)

Key differences from Kite's SDK:
- `DhanContext` pattern for credentials (define once, pass to all classes)
- Separate `MarketFeed` class for WebSocket
- Separate `OrderUpdate` class for live order status via WebSocket
- `Option Chain` as single function with Greeks, OI, volume
- `Kill Switch` API for emergency stop
- Market Quote supports **1,000 instruments at once** (Kite: individual)
- MIT licensed, open source

### Response Format Difference

Dhan returns candles as **parallel arrays** (not array of objects):
```json
{
    "open": [100.5, 101.0, ...],
    "high": [102.0, 103.0, ...],
    "low": [99.0, 100.0, ...],
    "close": [101.5, 102.5, ...],
    "volume": [50000, 60000, ...],
    "timestamp": [1696000000, 1696003600, ...],
    "open_interest": [0, 0, ...]
}
```
This is actually better for pandas DataFrame construction (direct column mapping).

### Authentication (Updated from Official)

- Token: JWT, passed as `access-token` header
- Validity: 24 hours
- WebSocket auth: token + clientId in connection URL query params
- API key + TOTP for programmatic renewal (v2.5+)
- Static IP required for **Order APIs only** (not data/quote APIs)

### Revised Assessment

The official docs paint a **more conservative picture** than third-party reviews:
- Order rate: 10/sec (not 25/sec as widely reported)
- Data rate: 5/sec (confirmed)
- Daily cap: 100K data requests (important for heavy backtesting)
- 90-day pagination for intraday (hidden complexity)

**Net impact on our data sync problem:** Moderate improvement. Dhan's 5 req/sec vs Kite's 3 req/sec = ~40% faster daily sync. But initial fills are similarly slow on both due to per-symbol, per-window fetching.

---

## Sources

- [Best Brokers for Algo Trading in India 2026](https://algotest.in/blog/best-brokers-for-algo-trading-in-india/)
- [Zerodha vs Dhan Complete Comparison](https://www.optiontradingwithai.in/articles/india/best-indian-broker-for-algo-trading-zerodha-vs-upstox-vs-angel-one-vs-dhan-complete-comparison)
- [Zerodha Kite Connect vs Dhan API 2026](https://www.multibagg.ai/market-pulse/articles/zerodha-nubra-dhan-api-comparison-cmp5l0ayn000ct70j0frlhjln)
- [Zerodha vs Dhan 2026 Charges](https://onetradejournal.com/brokers/zerodha-vs-dhan)
- [Dhan API Rate Limits](https://dhan.co/support/platforms/dhanhq-api/what-are-the-api-rate-limits-for-dhan/)
- [Dhan Historical Data Timeframes](https://dhan.co/support/platforms/dhanhq-api/what-timeframe-data-is-available-through-dhan-s-historical-data-apis/)
- [DhanHQ Enhanced Data APIs](https://madefortrade.in/t/enhanced-dhanhq-data-apis-with-more-data-and-higher-rate-limits/50328)
- [Dhan Brokerage Charges 2026](https://www.chittorgarh.com/brokerage_charges/dhan/176/)
- [DhanHQ Python SDK (GitHub)](https://github.com/dhan-oss/DhanHQ-py)
- [DhanHQ API Documentation](https://dhanhq.co/docs/v2/)
- [DhanHQ Live Market Feed](https://dhanhq.co/docs/v2/live-market-feed/)
- [Dhan API Access Token Validity](https://dhan.co/support/platforms/dhanhq-api/what-is-the-maximum-validity-of-an-api-access-token-in-dhan-apis/)
- [Dhan Authentication Changes](https://madefortrade.in/t/update-for-api-traders-new-changes-in-dhanhq-api-authentication-process-and-updates/56286)
- [Kite Connect Rate Limits](https://kite.trade/forum/discussion/13397/rate-limits)
- [Kite Connect API FAQs](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs)
- [MadeForTrade: Dhan API Problems](https://madefortrade.in/t/problem-with-dhan-api/60892)
- [MadeForTrade: "DO NOT Buy Dhan API for Data"](https://madefortrade.in/t/do-not-buy-dhan-api-for-data/91053)
- [MadeForTrade: Dhan Data API Stopped Working](https://madefortrade.in/t/dhan-data-api-suddenly-stopped-working-despite-active-subscription/94456)
- [MadeForTrade: Dhan API Errors](https://madefortrade.in/t/dhan-api-errors/90833)
- [MadeForTrade: Historical Data Rate Limits Conservative](https://madefortrade.in/t/rate-limit-on-historical-data-api-too-conservative/58892)
- [Dhan Algo Trading Review](https://www.chittorgarh.com/broker/dhan/api-for-algo-trading-review/176/)
- [Best Trading APIs in India 2026](https://indianbrokertest.com/best-trading-apis-in-india/)
- [Dhan Historical Data Downloader](https://dhandata.lovable.app/)

### Official Dhan Sources
- [DhanHQ Trading APIs](https://dhanhq.co/trading-apis) — Official pricing & feature page
- [Dhan Algos Marketplace](https://algos.dhan.co/) — Pre-built algo marketplace
- [DhanHQ API v2 Documentation](https://dhanhq.co/docs/v2/) — Full API reference
- [DhanHQ Historical Data API](https://dhanhq.co/docs/v2/historical-data/) — Candle endpoints & parameters
- [DhanHQ Live Market Feed](https://dhanhq.co/docs/v2/live-market-feed/) — WebSocket protocol docs
- [DhanHQ Python SDK Docs](https://dhanhq.co/docs/DhanHQ-py/) — Official Python client
- [DhanHQ Python SDK GitHub](https://github.com/dhan-oss/DhanHQ-py) — Source code & releases
