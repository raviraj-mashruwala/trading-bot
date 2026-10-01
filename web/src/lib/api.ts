import type {
  HealthStatus, ConfigResponse, Provider, PlanSummary, TradePlan,
  Trade, TradeStats, AnalysisStatus, ExecutionStatusResponse,
  KiteAuthStatus, AnalysisRun, Setup, DailyPlan, SyncStatus,
  TradeScorecard, PerformanceStatsData, GeneratePlanResponse,
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
    post<{ status: string; trade_date: string }>(
      "/api/analyze",
      tradeDate ? { trade_date: tradeDate } : undefined,
    ),
  cancelAnalysis: () => post<{ status: string }>("/api/analyze/cancel"),
  getExecutionStatus: () => get<ExecutionStatusResponse>("/api/execute/status"),
  postExecute: (mode?: string, date?: string) => {
    const body: Record<string, string> = {};
    if (mode) body.mode = mode;
    if (date) body.date = date;
    return Object.keys(body).length > 0
      ? post<{ status: string; mode: string; trade_date: string }>("/api/execute", body)
      : post<{ status: string; mode: string; trade_date: string }>("/api/execute");
  },
  stopExecution: () => post<{ status: string }>("/api/execute/stop"),

  // Kite Auth
  getKiteLoginUrl: () => get<{ login_url: string }>("/api/auth/kite/login"),
  getKiteStatus: () => get<KiteAuthStatus>("/api/auth/kite/status"),
  testKiteConnection: () =>
    get<{
      ok: boolean; error?: string; user_name?: string; user_id?: string;
      email?: string; broker?: string; available_cash?: number; available_margin?: number;
    }>("/api/auth/kite/test"),
  kiteCallback: (requestToken: string) =>
    get<{ authenticated: boolean; user_id: string }>(
      `/api/auth/kite/callback?request_token=${encodeURIComponent(requestToken)}`
    ),

  // V2 Pipeline
  getDailyPlan: () => get<DailyPlan>("/api/plans/today"),
  getAnalysisRuns: (tradeDate?: string) =>
    get<AnalysisRun[]>(`/api/plans/runs${tradeDate ? `?trade_date=${tradeDate}` : ""}`),
  getSetups: (symbol?: string, tradeDate?: string) => {
    const params = new URLSearchParams();
    if (symbol) params.set("symbol", symbol);
    if (tradeDate) params.set("trade_date", tradeDate);
    const qs = params.toString();
    return get<Setup[]>(`/api/plans/setups${qs ? `?${qs}` : ""}`);
  },
  patchSetup: (setupId: number, status: string, reason?: string) =>
    fetch(`/api/setups/${setupId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, reason }),
    }).then((r) => {
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      return r.json() as Promise<{ ok: boolean }>;
    }),

  // Data Sync
  postSync: () => post<{ status: string }>("/api/sync"),
  getSyncStatus: () => get<SyncStatus>("/api/sync/status"),

  // Plan Generation
  generatePlan: (date?: string) =>
    post<GeneratePlanResponse>(`/api/plans/generate${date ? `?trade_date=${date}` : ""}`),

  // Review & Performance
  getScorecards: (date: string) =>
    get<TradeScorecard[]>(`/api/review/scorecards?date=${date}`),
  getScorecard: (tradeId: number) =>
    get<TradeScorecard>(`/api/review/scorecards/${tradeId}`),
  getPerformanceStats: (days = 30) =>
    get<PerformanceStatsData>(`/api/review/stats?days=${days}`),
};
