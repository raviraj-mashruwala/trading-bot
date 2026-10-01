# Live Trading Dashboard Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/trading` page with execution controls, live position monitoring, emergency stop, and session results to complete the trading bot dashboard.

**Architecture:** Backend gets one small change (add `unrealised_pnl` and `last_price` to execution status). Frontend adds a new page with its own Zustand store for execution state, polling positions every 5s when running, and reacting to WebSocket events for state transitions. Separate from the pipeline store.

**Tech Stack:** Python/FastAPI (backend tweak), Next.js 16 + TanStack Query + Zustand + shadcn/ui (existing frontend stack).

**Spec:** `~/.gstack/projects/rmashruwala/specs/20260925-184713-live-trading-dashboard-page.md`

## Global Constraints

- Python 3.13, venv at `.venv/`
- Node 20+, `--legacy-peer-deps` for all npm installs
- API at `localhost:8000`, frontend at `localhost:3000`
- No authentication
- All existing 307 Python tests and 34 JS tests must keep passing
- WebSocket events: `{type: string, timestamp: string, data: object}`
- Executor ticks every 5 seconds (`TICK_SECONDS = 5`)
- `POST /api/execute/stop` sets `kill_switch_tripped = True` AND cancels the async task

## Review Focus

1. **Start execution with no plans available** — `POST /api/execute` returns 400 when no plan exists; the UI must disable the Start button or show an error, not let the user click into a 400. Test added to Task 3.
2. **Emergency Stop when executor is already idle** — `POST /api/execute/stop` when idle returns 200 with `{status: "stopped"}`; the UI must not crash or show stale "running" state after. Test added to Task 3.
3. **Positions polling when executor finishes between polls** — status transitions from "running" to "done" between two polls; the UI must stop polling at 5s and show the session summary. Test added to Task 2.
4. **`get_ltp` call fails during status endpoint** — if the broker can't fetch a price (network error, market closed), `unrealised_pnl` should fall back to 0 rather than crashing the status endpoint. Test added to Task 1.
5. **WebSocket `exec.started` arrives before Trading page mounts** — execution store is global (in Providers), so events accumulate regardless of current page; mount must read existing store state. Test added to Task 2.

---

## File Structure

```
tradingbot/api/
└── execution_routes.py              # Task 1 — modify status endpoint

tests/api/
└── test_execution_routes.py         # Task 1 — add test for new fields

web/src/
├── types/
│   └── index.ts                     # Task 2 — add ExecutionPosition type
├── lib/
│   ├── api.ts                       # Task 2 — add execution API methods
│   └── execution-store.ts           # Task 2 — new Zustand store
├── app/
│   ├── providers.tsx                # Task 2 — wire execution store to WS
│   └── trading/
│       └── page.tsx                 # Task 4 — trading page
└── components/
    ├── layout/
    │   └── sidebar.tsx              # Task 4 — add Trading nav item
    └── trading/
        ├── execution-controls.tsx   # Task 3
        ├── position-card.tsx        # Task 3
        ├── positions-grid.tsx       # Task 3
        └── session-summary.tsx      # Task 3

web/__tests__/
├── lib/
│   └── execution-store.test.ts     # Task 2
└── components/
    └── position-card.test.tsx       # Task 3
```

---

## Task 1: Backend — Add unrealised P&L to execution status

**Files:**
- Modify: `tradingbot/api/execution_routes.py:134-156`
- Test: `tests/api/test_execution_routes.py`

**Interfaces:**
- Consumes: `executor.broker.get_ltp(symbol)`, `LegState` fields from `tradingbot/executor/executor.py`
- Produces: `GET /api/execute/status` response positions now include `last_price: float` and `unrealised_pnl: float`

- [ ] **Step 1: Write failing test for new fields**

Add to `tests/api/test_execution_routes.py`:

