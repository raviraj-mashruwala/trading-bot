# React Frontend Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a browser dashboard (4 pages) that consumes the existing trading bot API — dashboard with charts, analysis pipeline visualization, config editor, and trade history.

**Architecture:** Next.js App Router with client-side rendering (`"use client"` pages) since all data comes from a local API. TanStack Query handles data fetching with 30s polling. Zustand manages WebSocket-driven pipeline state. shadcn/ui for components. Recharts for charts. Single WebSocket connection with exponential backoff reconnect.

**Tech Stack:** Next.js 15, React 19, TanStack Query v5, Zustand v5, Recharts 2, Tailwind CSS 4, shadcn/ui, Vitest, React Testing Library.

**Spec:** `~/.gstack/projects/rmashruwala/specs/20260925-173500-react-frontend-dashboard.md`

## Global Constraints

- Node 20+
- API runs at `http://localhost:8000`, frontend at `http://localhost:3000`
- CORS already configured on the API side for `localhost:3000`
- No authentication — single user, localhost
- No SSR needed — all pages are `"use client"` since data is from a local API
- All API response shapes match the Python models in `tradingbot/core/models.py`
- WebSocket events have shape `{type: string, timestamp: string, data: object}`
- No mobile responsiveness, no dark mode

## Review Focus

1. **WebSocket disconnect during active analysis** — if the WS drops mid-pipeline, reconnect must re-fetch `/api/analyze/status` to rebuild pipeline state; stale step states from before disconnect must not persist. Test added to Task 2.
2. **Empty trades array on fresh install** — Dashboard charts and History page must render gracefully with zero trades, not crash on empty arrays or division by zero in stats. Test added to Task 5 and Task 7.
3. **Config PUT with unchanged values** — Settings save should not send unchanged fields, since the API writes the whole TOML file; sending stale values from a cached GET could overwrite concurrent CLI changes. Test added to Task 6.
4. **Analysis started from another client** — if analysis was triggered via CLI or another tab, the Analysis page must pick up the running state from `/api/analyze/status` on mount, not show idle. Test added to Task 4.
5. **Pipeline events arriving before Analysis page mounts** — events fire from the moment analysis starts; if user navigates to /analysis mid-run, the Zustand store must already have events (WS listener is global). Test added to Task 2.

---

## File Structure

```
web/
├── package.json                          # Task 1
├── next.config.ts                        # Task 1
├── tailwind.config.ts                    # Task 1
├── tsconfig.json                         # Task 1
├── vitest.config.ts                      # Task 1
├── src/
│   ├── types/
│   │   └── index.ts                      # Task 2 — all TypeScript types
│   ├── lib/
│   │   ├── api.ts                        # Task 2 — typed fetch wrappers
│   │   ├── ws.ts                         # Task 2 — WebSocket manager
│   │   └── store.ts                      # Task 2 — Zustand pipeline store
│   ├── app/
│   │   ├── layout.tsx                    # Task 3 — shell with sidebar
│   │   ├── page.tsx                      # Task 5 — Dashboard
│   │   ├── providers.tsx                 # Task 3 — QueryClientProvider
│   │   ├── analysis/
│   │   │   └── page.tsx                  # Task 4 — Analysis pipeline
│   │   ├── settings/
│   │   │   └── page.tsx                  # Task 6 — Config editor
│   │   └── history/
│   │       └── page.tsx                  # Task 7 — Trade history
│   └── components/
│       ├── ui/                           # Task 1 — shadcn primitives
│       ├── layout/
│       │   ├── sidebar.tsx               # Task 3
│       │   └── top-bar.tsx               # Task 3
│       ├── analysis/
│       │   ├── pipeline-stepper.tsx      # Task 4
│       │   ├── pipeline-step-card.tsx    # Task 4
│       │   └── plan-legs-cards.tsx       # Task 4
│       ├── dashboard/
│       │   ├── stat-cards.tsx            # Task 5
│       │   ├── equity-curve.tsx          # Task 5
│       │   ├── daily-pnl-chart.tsx       # Task 5
│       │   ├── win-rate-donut.tsx        # Task 5
│       │   └── last-analysis.tsx         # Task 5
│       ├── settings/
│       │   ├── config-section.tsx        # Task 6
│       │   └── llm-test-button.tsx       # Task 6
│       └── history/
│           ├── trade-table.tsx           # Task 7
│           └── day-group.tsx             # Task 7
├── __tests__/
│   ├── lib/
│   │   ├── api.test.ts                  # Task 2
│   │   ├── store.test.ts               # Task 2
│   │   └── ws.test.ts                  # Task 2
│   ├── components/
│   │   ├── pipeline-step-card.test.tsx  # Task 4
│   │   ├── stat-cards.test.tsx          # Task 5
│   │   ├── config-section.test.tsx      # Task 6
│   │   └── day-group.test.tsx           # Task 7
│   └── setup.ts                         # Task 1 — test setup
```

---

## Task 1: Project Scaffolding + shadcn/ui Setup

**Files:**
- Create: `web/package.json`, `web/next.config.ts`, `web/tailwind.config.ts`, `web/tsconfig.json`, `web/vitest.config.ts`, `web/src/app/globals.css`, `web/__tests__/setup.ts`
- Create: shadcn/ui primitives via CLI: `button`, `card`, `input`, `label`, `select`, `accordion`, `badge`, `collapsible`, `separator`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: Working `npm run dev` that shows a blank page at `localhost:3000`. Vitest configured. shadcn/ui components available in `src/components/ui/`.

- [ ] **Step 1: Create Next.js project**

```bash
cd /Users/rmashruwala/work/Personal/Projects/trading-bot
npx create-next-app@latest web --typescript --tailwind --eslint --app --src-dir --import-alias "@/*" --no-turbopack
```

- [ ] **Step 2: Install dependencies**

```bash
cd web
npm install @tanstack/react-query@5 zustand@5 recharts@2
npm install -D vitest @testing-library/react @testing-library/jest-dom @vitejs/plugin-react jsdom
```

- [ ] **Step 3: Configure Next.js to proxy API**

Create `web/next.config.ts`:

```typescript
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/api/:path*", destination: "http://localhost:8000/api/:path*" },
      { source: "/ws", destination: "http://localhost:8000/ws" },
    ];
  },
};

export default nextConfig;
```

- [ ] **Step 4: Configure Vitest**

Create `web/vitest.config.ts`:

```typescript
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./__tests__/setup.ts"],
    globals: true,
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
});
```

Create `web/__tests__/setup.ts`:

```typescript
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 5: Add test and build scripts to package.json**

Add to `web/package.json` scripts:

```json
{
  "test": "vitest run",
  "test:watch": "vitest"
}
```

- [ ] **Step 6: Install shadcn/ui and add components**

```bash
cd web
npx shadcn@latest init -d
npx shadcn@latest add button card input label select accordion badge collapsible separator
```

- [ ] **Step 7: Verify dev server starts**

```bash
cd web && npm run dev
```

Expected: Next.js starts on `localhost:3000`, default page renders.

- [ ] **Step 8: Verify test runner works**

Create `web/__tests__/smoke.test.ts`:

```typescript
import { describe, it, expect } from "vitest";

