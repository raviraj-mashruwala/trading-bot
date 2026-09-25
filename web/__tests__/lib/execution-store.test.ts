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
  it("starts idle with empty state", () => {
    expect(getState().status).toBe("idle");
    expect(getState().fills).toHaveLength(0);
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
    expect(getState().fills).toHaveLength(1);
    expect(getState().fills[0].symbol).toBe("RELIANCE");
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

  it("accumulates events even when no component subscribes", () => {
    getState().handleEvent(makeEvent("exec.started", { trade_date: "2026-09-26", mode: "paper", legs: [] }));
    getState().handleEvent(makeEvent("exec.entry_filled", { symbol: "INFY", fill_price: 1800, quantity: 5 }));
    expect(getState().status).toBe("running");
    expect(getState().fills).toHaveLength(1);
  });
});
