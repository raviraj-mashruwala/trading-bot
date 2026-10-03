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

  it("marks scan.universe active when status is fetching", () => {
    getState().handleEvent(makeEvent("analysis.started"));
    getState().handleEvent(makeEvent("scan.universe", { total: 500, status: "fetching" }));
    expect(getState().steps["scan.universe"].status).toBe("active");
    expect(getState().steps["scan.universe"].data?.total).toBe(500);
  });

  it("marks scan.universe complete on second emit without status", () => {
    getState().handleEvent(makeEvent("analysis.started"));
    getState().handleEvent(makeEvent("scan.universe", { total: 500, status: "fetching" }));
    getState().handleEvent(makeEvent("scan.universe", { total: 480 }));
    expect(getState().steps["scan.universe"].status).toBe("complete");
    expect(getState().steps["scan.universe"].data?.total).toBe(480);
  });

  it("marks scan.filtered step complete after scan.universe", () => {
    getState().handleEvent(makeEvent("analysis.started"));
    getState().handleEvent(makeEvent("scan.universe", { total: 500 }));
    getState().handleEvent(makeEvent("scan.filtered", { passed: 120, failed: 380, pass_rate: 0.24 }));
    expect(getState().steps["scan.filtered"].status).toBe("complete");
  });

  it("does not advance next step when current is active (fetching)", () => {
    getState().handleEvent(makeEvent("analysis.started"));
    getState().handleEvent(makeEvent("scan.universe", { total: 500, status: "fetching" }));
    expect(getState().steps["scan.filtered"].status).toBe("pending");
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
    getState().handleEvent(makeEvent("scan.universe", { total: 100 }));
    getState().reset();
    expect(getState().status).toBe("idle");
    expect(Object.keys(getState().steps)).toHaveLength(0);
    expect(getState().error).toBeNull();
  });
});
