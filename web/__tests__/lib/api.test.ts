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