describe("smoke", () => {
  it("vitest runs", () => {
    expect(1 + 1).toBe(2);
  });
});
```

Run: `cd web && npm test`
Expected: 1 test passes.

- [ ] **Step 9: Commit**

```bash
git add web/
git commit -m "feat(web): scaffold Next.js project with shadcn/ui, TanStack Query, Zustand, Recharts, Vitest"
```

---

## Task 2: Types, API Client, WebSocket Manager, Zustand Store

**Files:**
- Create: `web/src/types/index.ts`, `web/src/lib/api.ts`, `web/src/lib/ws.ts`, `web/src/lib/store.ts`
- Test: `web/__tests__/lib/api.test.ts`, `web/__tests__/lib/store.test.ts`, `web/__tests__/lib/ws.test.ts`

**Interfaces:**
- Consumes: API response shapes from Python backend (read from `tradingbot/core/models.py`, `tradingbot/api/*_routes.py`).
- Produces:
  - Types: `Trade`, `TradePlan`, `TradeLeg`, `MarketContext`, `IndicatorSnapshot`, `BacktestResult`, `TradeStats`, `AnalysisStatus`, `ExecutionStatus`, `HealthStatus`, `ConfigResponse`, `Provider`, `WsEvent`, `StepState`, `PipelineStatus`
  - API: `api.getHealth()`, `api.getConfig()`, `api.putConfig(section, values)`, `api.getProviders()`, `api.testLlm()`, `api.getPlans()`, `api.getPlan(date)`, `api.getTrades(days?)`, `api.getTradeStats(days?)`, `api.postAnalyze(tradeDate?)`, `api.cancelAnalysis()`, `api.getAnalysisStatus()`
  - WebSocket: `createWsManager(url, onEvent)` returning `{connect(), disconnect(), isConnected}`
  - Store: `usePipelineStore` Zustand hook with `status`, `steps`, `plan`, `error`, `handleEvent(event)`, `reset()`

- [ ] **Step 1: Write TypeScript types**

Create `web/src/types/index.ts`:

```typescript
export type Direction = "long" | "short";
export type EntryType = "limit" | "stop";
export type StrategyName = "breakout" | "momentum" | "mean_reversion" | "vwap_bounce" | "orb";
export type MarketRegime = "trending" | "ranging" | "volatile" | "low_vol";
export type TradeStatus = "pending" | "open" | "closed" | "cancelled" | "skipped";
export type Mode = "paper" | "live";

export interface TradeLeg {
  symbol: string;
  exchange: string;
  strategy: StrategyName;
  direction: Direction;
  entry_price: number;
  entry_type: EntryType;
  stop_loss: number;
  target_1: number;
  target_2: number;
  quantity: number;
  risk_amount: number;
  entry_window_start: string;
  entry_window_end: string;
  max_entry_wait: string;
  exit_before: string;
  confidence: number;
  reasoning: string;
}

export interface TradePlan {
  schema_version: number;
  trade_date: string;
  generated_at: string;
  capital: number;
  max_risk_per_trade_pct: number;
  max_daily_loss_pct: number;
  market_regime: MarketRegime;
  market_summary: string;
  legs: TradeLeg[];
}

export interface Trade {
  trade_date: string;
  symbol: string;
  strategy: StrategyName;
  direction: Direction;
  quantity: number;
  entry_price: number;
  exit_price: number;
  pnl: number;
  exit_reason: string;
  status: TradeStatus;
  mode: Mode;
  entered_at: string;
  exited_at: string;
}

export interface TradeStats {
  trade_count: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
  max_drawdown: number;
  best_day: number;
  worst_day: number;
}

export interface AnalysisStatus {
  status: "idle" | "running" | "complete" | "failed";
  trade_date: string | null;
  error: string | null;
}

export interface ExecutionStatus {
  status: string;
  mode: string | null;
  positions: Array<{
    symbol: string;
    direction: Direction;
    quantity: number;
    entry_price: number;
    current_stop: number;
    target_1_booked: boolean;
    pnl: number;
  }>;
}

export interface HealthStatus {
  api: string;
  database: string;
  llm: string;
}

export interface ConfigResponse {
  general: Record<string, unknown>;
  scanner: Record<string, unknown>;
  strategy: Record<string, unknown>;
  risk: Record<string, unknown>;
  execution: Record<string, unknown>;
  llm: Record<string, unknown>;
  paper: Record<string, unknown>;
  secrets: Record<string, string>;
}

export interface Provider {
  name: string;
  has_key: boolean;
  models: string[];
}

export interface PlanSummary {
  trade_date: string;
  legs_count: number;
  market_regime: MarketRegime;
  generated_at: string;
}

export interface MarketContext {
  nifty_level: number;
  nifty_trend: string;
  banknifty_trend: string;
  india_vix: number;
  fii_net_cr: number;
  dii_net_cr: number;
  global_cues: string;
  sector_leaders: string[];
  sector_laggards: string[];
  regime: MarketRegime;
}

export interface IndicatorSnapshot {
  symbol: string;
  last_close: number;
  rsi_14: number;
  macd: number;
  macd_signal: number;
  bb_upper: number;
  bb_middle: number;
  bb_lower: number;
  atr_14: number;
  sma_20: number;
  sma_50: number;
  sma_200: number;
  ema_12: number;
  ema_26: number;
  vwap: number;
  pivot: number;
  support_levels: number[];
  resistance_levels: number[];
}

export interface BacktestResult {
  symbol: string;
  strategy: StrategyName;
  trades: number;
  wins: number;
  win_rate: number;
  avg_reward_risk: number;
}

export interface WsEvent {
  type: string;
  timestamp: string;
  data: Record<string, unknown>;
}

export type StepStatus = "pending" | "active" | "complete" | "failed";

export interface StepState {
  status: StepStatus;
  data: Record<string, unknown> | null;
  timestamp: string | null;
}

export type PipelineStatus = "idle" | "running" | "complete" | "failed";
```

- [ ] **Step 2: Write API client tests**

Create `web/__tests__/lib/api.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { api } from "@/lib/api";

const mockFetch = vi.fn();
global.fetch = mockFetch;

beforeEach(() => {
  mockFetch.mockReset();
});

describe("api", () => {
  it("getHealth fetches /api/health", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ api: "ok", database: "ok", llm: "unconfigured" }),
    });
    const result = await api.getHealth();
    expect(mockFetch).toHaveBeenCalledWith("/api/health");
    expect(result.api).toBe("ok");
  });

  it("getTradeStats passes days param", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ trade_count: 5, win_rate: 0.6, total_pnl: 1200, avg_pnl: 240, max_drawdown: -300, best_day: 800, worst_day: -200 }),
    });
    await api.getTradeStats(7);
    expect(mockFetch).toHaveBeenCalledWith("/api/trades/stats?days=7");
  });

  it("getTrades defaults to 30 days", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => [] });
    await api.getTrades();
    expect(mockFetch).toHaveBeenCalledWith("/api/trades?days=30");
  });

  it("putConfig sends PUT with section data", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ status: "updated" }) });
    await api.putConfig("general", { mode: "paper", capital: 500000 });
    expect(mockFetch).toHaveBeenCalledWith("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ general: { mode: "paper", capital: 500000 } }),
    });
  });

  it("postAnalyze sends POST with optional date", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ status: "started", trade_date: "2026-09-26" }) });
    await api.postAnalyze("2026-09-26");
    expect(mockFetch).toHaveBeenCalledWith("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ trade_date: "2026-09-26" }),
    });
  });

  it("postAnalyze sends empty body when no date", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ status: "started", trade_date: "2026-09-26" }) });
    await api.postAnalyze();
    expect(mockFetch).toHaveBeenCalledWith("/api/analyze", { method: "POST" });
  });

  it("cancelAnalysis sends POST to cancel", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ status: "cancelled" }) });
    await api.cancelAnalysis();
    expect(mockFetch).toHaveBeenCalledWith("/api/analyze/cancel", { method: "POST" });
  });

  it("getConfig fetches config", async () => {
    const mockConfig = { general: { mode: "paper" }, scanner: {}, strategy: {}, risk: {}, execution: {}, llm: {}, paper: {}, secrets: {} };
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => mockConfig });
    const result = await api.getConfig();
    expect(result.general.mode).toBe("paper");
  });
});
```

- [ ] **Step 3: Write API client**

Create `web/src/lib/api.ts`:

```typescript
import type {
  HealthStatus, ConfigResponse, Provider, PlanSummary, TradePlan,
  Trade, TradeStats, AnalysisStatus,
} from "@/types";

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function post<T>(url: string, body?: unknown): Promise<T> {
  const opts: RequestInit = { method: "POST" };
  if (body !== undefined) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export const api = {
  getHealth: () => get<HealthStatus>("/api/health"),
  getConfig: () => get<ConfigResponse>("/api/config"),
  putConfig: (section: string, values: Record<string, unknown>) =>
    fetch("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [section]: values }),
    }).then((r) => {
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      return r.json();
    }),
  getProviders: () => get<Provider[]>("/api/config/providers"),
  testLlm: () => post<{ ok: boolean; error?: string }>("/api/config/test-llm"),
  getPlans: () => get<PlanSummary[]>("/api/plans"),
  getPlan: (date: string) => get<TradePlan>(`/api/plans/${date}`),
  getTrades: (days = 30) => get<Trade[]>(`/api/trades?days=${days}`),
  getTradeStats: (days = 30) => get<TradeStats>(`/api/trades/stats?days=${days}`),
  getAnalysisStatus: () => get<AnalysisStatus>("/api/analyze/status"),
  postAnalyze: (tradeDate?: string) =>
    tradeDate
      ? post<{ status: string; trade_date: string }>("/api/analyze", { trade_date: tradeDate })
      : post<{ status: string; trade_date: string }>("/api/analyze"),
  cancelAnalysis: () => post<{ status: string }>("/api/analyze/cancel"),
};
```

- [ ] **Step 4: Run API tests**

Run: `cd web && npx vitest run __tests__/lib/api.test.ts`
Expected: 8 tests pass.

- [ ] **Step 5: Write Zustand store tests**

Create `web/__tests__/lib/store.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { usePipelineStore } from "@/lib/store";
import type { WsEvent } from "@/types";

const { getState } = usePipelineStore;

beforeEach(() => {
  getState().reset();
});

const makeEvent = (type: string, data: Record<string, unknown> = {}): WsEvent => ({
  type,
  timestamp: "2026-09-25T10:00:00+05:30",
  data,
});

describe("pipeline store", () => {
  it("starts idle with empty steps", () => {
    const state = getState();
    expect(state.status).toBe("idle");
    expect(Object.keys(state.steps)).toHaveLength(0);
  });

  it("sets status to running on analysis.started", () => {
    getState().handleEvent(makeEvent("analysis.started", { trade_date: "2026-09-26" }));
    expect(getState().status).toBe("running");
  });

  it("marks scan.universe step complete", () => {
    getState().handleEvent(makeEvent("analysis.started"));
    getState().handleEvent(makeEvent("scan.universe", { count: 500, symbols: ["RELIANCE"] }));
    expect(getState().steps["scan.universe"].status).toBe("complete");
    expect(getState().steps["scan.universe"].data?.count).toBe(500);
  });

  it("marks scan.filtered step complete after scan.universe", () => {
    getState().handleEvent(makeEvent("analysis.started"));
    getState().handleEvent(makeEvent("scan.universe", { count: 500 }));
    getState().handleEvent(makeEvent("scan.filtered", { passed: 120, failed: 380, pass_rate: 0.24 }));
    expect(getState().steps["scan.filtered"].status).toBe("complete");
  });

  it("handles all 8 pipeline events in sequence", () => {
    const events = [
      "scan.universe", "scan.filtered", "scan.context", "scan.shortlist",
      "strategy.indicators", "strategy.backtest", "strategy.setups", "strategy.sized",
    ];
    getState().handleEvent(makeEvent("analysis.started"));
    for (const type of events) {
      getState().handleEvent(makeEvent(type, { test: true }));
    }
    for (const type of events) {
      expect(getState().steps[type].status).toBe("complete");
    }
  });

  it("sets status to complete on analysis.complete", () => {
    getState().handleEvent(makeEvent("analysis.started"));
    getState().handleEvent(makeEvent("analysis.complete", { trade_date: "2026-09-26", legs_count: 2, plan_summary: "bullish" }));
    expect(getState().status).toBe("complete");
  });

  it("sets status to failed on analysis.failed", () => {
    getState().handleEvent(makeEvent("analysis.started"));
    getState().handleEvent(makeEvent("analysis.failed", { error: "LLM timeout" }));
    expect(getState().status).toBe("failed");
    expect(getState().error).toBe("LLM timeout");
  });

  it("reset clears all state", () => {
    getState().handleEvent(makeEvent("analysis.started"));
    getState().handleEvent(makeEvent("scan.universe", { count: 100 }));
    getState().reset();
    expect(getState().status).toBe("idle");
    expect(Object.keys(getState().steps)).toHaveLength(0);
    expect(getState().error).toBeNull();
  });
});
```

- [ ] **Step 6: Write Zustand store**

Create `web/src/lib/store.ts`:

```typescript
import { create } from "zustand";
import type { PipelineStatus, StepState, TradePlan, WsEvent } from "@/types";

const PIPELINE_STEPS = [
  "scan.universe", "scan.filtered", "scan.context", "scan.shortlist",
  "strategy.indicators", "strategy.backtest", "strategy.setups", "strategy.sized",
] as const;

interface PipelineStore {
  status: PipelineStatus;
  steps: Record<string, StepState>;
  plan: TradePlan | null;
  error: string | null;
  handleEvent: (event: WsEvent) => void;
  reset: () => void;
}

export const usePipelineStore = create<PipelineStore>((set, get) => ({
  status: "idle",
  steps: {},
  plan: null,
  error: null,

  handleEvent: (event: WsEvent) => {
    const { type, timestamp, data } = event;

    if (type === "analysis.started") {
      const freshSteps: Record<string, StepState> = {};
      for (const step of PIPELINE_STEPS) {
        freshSteps[step] = { status: "pending", data: null, timestamp: null };
      }
      set({ status: "running", steps: freshSteps, plan: null, error: null });
      return;
    }

    if (type === "analysis.complete") {
      set({ status: "complete" });
      return;
    }

    if (type === "analysis.failed") {
      set({ status: "failed", error: (data.error as string) ?? "Unknown error" });
      return;
    }

    if (PIPELINE_STEPS.includes(type as (typeof PIPELINE_STEPS)[number])) {
      const steps = { ...get().steps };
      steps[type] = { status: "complete", data, timestamp };
      const stepIndex = PIPELINE_STEPS.indexOf(type as (typeof PIPELINE_STEPS)[number]);
      const nextStep = PIPELINE_STEPS[stepIndex + 1];
      if (nextStep && steps[nextStep]?.status === "pending") {
        steps[nextStep] = { ...steps[nextStep], status: "active" };
      }
      set({ steps });
    }
  },

  reset: () => set({ status: "idle", steps: {}, plan: null, error: null }),
}));
```

- [ ] **Step 7: Run store tests**

Run: `cd web && npx vitest run __tests__/lib/store.test.ts`
Expected: 8 tests pass.

- [ ] **Step 8: Write WebSocket manager tests**

Create `web/__tests__/lib/ws.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createWsManager } from "@/lib/ws";

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  readyState = 0;
  close = vi.fn(() => { this.readyState = 3; });
  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }
  simulateOpen() { this.readyState = 1; this.onopen?.(); }
  simulateMessage(data: string) { this.onmessage?.({ data }); }
  simulateClose() { this.readyState = 3; this.onclose?.(); }
}

beforeEach(() => {
  MockWebSocket.instances = [];
  vi.stubGlobal("WebSocket", MockWebSocket);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("WebSocket manager", () => {
  it("connects and calls onEvent for messages", () => {
    const onEvent = vi.fn();
    const ws = createWsManager("ws://localhost:8000/ws", onEvent);
    ws.connect();
    const instance = MockWebSocket.instances[0];
    instance.simulateOpen();
    instance.simulateMessage(JSON.stringify({ type: "scan.universe", timestamp: "t", data: { count: 5 } }));
    expect(onEvent).toHaveBeenCalledWith({ type: "scan.universe", timestamp: "t", data: { count: 5 } });
  });

  it("disconnect closes the socket", () => {
    const ws = createWsManager("ws://localhost:8000/ws", vi.fn());
    ws.connect();
    MockWebSocket.instances[0].simulateOpen();
    ws.disconnect();
    expect(MockWebSocket.instances[0].close).toHaveBeenCalled();
  });

  it("ignores malformed JSON messages", () => {
    const onEvent = vi.fn();
    const ws = createWsManager("ws://localhost:8000/ws", onEvent);
    ws.connect();
    MockWebSocket.instances[0].simulateOpen();
    MockWebSocket.instances[0].simulateMessage("not json");
    expect(onEvent).not.toHaveBeenCalled();
  });

  it("handles pong messages without calling onEvent", () => {
    const onEvent = vi.fn();
    const ws = createWsManager("ws://localhost:8000/ws", onEvent);
    ws.connect();
    MockWebSocket.instances[0].simulateOpen();
    MockWebSocket.instances[0].simulateMessage(JSON.stringify({ type: "pong" }));
    expect(onEvent).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 9: Write WebSocket manager**

Create `web/src/lib/ws.ts`:

```typescript
import type { WsEvent } from "@/types";

export function createWsManager(url: string, onEvent: (event: WsEvent) => void) {
  let socket: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectDelay = 1000;
  let intentionalClose = false;

  function connect() {
    intentionalClose = false;
    socket = new WebSocket(url);

    socket.onopen = () => {
      reconnectDelay = 1000;
    };

    socket.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data);
        if (parsed.type === "pong") return;
        onEvent(parsed as WsEvent);
      } catch {
        // ignore malformed
      }
    };

    socket.onclose = () => {
      if (!intentionalClose) {
        reconnectTimer = setTimeout(() => {
          reconnectDelay = Math.min(reconnectDelay * 2, 30000);
          connect();
        }, reconnectDelay);
      }
    };

    socket.onerror = () => {
      socket?.close();
    };
  }

  function disconnect() {
    intentionalClose = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    socket?.close();
    socket = null;
  }

  return {
    connect,
    disconnect,
    get isConnected() {
      return socket?.readyState === WebSocket.OPEN;
    },
  };
}
```

- [ ] **Step 10: Run all Task 2 tests**

Run: `cd web && npx vitest run __tests__/lib/`
Expected: All tests pass (8 api + 8 store + 4 ws = 20 tests).

- [ ] **Step 11: Commit**

```bash
cd /Users/rmashruwala/work/Personal/Projects/trading-bot
git add web/src/types/ web/src/lib/ web/__tests__/lib/
git commit -m "feat(web): add TypeScript types, API client, WebSocket manager, and Zustand pipeline store"
```

---

## Task 3: App Shell — Layout, Sidebar, Top Bar, Providers

**Files:**
- Create: `web/src/app/layout.tsx`, `web/src/app/providers.tsx`, `web/src/components/layout/sidebar.tsx`, `web/src/components/layout/top-bar.tsx`
- Modify: `web/src/app/globals.css` (add sidebar layout styles)

**Interfaces:**
- Consumes: `api.getHealth()` from Task 2, shadcn/ui `button`, `badge`, `separator` from Task 1.
- Produces: `<RootLayout>` wrapping all pages with sidebar navigation and top bar. `<Providers>` wrapper with `QueryClientProvider`. Sidebar with nav links for `/`, `/analysis`, `/settings`, `/history`.

- [ ] **Step 1: Create Providers wrapper**

Create `web/src/app/providers.tsx`:

```typescript
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, useEffect, type ReactNode } from "react";
import { createWsManager } from "@/lib/ws";
import { usePipelineStore } from "@/lib/store";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, refetchInterval: 30_000 } } })
  );
  const handleEvent = usePipelineStore((s) => s.handleEvent);

  useEffect(() => {
    const wsUrl = `ws://${window.location.hostname}:8000/ws`;
    const ws = createWsManager(wsUrl, handleEvent);
    ws.connect();
    return () => ws.disconnect();
  }, [handleEvent]);

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
```

- [ ] **Step 2: Create Sidebar**

Create `web/src/components/layout/sidebar.tsx`:

```typescript
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: "📊" },
  { href: "/analysis", label: "Analysis", icon: "🔬" },
  { href: "/settings", label: "Settings", icon: "⚙️" },
  { href: "/history", label: "History", icon: "📜" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-screen w-56 flex-col border-r bg-muted/40 px-3 py-4">
      <div className="mb-6 px-2 text-lg font-semibold">Trading Bot</div>
      <nav className="flex flex-col gap-1">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors hover:bg-accent",
              pathname === item.href && "bg-accent font-medium"
            )}
          >
            <span>{item.icon}</span>
            {item.label}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
```

- [ ] **Step 3: Create Top Bar with health indicator**

Create `web/src/components/layout/top-bar.tsx`:

```typescript
"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

export function TopBar() {
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: api.getHealth,
    refetchInterval: 15_000,
  });

  const isHealthy = health?.api === "ok" && health?.database === "ok";

  return (
    <header className="flex h-14 items-center justify-between border-b px-6">
      <div />
      <div className="flex items-center gap-3">
        <Badge variant={isHealthy ? "default" : "destructive"}>
          {isHealthy ? "API Connected" : "API Disconnected"}
        </Badge>
      </div>
    </header>
  );
}
```

- [ ] **Step 4: Create Root Layout**

Replace `web/src/app/layout.tsx`:

```typescript
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { Sidebar } from "@/components/layout/sidebar";
import { TopBar } from "@/components/layout/top-bar";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Trading Bot Dashboard",
  description: "Trading bot analysis, execution, and monitoring dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <Providers>
          <div className="flex h-screen">
            <Sidebar />
            <div className="flex flex-1 flex-col overflow-hidden">
              <TopBar />
              <main className="flex-1 overflow-auto p-6">{children}</main>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
```

- [ ] **Step 5: Create placeholder pages**

Create `web/src/app/page.tsx`:

```typescript
export default function DashboardPage() {
  return <h1 className="text-2xl font-bold">Dashboard</h1>;
}
```

Create `web/src/app/analysis/page.tsx`:

```typescript
export default function AnalysisPage() {
  return <h1 className="text-2xl font-bold">Analysis</h1>;
}
```

Create `web/src/app/settings/page.tsx`:

```typescript
export default function SettingsPage() {
  return <h1 className="text-2xl font-bold">Settings</h1>;
}
```

Create `web/src/app/history/page.tsx`:

```typescript
export default function HistoryPage() {
  return <h1 className="text-2xl font-bold">History</h1>;
}
```

- [ ] **Step 6: Verify in browser**

Run `cd web && npm run dev`. Navigate to `localhost:3000`. Verify:
- Sidebar shows 4 nav links
- Clicking each navigates to the right page
- Top bar shows "API Disconnected" badge (API not running)
- Active nav item is highlighted

- [ ] **Step 7: Commit**

```bash
cd /Users/rmashruwala/work/Personal/Projects/trading-bot
git add web/src/app/ web/src/components/layout/
git commit -m "feat(web): add app shell with sidebar navigation, top bar health indicator, and providers"
```

---

## Task 4: Analysis Pipeline Page

**Files:**
- Create: `web/src/components/analysis/pipeline-stepper.tsx`, `web/src/components/analysis/pipeline-step-card.tsx`, `web/src/components/analysis/plan-legs-cards.tsx`
- Modify: `web/src/app/analysis/page.tsx`
- Test: `web/__tests__/components/pipeline-step-card.test.tsx`

**Interfaces:**
- Consumes: `usePipelineStore` from Task 2. `api.postAnalyze()`, `api.cancelAnalysis()`, `api.getAnalysisStatus()`, `api.getPlan()` from Task 2. shadcn/ui `card`, `button`, `badge`, `collapsible` from Task 1.
- Produces: Full analysis page with 8-step pipeline visualization, run/cancel controls, and plan leg cards.

- [ ] **Step 1: Write pipeline step card tests**

Create `web/__tests__/components/pipeline-step-card.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PipelineStepCard } from "@/components/analysis/pipeline-step-card";

describe("PipelineStepCard", () => {
  it("renders step label with pending state", () => {
    render(<PipelineStepCard label="Fetch universe" status="pending" data={null} />);
    expect(screen.getByText("Fetch universe")).toBeInTheDocument();
  });

  it("shows yellow styling for active state", () => {
    render(<PipelineStepCard label="Filter candidates" status="active" data={null} />);
    const card = screen.getByTestId("step-card");
    expect(card.className).toContain("border-yellow");
  });

  it("expands to show data when complete and clicked", async () => {
    const user = userEvent.setup();
    render(<PipelineStepCard label="Fetch universe" status="complete" data={{ count: 500 }} />);
    await user.click(screen.getByText("Fetch universe"));
    expect(screen.getByText(/500/)).toBeInTheDocument();
  });

  it("shows error styling for failed state", () => {
    render(<PipelineStepCard label="Failed step" status="failed" data={null} />);
    const card = screen.getByTestId("step-card");
    expect(card.className).toContain("border-red");
  });

  // Review Focus #4: analysis started from CLI, page mounts mid-run
  it("renders complete state when mounted after event already processed", () => {
    render(<PipelineStepCard label="Fetch universe" status="complete" data={{ count: 200 }} />);
    const card = screen.getByTestId("step-card");
    expect(card.className).toContain("border-green");
  });
});
```

- [ ] **Step 2: Write PipelineStepCard component**

Create `web/src/components/analysis/pipeline-step-card.tsx`:

```typescript
"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { StepStatus } from "@/types";

const STATUS_STYLES: Record<StepStatus, string> = {
  pending: "border-muted-foreground/20 opacity-50",
  active: "border-yellow-500 bg-yellow-50",
  complete: "border-green-500 bg-green-50",
  failed: "border-red-500 bg-red-50",
};

const STATUS_BADGE: Record<StepStatus, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  pending: { label: "Pending", variant: "outline" },
  active: { label: "Running", variant: "default" },
  complete: { label: "Done", variant: "secondary" },
  failed: { label: "Failed", variant: "destructive" },
};

interface Props {
  label: string;
  status: StepStatus;
  data: Record<string, unknown> | null;
}

export function PipelineStepCard({ label, status, data }: Props) {
  const [expanded, setExpanded] = useState(false);
  const canExpand = status === "complete" && data !== null;

  return (
    <Card
      data-testid="step-card"
      className={cn("cursor-pointer transition-all", STATUS_STYLES[status])}
      onClick={() => canExpand && setExpanded(!expanded)}
    >
      <CardHeader className="flex flex-row items-center justify-between py-3">
        <CardTitle className="text-sm font-medium">{label}</CardTitle>
        <Badge variant={STATUS_BADGE[status].variant}>{STATUS_BADGE[status].label}</Badge>
      </CardHeader>
      {expanded && data && (
        <CardContent className="pt-0">
          <pre className="text-xs text-muted-foreground whitespace-pre-wrap">
            {JSON.stringify(data, null, 2)}
          </pre>
        </CardContent>
      )}
    </Card>
  );
}
```

- [ ] **Step 3: Run step card tests**

Run: `cd web && npx vitest run __tests__/components/pipeline-step-card.test.tsx`
Expected: 5 tests pass.

- [ ] **Step 4: Write PipelineStepper component**

Create `web/src/components/analysis/pipeline-stepper.tsx`:

```typescript
"use client";

import { usePipelineStore } from "@/lib/store";
import { PipelineStepCard } from "./pipeline-step-card";

const STEP_LABELS: Record<string, string> = {
  "scan.universe": "1. Fetch Universe",
  "scan.filtered": "2. Filter Candidates",
  "scan.context": "3. Market Context",
  "scan.shortlist": "4. LLM Shortlist",
  "strategy.indicators": "5. Technical Indicators",
  "strategy.backtest": "6. Backtest",
  "strategy.setups": "7. Strategy Setups",
  "strategy.sized": "8. Risk Sizing",
};

const STEP_ORDER = Object.keys(STEP_LABELS);

export function PipelineStepper() {
  const steps = usePipelineStore((s) => s.steps);

  return (
    <div className="flex flex-col gap-2">
      {STEP_ORDER.map((key) => (
        <PipelineStepCard
          key={key}
          label={STEP_LABELS[key]}
          status={steps[key]?.status ?? "pending"}
          data={steps[key]?.data ?? null}
        />
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Write PlanLegsCards component**

Create `web/src/components/analysis/plan-legs-cards.tsx`:

```typescript
"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { TradeLeg } from "@/types";

function LegCard({ leg }: { leg: TradeLeg }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <Card className="cursor-pointer" onClick={() => setExpanded(!expanded)}>
      <CardHeader className="flex flex-row items-center justify-between py-3">
        <CardTitle className="text-sm font-medium">
          {leg.symbol} — {leg.direction.toUpperCase()}
        </CardTitle>
        <div className="flex gap-2">
          <Badge variant="outline">{leg.strategy}</Badge>
          <Badge variant="secondary">{(leg.confidence * 100).toFixed(0)}%</Badge>
        </div>
      </CardHeader>
      {expanded && (
        <CardContent className="grid grid-cols-2 gap-2 pt-0 text-sm">
          <div>Entry: ₹{leg.entry_price.toFixed(2)}</div>
          <div>Stop Loss: ₹{leg.stop_loss.toFixed(2)}</div>
          <div>Target 1: ₹{leg.target_1.toFixed(2)}</div>
          <div>Target 2: ₹{leg.target_2.toFixed(2)}</div>
          <div>Qty: {leg.quantity}</div>
          <div>Risk: ₹{leg.risk_amount.toFixed(0)}</div>
          <div className="col-span-2 text-muted-foreground">{leg.reasoning}</div>
        </CardContent>
      )}
    </Card>
  );
}

export function PlanLegsCards({ legs }: { legs: TradeLeg[] }) {
  if (legs.length === 0) return null;

  return (
    <div className="mt-6">
      <h3 className="mb-3 text-lg font-semibold">Trade Plan</h3>
      <div className="flex flex-col gap-2">
        {legs.map((leg, i) => (
          <LegCard key={`${leg.symbol}-${i}`} leg={leg} />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Wire up Analysis page**

Replace `web/src/app/analysis/page.tsx`:

```typescript
"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { usePipelineStore } from "@/lib/store";
import { PipelineStepper } from "@/components/analysis/pipeline-stepper";
import { PlanLegsCards } from "@/components/analysis/plan-legs-cards";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import type { TradePlan } from "@/types";

export default function AnalysisPage() {
  const [dateInput, setDateInput] = useState("");
  const queryClient = useQueryClient();
  const pipelineStatus = usePipelineStore((s) => s.status);
  const reset = usePipelineStore((s) => s.reset);

  const { data: analysisStatus } = useQuery({
    queryKey: ["analysis-status"],
    queryFn: api.getAnalysisStatus,
    refetchInterval: pipelineStatus === "running" ? 3_000 : 30_000,
  });

  const { data: latestPlan } = useQuery<TradePlan | null>({
    queryKey: ["latest-plan", analysisStatus?.trade_date],
    queryFn: async () => {
      if (!analysisStatus?.trade_date || analysisStatus.status !== "complete") return null;
      return api.getPlan(analysisStatus.trade_date);
    },
    enabled: analysisStatus?.status === "complete" && !!analysisStatus?.trade_date,
  });

  const runMutation = useMutation({
    mutationFn: (date?: string) => api.postAnalyze(date || undefined),
    onSuccess: () => {
      reset();
      queryClient.invalidateQueries({ queryKey: ["analysis-status"] });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: api.cancelAnalysis,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["analysis-status"] }),
  });

  const isRunning = pipelineStatus === "running" || analysisStatus?.status === "running";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Analysis Pipeline</h1>
        <div className="flex items-center gap-3">
          {analysisStatus && (
            <Badge variant={isRunning ? "default" : "secondary"}>
              {analysisStatus.status}{analysisStatus.trade_date ? ` — ${analysisStatus.trade_date}` : ""}
            </Badge>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3">
        <Input
          type="date"
          value={dateInput}
          onChange={(e) => setDateInput(e.target.value)}
          className="w-48"
          placeholder="Trade date (optional)"
        />
        {isRunning ? (
          <Button variant="destructive" onClick={() => cancelMutation.mutate()} disabled={cancelMutation.isPending}>
            Cancel
          </Button>
        ) : (
          <Button onClick={() => runMutation.mutate(dateInput || undefined)} disabled={runMutation.isPending}>
            Run Analysis
          </Button>
        )}
        {runMutation.isError && <span className="text-sm text-red-500">{runMutation.error.message}</span>}
      </div>

      <PipelineStepper />

      {latestPlan && <PlanLegsCards legs={latestPlan.legs} />}

      {pipelineStatus === "failed" && (
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-700">
          Analysis failed: {usePipelineStore.getState().error}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 7: Verify in browser**

Run dev server + API: `cd web && npm run dev` (in separate terminal: `cd /Users/rmashruwala/work/Personal/Projects/trading-bot && python -m tradingbot serve`).
- Navigate to `/analysis`
- Verify 8 step cards render in grey (pending)
- Click "Run Analysis" — steps should transition grey→yellow→green in real time
- After completion, plan leg cards should appear below

- [ ] **Step 8: Commit**

```bash
cd /Users/rmashruwala/work/Personal/Projects/trading-bot
git add web/src/components/analysis/ web/src/app/analysis/ web/__tests__/components/pipeline-step-card.test.tsx
git commit -m "feat(web): add analysis pipeline page with 8-step stepper, real-time WebSocket updates, and plan leg cards"
```

---

## Task 5: Dashboard Page

**Files:**
- Create: `web/src/components/dashboard/stat-cards.tsx`, `web/src/components/dashboard/equity-curve.tsx`, `web/src/components/dashboard/daily-pnl-chart.tsx`, `web/src/components/dashboard/win-rate-donut.tsx`, `web/src/components/dashboard/last-analysis.tsx`
- Modify: `web/src/app/page.tsx`
- Test: `web/__tests__/components/stat-cards.test.tsx`

**Interfaces:**
- Consumes: `api.getTradeStats()`, `api.getTrades()`, `api.getAnalysisStatus()`, `api.getPlans()` from Task 2. Recharts `LineChart`, `BarChart`, `PieChart`.
- Produces: Dashboard page with 4 stat cards, equity curve, daily P&L bars, win rate donut, last analysis widget.

- [ ] **Step 1: Write stat cards tests**

Create `web/__tests__/components/stat-cards.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatCards } from "@/components/dashboard/stat-cards";
import type { TradeStats } from "@/types";

const mockStats: TradeStats = {
  trade_count: 15,
  win_rate: 0.6,
  total_pnl: 5200.50,
  avg_pnl: 346.70,
  max_drawdown: -1200,
  best_day: 2000,
  worst_day: -800,
};

describe("StatCards", () => {
  it("renders all 4 stat cards with data", () => {
    render(<StatCards stats={mockStats} />);
    expect(screen.getByText("Total P&L")).toBeInTheDocument();
    expect(screen.getByText("Win Rate")).toBeInTheDocument();
    expect(screen.getByText("Trades")).toBeInTheDocument();
    expect(screen.getByText("Max Drawdown")).toBeInTheDocument();
    expect(screen.getByText(/5,200/)).toBeInTheDocument();
    expect(screen.getByText("60%")).toBeInTheDocument();
    expect(screen.getByText("15")).toBeInTheDocument();
  });

  // Review Focus #2: empty trades on fresh install
  it("renders zeros gracefully when no trades", () => {
    const empty: TradeStats = { trade_count: 0, win_rate: 0, total_pnl: 0, avg_pnl: 0, max_drawdown: 0, best_day: 0, worst_day: 0 };
    render(<StatCards stats={empty} />);
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.getByText("0%")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Write StatCards component**

Create `web/src/components/dashboard/stat-cards.tsx`:

```typescript
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { TradeStats } from "@/types";

function formatCurrency(n: number): string {
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString("en-IN", { maximumFractionDigits: 0 });
  return n < 0 ? `-₹${formatted}` : `₹${formatted}`;
}

export function StatCards({ stats }: { stats: TradeStats }) {
  const cards = [
    { title: "Total P&L", value: formatCurrency(stats.total_pnl), color: stats.total_pnl >= 0 ? "text-green-600" : "text-red-600" },
    { title: "Win Rate", value: `${Math.round(stats.win_rate * 100)}%`, color: stats.win_rate >= 0.5 ? "text-green-600" : "text-red-600" },
    { title: "Trades", value: String(stats.trade_count), color: "" },
    { title: "Max Drawdown", value: formatCurrency(stats.max_drawdown), color: "text-red-600" },
  ];

  return (
    <div className="grid grid-cols-4 gap-4">
      {cards.map((c) => (
        <Card key={c.title}>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">{c.title}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${c.color}`}>{c.value}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Run stat card tests**

Run: `cd web && npx vitest run __tests__/components/stat-cards.test.tsx`
Expected: 2 tests pass.

- [ ] **Step 4: Write EquityCurve chart**

Create `web/src/components/dashboard/equity-curve.tsx`:

```typescript
"use client";

import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Trade } from "@/types";

function computeEquityCurve(trades: Trade[]): Array<{ date: string; cumulative: number }> {
  const dailyPnl = new Map<string, number>();
  for (const t of trades) {
    dailyPnl.set(t.trade_date, (dailyPnl.get(t.trade_date) ?? 0) + t.pnl);
  }
  const sorted = [...dailyPnl.entries()].sort(([a], [b]) => a.localeCompare(b));
  let cumulative = 0;
  return sorted.map(([date, pnl]) => {
    cumulative += pnl;
    return { date, cumulative: Math.round(cumulative) };
  });
}

export function EquityCurve({ trades }: { trades: Trade[] }) {
  const data = computeEquityCurve(trades);

  if (data.length === 0) {
    return (
      <Card><CardHeader><CardTitle className="text-sm">Equity Curve</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground">No trades yet</CardContent></Card>
    );
  }

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">Equity Curve</CardTitle></CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Line type="monotone" dataKey="cumulative" stroke="#16a34a" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 5: Write DailyPnlChart**

Create `web/src/components/dashboard/daily-pnl-chart.tsx`:

```typescript
"use client";

import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Trade } from "@/types";

function computeDailyPnl(trades: Trade[]): Array<{ date: string; pnl: number }> {
  const daily = new Map<string, number>();
  for (const t of trades) {
    daily.set(t.trade_date, (daily.get(t.trade_date) ?? 0) + t.pnl);
  }
  return [...daily.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([date, pnl]) => ({ date, pnl: Math.round(pnl) }));
}

export function DailyPnlChart({ trades }: { trades: Trade[] }) {
  const data = computeDailyPnl(trades);

  if (data.length === 0) {
    return (
      <Card><CardHeader><CardTitle className="text-sm">Daily P&L</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground">No trades yet</CardContent></Card>
    );
  }

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">Daily P&L</CardTitle></CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Bar dataKey="pnl">
              {data.map((entry, i) => (
                <Cell key={i} fill={entry.pnl >= 0 ? "#16a34a" : "#dc2626"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 6: Write WinRateDonut**

Create `web/src/components/dashboard/win-rate-donut.tsx`:

```typescript
"use client";

import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function WinRateDonut({ winRate, tradeCount }: { winRate: number; tradeCount: number }) {
  if (tradeCount === 0) {
    return (
      <Card><CardHeader><CardTitle className="text-sm">Win Rate</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground">No trades yet</CardContent></Card>
    );
  }

  const wins = Math.round(winRate * tradeCount);
  const losses = tradeCount - wins;
  const data = [
    { name: "Wins", value: wins },
    { name: "Losses", value: losses },
  ];

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">Win Rate</CardTitle></CardHeader>
      <CardContent className="flex items-center justify-center">
        <ResponsiveContainer width="100%" height={200}>
          <PieChart>
            <Pie data={data} cx="50%" cy="50%" innerRadius={50} outerRadius={80} dataKey="value" label>
              <Cell fill="#16a34a" />
              <Cell fill="#dc2626" />
            </Pie>
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 7: Write LastAnalysis widget**

Create `web/src/components/dashboard/last-analysis.tsx`:

```typescript
"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { PlanSummary } from "@/types";

export function LastAnalysis() {
  const { data: status } = useQuery({ queryKey: ["analysis-status"], queryFn: api.getAnalysisStatus });
  const { data: plans } = useQuery({ queryKey: ["plans"], queryFn: api.getPlans });

  const latest: PlanSummary | undefined = plans?.at(-1);

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">Last Analysis</CardTitle></CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">Status:</span>
          <Badge variant={status?.status === "running" ? "default" : "secondary"}>{status?.status ?? "unknown"}</Badge>
        </div>
        {latest ? (
          <>
            <div><span className="text-muted-foreground">Date:</span> {latest.trade_date}</div>
            <div><span className="text-muted-foreground">Legs:</span> {latest.legs_count}</div>
            <div><span className="text-muted-foreground">Regime:</span> {latest.market_regime}</div>
          </>
        ) : (
          <div className="text-muted-foreground">No plans generated yet</div>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 8: Wire up Dashboard page**

Replace `web/src/app/page.tsx`:

```typescript
"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { StatCards } from "@/components/dashboard/stat-cards";
import { EquityCurve } from "@/components/dashboard/equity-curve";
import { DailyPnlChart } from "@/components/dashboard/daily-pnl-chart";
import { WinRateDonut } from "@/components/dashboard/win-rate-donut";
import { LastAnalysis } from "@/components/dashboard/last-analysis";

export default function DashboardPage() {
  const { data: stats } = useQuery({ queryKey: ["trade-stats"], queryFn: () => api.getTradeStats(30) });
  const { data: trades } = useQuery({ queryKey: ["trades"], queryFn: () => api.getTrades(30) });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>

      {stats && <StatCards stats={stats} />}

      <div className="grid grid-cols-2 gap-4">
        <EquityCurve trades={trades ?? []} />
        <DailyPnlChart trades={trades ?? []} />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <WinRateDonut winRate={stats?.win_rate ?? 0} tradeCount={stats?.trade_count ?? 0} />
        <LastAnalysis />
      </div>
    </div>
  );
}
```

- [ ] **Step 9: Run tests and verify in browser**

Run: `cd web && npx vitest run __tests__/components/stat-cards.test.tsx`
Expected: 2 tests pass.

Verify in browser: Dashboard shows stat cards, charts render (empty state if no trades), last analysis widget shows.

- [ ] **Step 10: Commit**

```bash
cd /Users/rmashruwala/work/Personal/Projects/trading-bot
git add web/src/components/dashboard/ web/src/app/page.tsx web/__tests__/components/stat-cards.test.tsx
git commit -m "feat(web): add dashboard page with stat cards, equity curve, daily P&L chart, win rate donut, and last analysis widget"
```

---

## Task 6: Settings Page

**Files:**
- Create: `web/src/components/settings/config-section.tsx`, `web/src/components/settings/llm-test-button.tsx`
- Modify: `web/src/app/settings/page.tsx`
- Test: `web/__tests__/components/config-section.test.tsx`

**Interfaces:**
- Consumes: `api.getConfig()`, `api.putConfig()`, `api.getProviders()`, `api.testLlm()` from Task 2. shadcn/ui `accordion`, `input`, `select`, `button`, `label`.
- Produces: Settings page with 7 editable config sections, LLM test button, read-only secrets display.

- [ ] **Step 1: Write config section tests**

Create `web/__tests__/components/config-section.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigSection } from "@/components/settings/config-section";

describe("ConfigSection", () => {
  it("renders all fields with current values", () => {
    render(<ConfigSection name="general" fields={{ mode: "paper", capital: 400000 }} onSave={vi.fn()} />);
    expect(screen.getByDisplayValue("paper")).toBeInTheDocument();
    expect(screen.getByDisplayValue("400000")).toBeInTheDocument();
  });

  it("calls onSave with updated values on submit", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ConfigSection name="general" fields={{ capital: 400000 }} onSave={onSave} />);
    const input = screen.getByDisplayValue("400000");
    await user.clear(input);
    await user.type(input, "500000");
    await user.click(screen.getByRole("button", { name: /save/i }));
    expect(onSave).toHaveBeenCalledWith({ capital: 500000 });
  });

  // Review Focus #3: only send changed values
  it("sends only changed fields, not unchanged ones", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ConfigSection name="risk" fields={{ max_risk_per_trade_pct: 0.01, max_daily_loss_pct: 0.02 }} onSave={onSave} />);
    const input = screen.getByDisplayValue("0.01");
    await user.clear(input);
    await user.type(input, "0.015");
    await user.click(screen.getByRole("button", { name: /save/i }));
    expect(onSave).toHaveBeenCalledWith({ max_risk_per_trade_pct: 0.015 });
  });
});
```

- [ ] **Step 2: Write ConfigSection component**

Create `web/src/components/settings/config-section.tsx`:

```typescript
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface Props {
  name: string;
  fields: Record<string, unknown>;
  onSave: (changed: Record<string, unknown>) => Promise<void>;
}

function parseValue(original: unknown, input: string): unknown {
  if (typeof original === "number") {
    const n = Number(input);
    return isNaN(n) ? input : n;
  }
  return input;
}

export function ConfigSection({ name, fields, onSave }: Props) {
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(fields).map(([k, v]) => [k, String(v)]))
  );
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const handleSave = async () => {
    const changed: Record<string, unknown> = {};
    for (const [key, val] of Object.entries(values)) {
      const parsed = parseValue(fields[key], val);
      if (String(parsed) !== String(fields[key])) {
        changed[key] = parsed;
      }
    }
    if (Object.keys(changed).length === 0) return;
    setSaving(true);
    await onSave(changed);
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="space-y-4 rounded border p-4">
      <h3 className="text-sm font-semibold capitalize">{name}</h3>
      <div className="grid grid-cols-2 gap-3">
        {Object.entries(values).map(([key, val]) => (
          <div key={key}>
            <Label className="text-xs text-muted-foreground">{key}</Label>
            <Input
              value={val}
              onChange={(e) => setValues((prev) => ({ ...prev, [key]: e.target.value }))}
              className="mt-1"
            />
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={handleSave} disabled={saving}>
          {saving ? "Saving..." : "Save"}
        </Button>
        {saved && <span className="text-xs text-green-600">Saved</span>}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Run config section tests**

Run: `cd web && npx vitest run __tests__/components/config-section.test.tsx`
Expected: 3 tests pass.

- [ ] **Step 4: Write LLM test button**

Create `web/src/components/settings/llm-test-button.tsx`:

```typescript
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

export function LlmTestButton() {
  const [result, setResult] = useState<{ ok: boolean; error?: string } | null>(null);
  const [testing, setTesting] = useState(false);

  const handleTest = async () => {
    setTesting(true);
    setResult(null);
    try {
      const res = await api.testLlm();
      setResult(res);
    } catch (e) {
      setResult({ ok: false, error: e instanceof Error ? e.message : "Unknown error" });
    }
    setTesting(false);
  };

  return (
    <div className="flex items-center gap-3">
      <Button size="sm" variant="outline" onClick={handleTest} disabled={testing}>
        {testing ? "Testing..." : "Test Connection"}
      </Button>
      {result && (
        <span className={`text-xs ${result.ok ? "text-green-600" : "text-red-600"}`}>
          {result.ok ? "Connection OK" : `Failed: ${result.error}`}
        </span>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Wire up Settings page**

Replace `web/src/app/settings/page.tsx`:

```typescript
"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ConfigSection } from "@/components/settings/config-section";
import { LlmTestButton } from "@/components/settings/llm-test-button";

const SECTION_ORDER = ["general", "scanner", "strategy", "risk", "execution", "llm", "paper"];

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { data: config, isLoading } = useQuery({ queryKey: ["config"], queryFn: api.getConfig });

  if (isLoading || !config) return <div>Loading config...</div>;

  const handleSave = async (section: string, changed: Record<string, unknown>) => {
    await api.putConfig(section, changed);
    queryClient.invalidateQueries({ queryKey: ["config"] });
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>

      {SECTION_ORDER.map((section) => (
        <div key={section}>
          <ConfigSection
            name={section}
            fields={config[section as keyof typeof config] as Record<string, unknown>}
            onSave={(changed) => handleSave(section, changed)}
          />
          {section === "llm" && (
            <div className="mt-2 ml-4">
              <LlmTestButton />
            </div>
          )}
        </div>
      ))}

      <div className="space-y-2 rounded border p-4 opacity-60">
        <h3 className="text-sm font-semibold">Secrets (read-only)</h3>
        <div className="grid grid-cols-2 gap-2 text-sm text-muted-foreground">
          {Object.entries(config.secrets).map(([key, val]) => (
            <div key={key}><span className="font-mono">{key}:</span> {val}</div>
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Verify in browser**

Navigate to `/settings`. Verify:
- All 7 sections render with current config values
- Editing a field and clicking Save updates the value
- LLM test button shows connection result
- Secrets section is read-only and masked

- [ ] **Step 7: Commit**

```bash
cd /Users/rmashruwala/work/Personal/Projects/trading-bot
git add web/src/components/settings/ web/src/app/settings/ web/__tests__/components/config-section.test.tsx
git commit -m "feat(web): add settings page with 7 editable config sections, LLM test button, and read-only secrets"
```

---

## Task 7: History Page

**Files:**
- Create: `web/src/components/history/trade-table.tsx`, `web/src/components/history/day-group.tsx`
- Modify: `web/src/app/history/page.tsx`
- Test: `web/__tests__/components/day-group.test.tsx`

**Interfaces:**
- Consumes: `api.getTrades()`, `api.getTradeStats()` from Task 2. shadcn/ui `card`, `collapsible`, `badge`.
- Produces: History page with stats summary, period selector, date-grouped collapsible trade sections.

- [ ] **Step 1: Write day group tests**

Create `web/__tests__/components/day-group.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DayGroup } from "@/components/history/day-group";
import type { Trade } from "@/types";

const trade: Trade = {
  trade_date: "2026-09-25",
  symbol: "RELIANCE",
  strategy: "breakout",
  direction: "long",
  quantity: 10,
  entry_price: 2450.50,
  exit_price: 2480.00,
  pnl: 295.00,
  exit_reason: "target_1",
  status: "closed",
  mode: "paper",
  entered_at: "2026-09-25T09:30:00+05:30",
  exited_at: "2026-09-25T11:15:00+05:30",
};

describe("DayGroup", () => {
  it("renders date header with trade count and daily P&L", () => {
    render(<DayGroup date="2026-09-25" trades={[trade]} dailyPnl={295} />);
    expect(screen.getByText("2026-09-25")).toBeInTheDocument();
    expect(screen.getByText("1 trade")).toBeInTheDocument();
    expect(screen.getByText(/295/)).toBeInTheDocument();
  });

  it("expands to show trade table on click", async () => {
    const user = userEvent.setup();
    render(<DayGroup date="2026-09-25" trades={[trade]} dailyPnl={295} />);
    await user.click(screen.getByText("2026-09-25"));
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText("breakout")).toBeInTheDocument();
  });

  // Review Focus #2: empty trades
  it("renders zero trades gracefully", () => {
    render(<DayGroup date="2026-09-25" trades={[]} dailyPnl={0} />);
    expect(screen.getByText("0 trades")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Write TradeTable component**

Create `web/src/components/history/trade-table.tsx`:

```typescript
import type { Trade } from "@/types";

function formatCurrency(n: number): string {
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  return n < 0 ? `-₹${formatted}` : `₹${formatted}`;
}

export function TradeTable({ trades }: { trades: Trade[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b text-left text-xs text-muted-foreground">
          <th className="py-2">Symbol</th>
          <th>Strategy</th>
          <th>Direction</th>
          <th className="text-right">Qty</th>
          <th className="text-right">Entry</th>
          <th className="text-right">Exit</th>
          <th className="text-right">P&L</th>
          <th>Exit Reason</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {trades.map((t, i) => (
          <tr key={i} className="border-b last:border-0">
            <td className="py-2 font-medium">{t.symbol}</td>
            <td>{t.strategy}</td>
            <td>{t.direction}</td>
            <td className="text-right">{t.quantity}</td>
            <td className="text-right">₹{t.entry_price.toFixed(2)}</td>
            <td className="text-right">₹{t.exit_price.toFixed(2)}</td>
            <td className={`text-right font-medium ${t.pnl >= 0 ? "text-green-600" : "text-red-600"}`}>
              {formatCurrency(t.pnl)}
            </td>
            <td>{t.exit_reason}</td>
            <td>{t.status}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 3: Write DayGroup component**

Create `web/src/components/history/day-group.tsx`:

```typescript
"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { TradeTable } from "./trade-table";
import type { Trade } from "@/types";

function formatCurrency(n: number): string {
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString("en-IN", { maximumFractionDigits: 0 });
  return n < 0 ? `-₹${formatted}` : `₹${formatted}`;
}

interface Props {
  date: string;
  trades: Trade[];
  dailyPnl: number;
}

export function DayGroup({ date, trades, dailyPnl }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <Card className="cursor-pointer" onClick={() => setOpen(!open)}>
      <CardHeader className="flex flex-row items-center justify-between py-3">
        <div className="flex items-center gap-3">
          <span className="font-medium">{date}</span>
          <span className="text-sm text-muted-foreground">
            {trades.length} trade{trades.length !== 1 ? "s" : ""}
          </span>
        </div>
        <span className={`font-semibold ${dailyPnl >= 0 ? "text-green-600" : "text-red-600"}`}>
          {formatCurrency(dailyPnl)}
        </span>
      </CardHeader>
      {open && trades.length > 0 && (
        <CardContent className="pt-0" onClick={(e) => e.stopPropagation()}>
          <TradeTable trades={trades} />
        </CardContent>
      )}
    </Card>
  );
}
```

- [ ] **Step 4: Run day group tests**

Run: `cd web && npx vitest run __tests__/components/day-group.test.tsx`
Expected: 3 tests pass.

- [ ] **Step 5: Wire up History page**

Replace `web/src/app/history/page.tsx`:

```typescript
"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { DayGroup } from "@/components/history/day-group";
import { StatCards } from "@/components/dashboard/stat-cards";
import { Button } from "@/components/ui/button";
import type { Trade } from "@/types";

const PERIODS = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "All", days: 9999 },
];

function groupByDate(trades: Trade[]): Map<string, { trades: Trade[]; pnl: number }> {
  const groups = new Map<string, { trades: Trade[]; pnl: number }>();
  for (const t of trades) {
    const existing = groups.get(t.trade_date) ?? { trades: [], pnl: 0 };
    existing.trades.push(t);
    existing.pnl += t.pnl;
    groups.set(t.trade_date, existing);
  }
  return new Map([...groups.entries()].sort(([a], [b]) => b.localeCompare(a)));
}

export default function HistoryPage() {
  const [days, setDays] = useState(30);
  const { data: stats } = useQuery({ queryKey: ["trade-stats", days], queryFn: () => api.getTradeStats(days) });
  const { data: trades } = useQuery({ queryKey: ["trades", days], queryFn: () => api.getTrades(days) });

  const grouped = groupByDate(trades ?? []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Trade History</h1>
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <Button
              key={p.label}
              size="sm"
              variant={days === p.days ? "default" : "outline"}
              onClick={() => setDays(p.days)}
            >
              {p.label}
            </Button>
          ))}
        </div>
      </div>

      {stats && <StatCards stats={stats} />}

      <div className="flex flex-col gap-2">
        {grouped.size === 0 ? (
          <div className="py-8 text-center text-muted-foreground">No trades in this period</div>
        ) : (
          [...grouped.entries()].map(([date, { trades: dayTrades, pnl }]) => (
            <DayGroup key={date} date={date} trades={dayTrades} dailyPnl={pnl} />
          ))
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Verify in browser**

Navigate to `/history`. Verify:
- Stats summary shows at top
- Period selector switches between 7d/30d/90d/All
- Empty state shows "No trades in this period"
- With trades: collapsible day groups with P&L color coding

- [ ] **Step 7: Commit**

```bash
cd /Users/rmashruwala/work/Personal/Projects/trading-bot
git add web/src/components/history/ web/src/app/history/ web/__tests__/components/day-group.test.tsx
git commit -m "feat(web): add history page with date-grouped trades, period selector, and stats summary"
```

---

## Task 8: Final Verification + Build Check

**Files:**
- None created. This is a verification-only task.

**Interfaces:**
- Consumes: Everything from Tasks 1-7.
- Produces: Green `npm run build` and full test suite pass.

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/rmashruwala/work/Personal/Projects/trading-bot/web && npx vitest run
```

Expected: ~33 tests pass across all test files.

- [ ] **Step 2: Run TypeScript build**

```bash
cd /Users/rmashruwala/work/Personal/Projects/trading-bot/web && npm run build
```

Expected: Build succeeds with zero TypeScript errors.

- [ ] **Step 3: Fix any issues**

If tests fail or build errors exist, fix them. Common issues:
- Import path mismatches (check `@/` alias resolves)
- Missing shadcn component installs
- Type mismatches between API response and TypeScript interface

- [ ] **Step 4: Verify all pages in browser with API running**

Start API: `cd /Users/rmashruwala/work/Personal/Projects/trading-bot && python -m tradingbot serve`
Start frontend: `cd web && npm run dev`

Check each page:
- Dashboard: stat cards load, charts render (empty state OK)
- Analysis: 8 steps render, Run Analysis triggers pipeline
- Settings: config loads, editing and saving works
- History: trades load, period selector works
- Top bar: health indicator shows green when API running

- [ ] **Step 5: Commit if any fixes were needed**

```bash
cd /Users/rmashruwala/work/Personal/Projects/trading-bot
git add web/
git commit -m "fix(web): resolve build and test issues from final verification"
```

- [ ] **Step 6: Run backend tests to confirm no regressions**

```bash
cd /Users/rmashruwala/work/Personal/Projects/trading-bot && python -m pytest -x -q
```

Expected: 307 tests pass (no backend changes were made).
