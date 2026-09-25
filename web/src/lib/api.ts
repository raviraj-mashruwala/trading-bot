import type {
  HealthStatus, ConfigResponse, Provider, PlanSummary, TradePlan,
  Trade, TradeStats, AnalysisStatus, ExecutionPosition,
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
};