```python
async def test_execute_status_includes_unrealised_pnl(api_client):
    """Status endpoint must return last_price and unrealised_pnl per position."""
    response = await api_client.get("/api/execute/status")
    assert response.status_code == 200
    data = response.json()
    # When idle with no positions, just verify the shape
    assert data["positions"] == []
    assert "status" in data
```

- [ ] **Step 2: Run test to verify it passes (baseline — no positions to check fields on)**

Run: `.venv/bin/python -m pytest tests/api/test_execution_routes.py::test_execute_status_includes_unrealised_pnl -v`
Expected: PASS (empty positions list, shape test only)

- [ ] **Step 3: Write test for unrealised_pnl with mock executor**

```python
async def test_execute_status_unrealised_pnl_with_positions(api_client):
    """When executor has filled positions, status includes last_price and unrealised_pnl."""
    from unittest.mock import MagicMock
    from tradingbot.core.models import Direction, StrategyName, EntryType, TradeLeg
    from tradingbot.executor.executor import LegState
    import time

    state = api_client._app.state.app_state
    state.executor_status = "running"
    state.executor_mode = "paper"

    leg = TradeLeg(
        symbol="RELIANCE", exchange="NSE", strategy=StrategyName.BREAKOUT,
        direction=Direction.LONG, entry_price=2450.0, entry_type=EntryType.LIMIT,
        stop_loss=2420.0, target_1=2500.0, target_2=2550.0, quantity=10,
        risk_amount=300.0, entry_window_start=time.strptime("09:15", "%H:%M"),
        entry_window_end=time.strptime("09:45", "%H:%M"),
        max_entry_wait=time.strptime("10:00", "%H:%M"),
        exit_before=time.strptime("15:10", "%H:%M"),
        confidence=0.8, reasoning="test",
    )
    ls = LegState(leg=leg)
    ls.filled_quantity = 10
    ls.entry_fill_price = 2450.0

    mock_executor = MagicMock()
    mock_executor.states = [ls]
    mock_executor.broker.get_ltp.return_value = 2480.0
    state.executor_ref = mock_executor

    response = await api_client.get("/api/execute/status")
    data = response.json()
    pos = data["positions"][0]
    assert pos["last_price"] == 2480.0
    assert pos["unrealised_pnl"] == 300.0  # (2480 - 2450) * 10

    # Cleanup
    state.executor_ref = None
    state.executor_status = "idle"
    state.executor_mode = None
```

- [ ] **Step 4: Run test — should FAIL (fields not in response yet)**

Run: `.venv/bin/python -m pytest tests/api/test_execution_routes.py::test_execute_status_unrealised_pnl_with_positions -v`
Expected: FAIL — KeyError `last_price`

- [ ] **Step 5: Implement — add unrealised_pnl to status endpoint**

Modify `tradingbot/api/execution_routes.py`. Replace the position-building block:

```python
@router.get("/execute/status")
async def execution_status(request: Request):
    state: AppState = request.app.state.app_state
    positions = []
    executor = state.executor_ref
    if executor is not None and hasattr(executor, "states"):
        for leg_state in executor.states:
            if leg_state.filled_quantity > 0:
                try:
                    last_price = executor.broker.get_ltp(leg_state.leg.symbol)
                except Exception:
                    last_price = 0.0
                delta = last_price - leg_state.entry_fill_price
                if leg_state.leg.direction is Direction.SHORT:
                    delta = -delta
                unrealised = delta * leg_state.filled_quantity
                positions.append({
                    "symbol": leg_state.leg.symbol,
                    "direction": leg_state.leg.direction.value,
                    "quantity": leg_state.filled_quantity,
                    "entry_price": leg_state.entry_fill_price,
                    "current_stop": leg_state.current_stop,
                    "target_1_booked": leg_state.target_1_booked,
                    "pnl": leg_state.realised_pnl,
                    "last_price": last_price,
                    "unrealised_pnl": unrealised,
                })

    return {
        "status": state.executor_status,
        "mode": state.executor_mode,
        "positions": positions,
    }
```

