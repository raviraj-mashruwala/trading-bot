# Frontend V2 Pipeline UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the Next.js frontend to support the v2 analysis pipeline — Kite login, multi-run analysis display, ranked setup management, and v2 pipeline trigger.

**Architecture:** Extend existing patterns (TanStack Query + Zustand + Recharts + shadcn-style components). Add new types, API functions, and components. No new dependencies. All pages follow DESIGN.md tokens (Satoshi/Instrument Sans/JetBrains Mono, gold accent #d4a015, dark navy #070a0f).

**Tech Stack:** Next.js 16, React 19, TanStack Query v5, Zustand v5, Tailwind 4, TypeScript 5

**Spec:** `docs/superpowers/specs/2026-09-27-analysis-pipeline-redesign.md` (Section 7: Persistence & Multi-Run, Section 8: Kite Execution)

## Global Constraints

- `npm --legacy-peer-deps` for all installs in web/
- DESIGN.md is source of truth for all visual decisions — read before any UI work
- Fonts: Satoshi (display, 700), Instrument Sans (body, 13px), JetBrains Mono (numbers/stats)
- Colors: gold accent #d4a015, bg #070a0f, surface #0f1419, success #2da44e, error #f85149
- No new npm dependencies — use existing Tailwind, Recharts, Lucide icons
- shadcn CLI doesn't work — create components manually following existing patterns in `web/src/components/ui/`
- Existing 45 JS tests must keep passing
- All API calls through `web/src/lib/api.ts` — never fetch directly from components

## Review Focus

1. **Kite callback race condition:** User lands on /auth/kite/callback before the token exchange completes. The callback page must show a loading state and poll /auth/kite/status, not assume instant auth.
2. **Empty state on first v2 run:** DailyPlan returns empty ranked_suggestions before any analysis runs. The UI must show "Run analysis first" prompt, not a blank page or error.
3. **Stale React Query cache after new analysis run:** After POST /analyze completes, the plans/today and plans/runs queries must invalidate. Without this, the UI shows old data until manual refresh.
4. **Setup action optimistic update:** PATCH /setups/{id} should optimistically update the UI, then revert on error. Without this, approve/reject buttons feel laggy.
5. **WebSocket disconnect during analysis:** If WS drops mid-analysis, the pipeline stepper should fall back to polling /analyze/status instead of freezing.

---

### Task 1: Types + API Client Extensions

**Files:**
- Modify: `web/src/types/index.ts`
- Modify: `web/src/lib/api.ts`

**Interfaces:**
- Consumes: Backend endpoints — GET /auth/kite/login, /status, /callback, GET /plans/today, /plans/runs, /plans/setups, PATCH /setups/{id}, POST /analyze with pipeline param
- Produces: TypeScript types (`KiteAuthStatus`, `AnalysisRun`, `RankedSuggestion`, `DailyPlan`, `Setup`) and API functions consumed by all subsequent tasks

- [ ] **Step 1: Add new types to types/index.ts**

```typescript
// Add to web/src/types/index.ts

export interface KiteAuthStatus {
  authenticated: boolean;
  user_id?: string;
}

export interface AnalysisRun {
  run_id: string;
  trade_date: string;
  timestamp: string;
  market_regime: string;
  regime_confidence: number;
  total_scanned: number;
  tier1_passed: number;
  tier2_shortlisted: number;
  setups_proposed: number;
  setups_approved: number;
  llm_calls: number;
  llm_cost_usd: number;
  duration_seconds: number;
}

export interface Setup {
  id: number;
  run_id: string;
  trade_date: string;
  symbol: string;
  strategy: string;
  direction: "long" | "short";
  entry_price: number;
  stop_loss: number;
  target_1: number;
  target_2: number | null;
  confidence: number;
  status: "proposed" | "approved" | "rejected" | "active" | "filled" | "expired" | "closed";
  reasoning: string;
  rejection_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface RankedSuggestion {
  rank: number;
  symbol: string;
  direction: string;
  confidence: number;
  consistency: number;
  run_count: number;
  recommendation: "execute" | "watch" | "conflicting" | "stale";
  best_setup: Setup;
}

export interface DailyPlan {
  date: string;
  runs: AnalysisRun[];
  total_runs: number;
  active_setups: Setup[];
  ranked_suggestions: RankedSuggestion[];
}
```

- [ ] **Step 2: Add API functions to api.ts**

```typescript
// Add to web/src/lib/api.ts

// Kite Auth
getKiteLoginUrl: () => get<{ login_url: string }>("/auth/kite/login"),
getKiteStatus: () => get<KiteAuthStatus>("/auth/kite/status"),
kiteCallback: (requestToken: string) =>
  get<{ authenticated: boolean; user_id: string }>(
    `/auth/kite/callback?request_token=${requestToken}`
  ),

// V2 Pipeline
getDailyPlan: () => get<DailyPlan>("/plans/today"),
getAnalysisRuns: (tradeDate?: string) =>
  get<AnalysisRun[]>(`/plans/runs${tradeDate ? `?trade_date=${tradeDate}` : ""}`),
getSetups: (symbol?: string, tradeDate?: string) => {
  const params = new URLSearchParams();
  if (symbol) params.set("symbol", symbol);
  if (tradeDate) params.set("trade_date", tradeDate);
  const qs = params.toString();
  return get<Setup[]>(`/plans/setups${qs ? `?${qs}` : ""}`);
},
patchSetup: (setupId: number, status: string, reason?: string) =>
  post<{ ok: boolean }>(`/setups/${setupId}`, { status, reason }),
```

Also update `postAnalyze` to accept pipeline version:

```typescript
postAnalyze: (tradeDate?: string, pipeline: string = "v2") =>
  post<{ status: string; trade_date: string }>("/analyze", {
    ...(tradeDate ? { trade_date: tradeDate } : {}),
    pipeline,
  }),
```

- [ ] **Step 3: Add type imports to api.ts**

Update the imports at the top of `api.ts` to include new types from `types/index.ts`.

- [ ] **Step 4: Verify build**

Run: `cd web && npx next build 2>&1 | tail -5`
Expected: Build succeeds with no type errors

- [ ] **Step 5: Commit**

```bash
git add web/src/types/index.ts web/src/lib/api.ts
git commit -m "feat(web): add v2 pipeline types and API functions

KiteAuthStatus, AnalysisRun, Setup, RankedSuggestion, DailyPlan types.
API: kite auth, daily plan, runs, setups, patch setup.
postAnalyze defaults to pipeline=v2."
```

---

### Task 2: Kite Auth Flow UI

**Files:**
- Create: `web/src/components/auth/kite-connect-button.tsx`
- Create: `web/src/app/auth/kite/callback/page.tsx`
- Modify: `web/src/components/layout/top-bar.tsx`

**Interfaces:**
- Consumes: `api.getKiteStatus()`, `api.getKiteLoginUrl()`, `api.kiteCallback()` from Task 1
- Produces: `KiteConnectButton` component (used in TopBar), `/auth/kite/callback` page

- [ ] **Step 1: Create KiteConnectButton component**

```tsx
// web/src/components/auth/kite-connect-button.tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function KiteConnectButton() {
  const { data: status, isLoading } = useQuery({
    queryKey: ["kite-status"],
    queryFn: api.getKiteStatus,
    refetchInterval: 30_000,
  });

  const handleConnect = async () => {
    const { login_url } = await api.getKiteLoginUrl();
    window.location.href = login_url;
  };

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-surface text-text-muted text-xs font-medium">
        <div className="w-2 h-2 rounded-full bg-text-muted animate-pulse" />
        Kite
      </div>
    );
  }

  if (status?.authenticated) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-surface text-xs font-medium">
        <div className="w-2 h-2 rounded-full bg-success" />
        <span className="text-success">Kite Connected</span>
      </div>
    );
  }

  return (
    <button
      onClick={handleConnect}
      className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-accent/10 text-accent text-xs font-medium hover:bg-accent/20 transition-colors"
    >
      <div className="w-2 h-2 rounded-full bg-error" />
      Connect Kite
    </button>
  );
}
```

- [ ] **Step 2: Create callback page**

```tsx
// web/src/app/auth/kite/callback/page.tsx
"use client";

import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";

export default function KiteCallbackPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    const requestToken = searchParams.get("request_token");
    if (!requestToken) {
      setStatus("error");
      setError("No request_token in URL. Please try logging in again.");
      return;
    }

    api.kiteCallback(requestToken)
      .then(() => {
        setStatus("success");
        queryClient.invalidateQueries({ queryKey: ["kite-status"] });
        setTimeout(() => router.push("/analysis"), 2000);
      })
      .catch((err) => {
        setStatus("error");
        setError(err.message || "Token exchange failed");
      });
  }, [searchParams, router, queryClient]);

  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="bg-surface rounded-lg p-8 max-w-md w-full text-center">
        {status === "loading" && (
          <>
            <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin mx-auto mb-4" />
            <h2 className="text-lg font-display font-bold text-text mb-2">
              Connecting to Kite...
            </h2>
            <p className="text-text-muted text-sm">Exchanging token with Zerodha</p>
          </>
        )}
        {status === "success" && (
          <>
            <div className="w-8 h-8 rounded-full bg-success/20 text-success flex items-center justify-center mx-auto mb-4 text-xl">
              ✓
            </div>
            <h2 className="text-lg font-display font-bold text-text mb-2">
              Kite Connected
            </h2>
            <p className="text-text-muted text-sm">Redirecting to analysis...</p>
          </>
        )}
        {status === "error" && (
          <>
            <div className="w-8 h-8 rounded-full bg-error/20 text-error flex items-center justify-center mx-auto mb-4 text-xl">
              ✗
            </div>
            <h2 className="text-lg font-display font-bold text-text mb-2">
              Connection Failed
            </h2>
            <p className="text-text-muted text-sm mb-4">{error}</p>
            <button
              onClick={() => router.push("/analysis")}
              className="px-4 py-2 bg-accent text-bg rounded-md text-sm font-medium hover:bg-accent/90"
            >
              Back to Analysis
            </button>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Add KiteConnectButton to TopBar**

In `web/src/components/layout/top-bar.tsx`, import and add `KiteConnectButton` next to the health status indicator.

- [ ] **Step 4: Create directory for callback page**

```bash
mkdir -p web/src/app/auth/kite/callback
```

- [ ] **Step 5: Verify in browser**

Run: `cd web && npm run dev`
Check: TopBar shows "Connect Kite" button (red dot). Clicking redirects to Kite login URL.
Check: /auth/kite/callback shows loading state, handles missing token gracefully.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/auth/ web/src/app/auth/ web/src/components/layout/top-bar.tsx
git commit -m "feat(web): add Kite OAuth login flow

KiteConnectButton in TopBar shows auth status (red/green dot).
/auth/kite/callback page handles token exchange with loading/success/error states.
Auto-redirects to analysis page on success."
```

---

### Task 3: Analysis Page — V2 Pipeline + Run History

**Files:**
- Modify: `web/src/app/analysis/page.tsx`
- Create: `web/src/components/analysis/run-history.tsx`
- Modify: `web/src/lib/store.ts` (pipeline store)

**Interfaces:**
- Consumes: `api.postAnalyze(date, "v2")`, `api.getAnalysisRuns()`, `api.getDailyPlan()` from Task 1
- Produces: Updated analysis page with v2 trigger + run history panel

- [ ] **Step 1: Create RunHistory component**

```tsx
// web/src/components/analysis/run-history.tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AnalysisRun } from "@/types";

export function RunHistory() {
  const { data: runs, isLoading } = useQuery({
    queryKey: ["analysis-runs"],
    queryFn: () => api.getAnalysisRuns(),
    refetchInterval: 10_000,
  });

  if (isLoading) {
    return <div className="text-text-muted text-sm">Loading runs...</div>;
  }

  if (!runs || runs.length === 0) {
    return (
      <div className="text-text-muted text-sm py-4 text-center">
        No analysis runs today. Click &quot;Run Analysis&quot; to start.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-text-muted uppercase tracking-wider">
        Today&apos;s Runs
      </h3>
      {runs.map((run: AnalysisRun) => (
        <div
          key={run.run_id}
          className="bg-surface rounded-lg p-3 border border-border/50"
        >
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-mono text-text-muted">
              {new Date(run.timestamp).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
            </span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-accent/10 text-accent">
              {run.market_regime.replace("_", " ")}
            </span>
          </div>
          <div className="grid grid-cols-4 gap-2 text-xs">
            <div>
              <span className="text-text-muted">Scanned</span>
              <p className="font-mono text-text">{run.total_scanned}</p>
            </div>
            <div>
              <span className="text-text-muted">Tier 1</span>
              <p className="font-mono text-text">{run.tier1_passed}</p>
            </div>
            <div>
              <span className="text-text-muted">Shortlist</span>
              <p className="font-mono text-text">{run.tier2_shortlisted}</p>
            </div>
            <div>
              <span className="text-text-muted">Approved</span>
              <p className="font-mono text-success">{run.setups_approved}</p>
            </div>
          </div>
          <div className="flex items-center gap-3 mt-2 text-xs text-text-muted">
            <span>{run.llm_calls} LLM calls</span>
            <span>{run.duration_seconds.toFixed(1)}s</span>
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Update analysis page to use v2 and show run history**

Modify `web/src/app/analysis/page.tsx`:
- The existing `postAnalyze()` call should now pass `pipeline: "v2"` (handled by api.ts default in Task 1)
- Add `RunHistory` component below the pipeline stepper
- After analysis completes, invalidate `["analysis-runs"]` and `["daily-plan"]` queries
- Add `useQueryClient` to invalidate queries on WebSocket `analysis.complete` event

- [ ] **Step 3: Update pipeline store to invalidate queries**

In `web/src/lib/store.ts`, update the `handleEvent` method for `analysis.complete` to also trigger React Query cache invalidation. Since Zustand and React Query are separate, pass an `onAnalysisComplete` callback.

- [ ] **Step 4: Verify in browser**

Run: `cd web && npm run dev`
Check: Analysis page shows "Run Analysis" button. After clicking, pipeline stepper shows progress.
Check: Run history panel shows completed runs with stats.
Check: Multiple runs accumulate (don't replace).

- [ ] **Step 5: Commit**

```bash
git add web/src/app/analysis/page.tsx web/src/components/analysis/run-history.tsx web/src/lib/store.ts
git commit -m "feat(web): add run history panel + v2 pipeline trigger

Analysis page defaults to v2 pipeline. RunHistory component shows
today's runs with regime, funnel stats, duration. Queries invalidate
on analysis.complete WebSocket event."
```

---

### Task 4: Ranked Setups Display + Management

**Files:**
- Create: `web/src/components/analysis/ranked-setups.tsx`
- Create: `web/src/components/analysis/setup-card.tsx`
- Modify: `web/src/app/analysis/page.tsx`

**Interfaces:**
- Consumes: `api.getDailyPlan()`, `api.patchSetup()` from Task 1, `DailyPlan`, `RankedSuggestion`, `Setup` types
- Produces: `RankedSetups` and `SetupCard` components with approve/reject/watch actions

- [ ] **Step 1: Create SetupCard component**

```tsx
// web/src/components/analysis/setup-card.tsx
"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { RankedSuggestion } from "@/types";

const RECOMMENDATION_COLORS: Record<string, string> = {
  execute: "bg-success/10 text-success",
  watch: "bg-accent/10 text-accent",
  conflicting: "bg-error/10 text-error",
  stale: "bg-text-muted/10 text-text-muted",
};

export function SetupCard({ suggestion }: { suggestion: RankedSuggestion }) {
  const queryClient = useQueryClient();
  const setup = suggestion.best_setup;

  const mutation = useMutation({
    mutationFn: ({ status, reason }: { status: string; reason?: string }) =>
      api.patchSetup(setup.id, status, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["daily-plan"] });
    },
  });

  const riskReward =
    setup.stop_loss > 0
      ? Math.abs(setup.target_1 - setup.entry_price) /
        Math.abs(setup.entry_price - setup.stop_loss)
      : 0;

  return (
    <div className="bg-surface rounded-lg border border-border/50 p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="text-xs font-mono text-text-muted">#{suggestion.rank}</span>
          <span className="text-base font-display font-bold text-text">{setup.symbol}</span>
          <span
            className={`text-xs px-2 py-0.5 rounded-full ${
              setup.direction === "long" ? "bg-success/10 text-success" : "bg-error/10 text-error"
            }`}
          >
            {setup.direction.toUpperCase()}
          </span>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded-full ${RECOMMENDATION_COLORS[suggestion.recommendation] || ""}`}>
          {suggestion.recommendation}
        </span>
      </div>

      {/* Price levels */}
      <div className="grid grid-cols-4 gap-3 mb-3">
        <div>
          <span className="text-xs text-text-muted block">Entry</span>
          <span className="font-mono text-sm text-text">₹{setup.entry_price.toFixed(1)}</span>
        </div>
        <div>
          <span className="text-xs text-text-muted block">Stop Loss</span>
          <span className="font-mono text-sm text-error">₹{setup.stop_loss.toFixed(1)}</span>
        </div>
        <div>
          <span className="text-xs text-text-muted block">Target 1</span>
          <span className="font-mono text-sm text-success">₹{setup.target_1.toFixed(1)}</span>
        </div>
        <div>
          <span className="text-xs text-text-muted block">R:R</span>
          <span className="font-mono text-sm text-accent">{riskReward.toFixed(1)}:1</span>
        </div>
      </div>

      {/* Confidence + consistency */}
      <div className="flex items-center gap-4 mb-3">
        <div className="flex-1">
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-text-muted">Confidence</span>
            <span className="font-mono text-text">{(suggestion.confidence * 100).toFixed(0)}%</span>
          </div>
          <div className="h-1.5 bg-bg rounded-full overflow-hidden">
            <div
              className="h-full bg-accent rounded-full"
              style={{ width: `${suggestion.confidence * 100}%` }}
            />
          </div>
        </div>
        <div className="text-xs text-text-muted">
          <span className="font-mono text-text">{suggestion.run_count}</span> run{suggestion.run_count !== 1 ? "s" : ""} agree
          <span className="ml-1 font-mono text-accent">
            ({(suggestion.consistency * 100).toFixed(0)}%)
          </span>
        </div>
      </div>

      {/* Strategy + reasoning */}
      <div className="text-xs text-text-muted mb-3">
        <span className="text-text font-medium">{setup.strategy.replace(/_/g, " ")}</span>
        {setup.reasoning && <span className="ml-2">— {setup.reasoning}</span>}
      </div>

      {/* Actions */}
      {setup.status === "approved" && (
        <div className="flex items-center gap-2">
          <button
            onClick={() => mutation.mutate({ status: "active" })}
            disabled={mutation.isPending}
            className="flex-1 px-3 py-1.5 bg-success/10 text-success text-xs font-medium rounded-md hover:bg-success/20 transition-colors disabled:opacity-50"
          >
            Execute
          </button>
          <button
            onClick={() => mutation.mutate({ status: "rejected", reason: "manual reject" })}
            disabled={mutation.isPending}
            className="px-3 py-1.5 bg-error/10 text-error text-xs font-medium rounded-md hover:bg-error/20 transition-colors disabled:opacity-50"
          >
            Reject
          </button>
        </div>
      )}
      {setup.status === "proposed" && (
        <div className="flex items-center gap-2">
          <button
            onClick={() => mutation.mutate({ status: "approved" })}
            disabled={mutation.isPending}
            className="flex-1 px-3 py-1.5 bg-accent/10 text-accent text-xs font-medium rounded-md hover:bg-accent/20 transition-colors disabled:opacity-50"
          >
            Approve
          </button>
          <button
            onClick={() => mutation.mutate({ status: "rejected", reason: "manual reject" })}
            disabled={mutation.isPending}
            className="px-3 py-1.5 bg-error/10 text-error text-xs font-medium rounded-md hover:bg-error/20 transition-colors disabled:opacity-50"
          >
            Reject
          </button>
        </div>
      )}
      {setup.status === "rejected" && (
        <div className="text-xs text-error/60">
          Rejected{setup.rejection_reason ? `: ${setup.rejection_reason}` : ""}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create RankedSetups container**

```tsx
// web/src/components/analysis/ranked-setups.tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { SetupCard } from "./setup-card";
import type { DailyPlan } from "@/types";

export function RankedSetups() {
  const { data: plan, isLoading } = useQuery({
    queryKey: ["daily-plan"],
    queryFn: api.getDailyPlan,
    refetchInterval: 10_000,
  });

  if (isLoading) {
    return <div className="text-text-muted text-sm py-4">Loading setups...</div>;
  }

  if (!plan || plan.ranked_suggestions.length === 0) {
    return (
      <div className="bg-surface rounded-lg border border-border/50 p-6 text-center">
        <p className="text-text-muted text-sm">
          No setups yet. Run analysis to generate trade setups.
        </p>
      </div>
    );
  }

  const executeCount = plan.ranked_suggestions.filter(
    (s) => s.recommendation === "execute"
  ).length;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-text-muted uppercase tracking-wider">
          Ranked Setups
        </h3>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-text-muted">{plan.total_runs} run(s)</span>
          <span className="text-success">{executeCount} ready</span>
          <span className="text-text-muted">
            {plan.ranked_suggestions.length} total
          </span>
        </div>
      </div>
      {plan.ranked_suggestions.map((suggestion) => (
        <SetupCard key={`${suggestion.symbol}-${suggestion.rank}`} suggestion={suggestion} />
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Add RankedSetups to analysis page**

In `web/src/app/analysis/page.tsx`, import and render `RankedSetups` below the pipeline stepper and plan legs section. Layout:
- Left column (2/3): Pipeline stepper + progress
- Right column (1/3): Run history
- Full width below: Ranked setups

- [ ] **Step 4: Verify in browser**

Run: `cd web && npm run dev`
Check: After analysis completes, ranked setups appear with confidence bars, R:R, strategy.
Check: Approve/reject buttons work (optimistic update).
Check: Multiple runs show consistency indicator ("2 runs agree").
Check: Empty state shows "No setups yet" message.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/analysis/setup-card.tsx web/src/components/analysis/ranked-setups.tsx web/src/app/analysis/page.tsx
git commit -m "feat(web): add ranked setups display with approve/reject management

SetupCard shows entry/SL/target levels, confidence bar, R:R ratio,
cross-run consistency, strategy. Execute/approve/reject actions with
optimistic mutation. RankedSetups container fetches DailyPlan."
```

---

### Task 5: Analysis Page Layout + Query Invalidation

**Files:**
- Modify: `web/src/app/analysis/page.tsx` (final layout assembly)
- Modify: `web/src/lib/store.ts` (WebSocket → query invalidation bridge)

**Interfaces:**
- Consumes: All components from Tasks 2-4, WebSocket events from `ws.ts`
- Produces: Complete analysis page with v2 pipeline, run history, ranked setups, and live updates

- [ ] **Step 1: Wire WebSocket events to React Query invalidation**

In `web/src/lib/store.ts`, add a query client reference and invalidation on `analysis.complete`:

```typescript
// At the module level or in a provider, bridge WS → React Query:
// When ws receives "analysis.complete", call:
//   queryClient.invalidateQueries({ queryKey: ["daily-plan"] })
//   queryClient.invalidateQueries({ queryKey: ["analysis-runs"] })
//   queryClient.invalidateQueries({ queryKey: ["analysis-status"] })
```

The cleanest approach: in `providers.tsx`, subscribe to WS events and call `queryClient.invalidateQueries` inside the effect that handles WS messages.

- [ ] **Step 2: Assemble final analysis page layout**

The analysis page should have this layout:

```
┌─────────────────────────────────────────────────┐
│  Run Analysis (button)    [Kite status badge]    │
├──────────────────────────┬──────────────────────┤
│  Pipeline Stepper        │  Run History         │
│  (progress + steps)      │  (today's runs)      │
├──────────────────────────┴──────────────────────┤
│  Ranked Setups (full width)                      │
│  [SetupCard] [SetupCard] [SetupCard]...         │
└─────────────────────────────────────────────────┘
```

- [ ] **Step 3: Verify full flow in browser**

Run: `cd web && npm run dev`
Check the full flow:
1. Page loads → shows Kite status + "Run Analysis" button
2. If Kite not connected → "Connect Kite" in TopBar
3. Click "Run Analysis" → pipeline stepper animates through stages
4. On complete → run appears in history panel, setups appear in ranked list
5. Click "Run Analysis" again → second run, setups accumulate/update
6. Approve/reject a setup → status updates immediately

- [ ] **Step 4: Run existing frontend tests**

Run: `cd web && npx vitest run 2>&1 | tail -10`
Expected: All existing tests pass

- [ ] **Step 5: Commit**

```bash
git add web/src/app/analysis/page.tsx web/src/lib/store.ts web/src/app/providers.tsx
git commit -m "feat(web): complete analysis page with v2 pipeline + live updates

Final layout: pipeline stepper + run history + ranked setups.
WebSocket analysis.complete event invalidates React Query caches.
Full flow: connect Kite → run analysis → view/manage setups."
```

---

## Execution Order Summary

| Task | What It Builds | Key Files |
|------|---------------|-----------|
| 1: Types + API | Foundation types + 8 new API functions | types/index.ts, api.ts |
| 2: Kite Auth | Connect button + callback page | auth/ components, top-bar |
| 3: Run History | Analysis run panel + v2 trigger | analysis/page, run-history |
| 4: Setup Cards | Ranked setups + approve/reject | setup-card, ranked-setups |
| 5: Integration | Layout assembly + live updates | analysis/page, store, providers |