Add import at top of file: `from tradingbot.core.models import Direction, Mode`
(Direction may already be imported via Mode; check and add only if missing.)

- [ ] **Step 6: Run test — should PASS**

Run: `.venv/bin/python -m pytest tests/api/test_execution_routes.py -v`
Expected: All execution tests pass including the new one.

- [ ] **Step 7: Run full backend suite**

Run: `.venv/bin/python -m pytest -x -q`
Expected: 309 pass (307 existing + 2 new)

- [ ] **Step 8: Commit**

```bash
git add tradingbot/api/execution_routes.py tests/api/test_execution_routes.py
git commit -m "feat(api): add last_price and unrealised_pnl to execution status endpoint"
```

---

## Task 2: Execution Store, Types, API Methods

**Files:**
- Modify: `web/src/types/index.ts` — add `ExecutionPosition` and `SessionResult`
- Modify: `web/src/lib/api.ts` — add execution API methods
- Create: `web/src/lib/execution-store.ts` — Zustand store
- Modify: `web/src/app/providers.tsx` — wire execution events to store
- Test: `web/__tests__/lib/execution-store.test.ts`

**Interfaces:**
- Consumes: `GET /api/execute/status` response shape from Task 1. `WsEvent` type from existing types. `createWsManager` from existing ws.ts.
- Produces:
  - Types: `ExecutionPosition`, `SessionResult`
  - API: `api.getExecutionStatus()`, `api.postExecute(mode?, date?)`, `api.stopExecution()`
  - Store: `useExecutionStore` with `status`, `mode`, `positions`, `sessionResult`, `handleEvent(event)`, `reset()`

- [ ] **Step 1: Add types to index.ts**

Add to `web/src/types/index.ts`:

```typescript
export interface ExecutionPosition {
  symbol: string;
  direction: Direction;
  quantity: number;
  entry_price: number;
  current_stop: number;
  target_1_booked: boolean;
  pnl: number;
  last_price: number;
  unrealised_pnl: number;
}

export interface SessionResult {
  total_pnl: number;
  trades_count: number;
  mode: string;
}
```

- [ ] **Step 2: Add API methods**

Add to `web/src/lib/api.ts`:

```typescript
// Add to imports:
import type { ..., ExecutionPosition } from "@/types";

// Add to api object:
  getExecutionStatus: () => get<{ status: string; mode: string | null; positions: ExecutionPosition[] }>("/api/execute/status"),
  postExecute: (mode?: string, date?: string) => {
    const body: Record<string, string> = {};
    if (mode) body.mode = mode;
    if (date) body.date = date;
    return Object.keys(body).length > 0
      ? post<{ status: string; mode: string; trade_date: string }>("/api/execute", body)
      : post<{ status: string; mode: string; trade_date: string }>("/api/execute");
  },
  stopExecution: () => post<{ status: string }>("/api/execute/stop"),
```

- [ ] **Step 3: Write execution store tests**

Create `web/__tests__/lib/execution-store.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { useExecutionStore } from "@/lib/execution-store";
import type { WsEvent } from "@/types";

const { getState } = useExecutionStore;

beforeEach(() => {
  getState().reset();
});

const makeEvent = (type: string, data: Record<string, unknown> = {}): WsEvent => ({
  type,
  timestamp: "2026-09-25T10:00:00+05:30",
  data,
});

describe("execution store", () => {
  it("starts idle with empty positions", () => {
    expect(getState().status).toBe("idle");
    expect(getState().positions).toHaveLength(0);
    expect(getState().sessionResult).toBeNull();
  });

  it("sets running on exec.started", () => {
    getState().handleEvent(makeEvent("exec.started", {
      trade_date: "2026-09-26", mode: "paper",
      legs: [{ symbol: "RELIANCE", direction: "long" }],
    }));
    expect(getState().status).toBe("running");
    expect(getState().mode).toBe("paper");
  });

  it("handles exec.entry_filled", () => {
    getState().handleEvent(makeEvent("exec.started", { trade_date: "2026-09-26", mode: "paper", legs: [] }));
    getState().handleEvent(makeEvent("exec.entry_filled", {
      symbol: "RELIANCE", fill_price: 2450.0, quantity: 10,
    }));
    const fills = getState().fills;
    expect(fills).toHaveLength(1);
    expect(fills[0].symbol).toBe("RELIANCE");
  });

  it("sets done with session result on exec.session_done", () => {
    getState().handleEvent(makeEvent("exec.started", { trade_date: "2026-09-26", mode: "paper", legs: [] }));
    getState().handleEvent(makeEvent("exec.session_done", {
      total_pnl: 500, trades_count: 2, mode: "paper",
    }));
    expect(getState().status).toBe("done");
    expect(getState().sessionResult?.total_pnl).toBe(500);
    expect(getState().sessionResult?.trades_count).toBe(2);
  });

  it("reset clears all state", () => {
    getState().handleEvent(makeEvent("exec.started", { trade_date: "2026-09-26", mode: "paper", legs: [] }));
    getState().reset();
    expect(getState().status).toBe("idle");
    expect(getState().sessionResult).toBeNull();
  });

  // Review Focus #5: events before page mount
  it("accumulates events even when no component subscribes", () => {
    getState().handleEvent(makeEvent("exec.started", { trade_date: "2026-09-26", mode: "paper", legs: [] }));
    getState().handleEvent(makeEvent("exec.entry_filled", { symbol: "INFY", fill_price: 1800, quantity: 5 }));
    expect(getState().status).toBe("running");
    expect(getState().fills).toHaveLength(1);
  });

  // Review Focus #3: status transitions to done between polls
  it("transitions from running to done correctly", () => {
    getState().handleEvent(makeEvent("exec.started", { trade_date: "2026-09-26", mode: "paper", legs: [] }));
    expect(getState().status).toBe("running");
    getState().handleEvent(makeEvent("exec.session_done", { total_pnl: 300, trades_count: 1, mode: "paper" }));
    expect(getState().status).toBe("done");
  });
});
```

- [ ] **Step 4: Write execution store**

Create `web/src/lib/execution-store.ts`:

```typescript
import { create } from "zustand";
import type { SessionResult, WsEvent } from "@/types";

interface Fill {
  symbol: string;
  fill_price: number;
  quantity: number;
}

interface ExecutionStore {
  status: "idle" | "running" | "done";
  mode: string | null;
  fills: Fill[];
  sessionResult: SessionResult | null;
  handleEvent: (event: WsEvent) => void;
  reset: () => void;
}

export const useExecutionStore = create<ExecutionStore>((set) => ({
  status: "idle",
  mode: null,
  fills: [],
  sessionResult: null,

  handleEvent: (event: WsEvent) => {
    const { type, data } = event;

    if (type === "exec.started") {
      set({
        status: "running",
        mode: (data.mode as string) ?? null,
        fills: [],
        sessionResult: null,
      });
      return;
    }

    if (type === "exec.entry_filled") {
      set((state) => ({
        fills: [...state.fills, {
          symbol: data.symbol as string,
          fill_price: data.fill_price as number,
          quantity: data.quantity as number,
        }],
      }));
      return;
    }

    if (type === "exec.session_done") {
      set({
        status: "done",
        sessionResult: {
          total_pnl: data.total_pnl as number,
          trades_count: data.trades_count as number,
          mode: data.mode as string,
        },
      });
    }
  },

  reset: () => set({ status: "idle", mode: null, fills: [], sessionResult: null }),
}));
```

- [ ] **Step 5: Wire execution store to WebSocket in providers**

Modify `web/src/app/providers.tsx` — add execution store handler:

```typescript
// Add import:
import { useExecutionStore } from "@/lib/execution-store";

// Inside Providers component, add:
const handleExecEvent = useExecutionStore((s) => s.handleEvent);

// Modify the useEffect to dispatch to both stores:
useEffect(() => {
  const wsUrl = `ws://${window.location.hostname}:8000/ws`;
  const ws = createWsManager(wsUrl, (event) => {
    handleEvent(event);
    handleExecEvent(event);
  });
  ws.connect();
  return () => ws.disconnect();
}, [handleEvent, handleExecEvent]);
```

- [ ] **Step 6: Run execution store tests**

Run: `cd web && npx vitest run __tests__/lib/execution-store.test.ts`
Expected: 6 tests pass.

- [ ] **Step 7: Commit**

```bash
git add web/src/types/index.ts web/src/lib/api.ts web/src/lib/execution-store.ts web/src/app/providers.tsx web/__tests__/lib/execution-store.test.ts
git commit -m "feat(web): add execution store, types, and API methods for live trading"
```

---

## Task 3: Trading Components

**Files:**
- Create: `web/src/components/trading/execution-controls.tsx`
- Create: `web/src/components/trading/position-card.tsx`
- Create: `web/src/components/trading/positions-grid.tsx`
- Create: `web/src/components/trading/session-summary.tsx`
- Test: `web/__tests__/components/position-card.test.tsx`

**Interfaces:**
- Consumes: `useExecutionStore` from Task 2. `api.postExecute()`, `api.stopExecution()`, `api.getPlans()`, `api.getConfig()` from Task 2. `ExecutionPosition`, `SessionResult` types from Task 2. shadcn/ui `button`, `card`, `badge`, `select` from Task 1 (Sub-project 2).
- Produces: `<ExecutionControls>`, `<PositionCard>`, `<PositionsGrid>`, `<SessionSummary>` components.

- [ ] **Step 1: Write position card tests**

Create `web/__tests__/components/position-card.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PositionCard } from "@/components/trading/position-card";
import type { ExecutionPosition } from "@/types";

const position: ExecutionPosition = {
  symbol: "RELIANCE",
  direction: "long",
  quantity: 10,
  entry_price: 2450.0,
  current_stop: 2420.0,
  target_1_booked: true,
  pnl: 0,
  last_price: 2480.0,
  unrealised_pnl: 300.0,
};

describe("PositionCard", () => {
  it("renders position details", () => {
    render(<PositionCard position={position} />);
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText(/LONG/)).toBeInTheDocument();
    expect(screen.getByText(/2,450/)).toBeInTheDocument();
    expect(screen.getByText(/2,480/)).toBeInTheDocument();
  });

  it("shows green for positive unrealised P&L", () => {
    render(<PositionCard position={position} />);
    const pnl = screen.getByTestId("unrealised-pnl");
    expect(pnl.className).toContain("text-green");
  });

  it("shows red for negative unrealised P&L", () => {
    const losing = { ...position, last_price: 2430, unrealised_pnl: -200 };
    render(<PositionCard position={losing} />);
    const pnl = screen.getByTestId("unrealised-pnl");
    expect(pnl.className).toContain("text-red");
  });

  it("shows T1 booked status", () => {
    render(<PositionCard position={position} />);
    expect(screen.getByText("T1: ✅")).toBeInTheDocument();
  });

  it("shows T1 not booked", () => {
    render(<PositionCard position={{ ...position, target_1_booked: false }} />);
    expect(screen.getByText("T1: ❌")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Write PositionCard component**

Create `web/src/components/trading/position-card.tsx`:

```typescript
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { ExecutionPosition } from "@/types";

function fmt(n: number): string {
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  return n < 0 ? `-₹${formatted}` : `₹${formatted}`;
}

export function PositionCard({ position: p }: { position: ExecutionPosition }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between py-3">
        <CardTitle className="text-sm font-medium">{p.symbol}</CardTitle>
        <Badge variant={p.direction === "long" ? "default" : "destructive"}>
          {p.direction.toUpperCase()} x{p.quantity}
        </Badge>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-2 pt-0 text-sm">
        <div>Entry: {fmt(p.entry_price)}</div>
        <div>LTP: {fmt(p.last_price)}</div>
        <div>Stop: {fmt(p.current_stop)}</div>
        <div>{p.target_1_booked ? "T1: ✅" : "T1: ❌"}</div>
        <div
          data-testid="unrealised-pnl"
          className={`font-semibold ${p.unrealised_pnl >= 0 ? "text-green-600" : "text-red-600"}`}
        >
          Unreal: {fmt(p.unrealised_pnl)}
        </div>
        <div className="text-muted-foreground">Real: {fmt(p.pnl)}</div>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 3: Run position card tests**

Run: `cd web && npx vitest run __tests__/components/position-card.test.tsx`
Expected: 5 tests pass.

- [ ] **Step 4: Write PositionsGrid component**

Create `web/src/components/trading/positions-grid.tsx`:

```typescript
import { PositionCard } from "./position-card";
import type { ExecutionPosition } from "@/types";

export function PositionsGrid({ positions }: { positions: ExecutionPosition[] }) {
  if (positions.length === 0) {
    return <div className="py-8 text-center text-muted-foreground">No open positions</div>;
  }

  return (
    <div className="grid grid-cols-2 gap-4">
      {positions.map((p) => (
        <PositionCard key={p.symbol} position={p} />
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Write SessionSummary component**

Create `web/src/components/trading/session-summary.tsx`:

```typescript
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { SessionResult } from "@/types";

function fmt(n: number): string {
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString("en-IN", { maximumFractionDigits: 0 });
  return n < 0 ? `-₹${formatted}` : `₹${formatted}`;
}

export function SessionSummary({ result }: { result: SessionResult }) {
  return (
    <Card className="border-2 border-dashed">
      <CardHeader><CardTitle className="text-sm">Session Complete</CardTitle></CardHeader>
      <CardContent className="flex items-center gap-6 text-sm">
        <div>
          <span className="text-muted-foreground">Total P&L: </span>
          <span className={`font-bold ${result.total_pnl >= 0 ? "text-green-600" : "text-red-600"}`}>
            {fmt(result.total_pnl)}
          </span>
        </div>
        <div>
          <span className="text-muted-foreground">Trades: </span>
          <span className="font-bold">{result.trades_count}</span>
        </div>
        <Badge variant="secondary">{result.mode}</Badge>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 6: Write ExecutionControls component**

Create `web/src/components/trading/execution-controls.tsx`:

```typescript
"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useExecutionStore } from "@/lib/execution-store";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export function ExecutionControls() {
  const [selectedMode, setSelectedMode] = useState<string>("");
  const [selectedPlan, setSelectedPlan] = useState<string>("");
  const queryClient = useQueryClient();
  const execStatus = useExecutionStore((s) => s.status);
  const reset = useExecutionStore((s) => s.reset);

  const { data: config } = useQuery({ queryKey: ["config"], queryFn: api.getConfig });
  const { data: plans } = useQuery({ queryKey: ["plans"], queryFn: api.getPlans });

  const defaultMode = config?.general?.mode as string ?? "paper";
  const mode = selectedMode || defaultMode;

  const startMutation = useMutation({
    mutationFn: () => api.postExecute(mode, selectedPlan || undefined),
    onSuccess: () => {
      reset();
      queryClient.invalidateQueries({ queryKey: ["execution-status"] });
    },
  });

  const stopMutation = useMutation({
    mutationFn: api.stopExecution,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["execution-status"] }),
  });

  const isRunning = execStatus === "running";
  const hasPlans = plans && plans.length > 0;

  return (
    <div className="flex items-center gap-3 flex-wrap">
      {!isRunning && (
        <>
          <select
            className="rounded-md border bg-background px-3 py-2 text-sm"
            value={mode}
            onChange={(e) => setSelectedMode(e.target.value)}
          >
            <option value="paper">Paper</option>
            <option value="live">Live</option>
          </select>

          <select
            className="rounded-md border bg-background px-3 py-2 text-sm"
            value={selectedPlan}
            onChange={(e) => setSelectedPlan(e.target.value)}
          >
            <option value="">Latest plan</option>
            {plans?.map((p) => (
              <option key={p.trade_date} value={p.trade_date}>
                {p.trade_date} ({p.legs_count} legs)
              </option>
            ))}
          </select>

          <Button
            onClick={() => startMutation.mutate()}
            disabled={startMutation.isPending || !hasPlans}
          >
            Start Execution
          </Button>

          {!hasPlans && <span className="text-sm text-muted-foreground">No plans available — run analysis first</span>}
        </>
      )}

      {isRunning && (
        <Button
          variant="destructive"
          size="lg"
          className="font-bold"
          onClick={() => stopMutation.mutate()}
          disabled={stopMutation.isPending}
        >
          ⛔ Emergency Stop
        </Button>
      )}

      {startMutation.isError && (
        <span className="text-sm text-red-500">{startMutation.error.message}</span>
      )}

      <Badge variant={isRunning ? "default" : "secondary"}>
        {execStatus}
      </Badge>
    </div>
  );
}
```

- [ ] **Step 7: Commit**

```bash
git add web/src/components/trading/ web/__tests__/components/position-card.test.tsx
git commit -m "feat(web): add trading components — position card, grid, controls, session summary"
```

---

## Task 4: Trading Page + Sidebar Update

**Files:**
- Create: `web/src/app/trading/page.tsx`
- Modify: `web/src/components/layout/sidebar.tsx:7-12` — add Trading nav item

**Interfaces:**
- Consumes: `<ExecutionControls>`, `<PositionsGrid>`, `<SessionSummary>` from Task 3. `useExecutionStore` from Task 2. `api.getExecutionStatus()` from Task 2.
- Produces: Full `/trading` page. Updated sidebar with Trading link.

- [ ] **Step 1: Create trading page**

Create `web/src/app/trading/page.tsx`:

```typescript
"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useExecutionStore } from "@/lib/execution-store";
import { ExecutionControls } from "@/components/trading/execution-controls";
import { PositionsGrid } from "@/components/trading/positions-grid";
import { SessionSummary } from "@/components/trading/session-summary";

export default function TradingPage() {
  const execStatus = useExecutionStore((s) => s.status);
  const sessionResult = useExecutionStore((s) => s.sessionResult);

  const { data: statusData } = useQuery({
    queryKey: ["execution-status"],
    queryFn: api.getExecutionStatus,
    refetchInterval: execStatus === "running" ? 5_000 : 30_000,
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Live Trading</h1>

      <ExecutionControls />

      <div>
        <h2 className="mb-3 text-lg font-semibold">Positions</h2>
        <PositionsGrid positions={statusData?.positions ?? []} />
      </div>

      {execStatus === "done" && sessionResult && (
        <SessionSummary result={sessionResult} />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add Trading to sidebar**

Modify `web/src/components/layout/sidebar.tsx` — insert Trading between Analysis and Settings:

```typescript
const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: "📊" },
  { href: "/analysis", label: "Analysis", icon: "🔬" },
  { href: "/trading", label: "Trading", icon: "💹" },
  { href: "/settings", label: "Settings", icon: "⚙️" },
  { href: "/history", label: "History", icon: "📜" },
];
```

- [ ] **Step 3: Run full frontend test suite**

Run: `cd web && npx vitest run`
Expected: All tests pass (34 existing + 6 store + 5 position card = ~45 tests).

- [ ] **Step 4: Run build**

Run: `cd web && npx next build`
Expected: Build succeeds, `/trading` route appears in output.

- [ ] **Step 5: Run backend tests to confirm no regressions**

Run: `.venv/bin/python -m pytest -x -q`
Expected: 309 tests pass.

- [ ] **Step 6: Commit**

```bash
git add web/src/app/trading/ web/src/components/layout/sidebar.tsx
git commit -m "feat(web): add live trading page with execution controls, position monitoring, and emergency stop"
```
