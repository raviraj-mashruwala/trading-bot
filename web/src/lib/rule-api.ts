// API client for the rule executor (/api/rules/kec). Kept apart from api.ts so the
// plan-executor client is untouched. Errors carry the backend's `detail` message.

export type RuleMode = "paper" | "live";

export interface RuleSignal {
  trade: boolean;
  reasons: string[];
  gap_pct: number;
  prev_close_pos: number;
  adr_pct: number;
  prev_close: number;
  today_open: number;
  note: string;
}

export interface RuleSession {
  phase: string;
  mode: RuleMode;
  trade_date: string;
  note: string;
  signal: RuleSignal | null;
  position: {
    quantity: number;
    entry_price: number;
    stop: number;
    last_price: number | null;
    unrealised_pnl: number | null;
    entered_at: string | null;
  } | null;
  result: { gross_pnl: number; est_charges: number; net_pnl: number } | null;
}

export interface RuleStatus {
  running: boolean;
  error: string | null;
  session: RuleSession | null;
  defaults: Record<string, string | number>;
}

export interface RulePreview {
  as_of: string;
  previous_session: string;
  previous_close: number;
  previous_close_pos: number;
  weak_close_met: boolean;
  gap_trigger_price: number;
  adr_pct: number;
  today_open: number | null;
  signal: RuleSignal | null;
}

export interface RuleTrade {
  id: number;
  trade_date: string;
  mode: RuleMode;
  symbol: string;
  quantity: number;
  entry_price: number;
  stop_price: number;
  exit_price: number | null;
  exit_reason: string | null;
  gross_pnl: number | null;
  est_charges: number | null;
  net_pnl: number | null;
  status: string;
}

export interface RuleEvent {
  id: number;
  trade_date: string;
  mode: RuleMode;
  timestamp: string;
  kind: string;
  message: string;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body && typeof body.detail === "string" ? body.detail : `${res.status} ${res.statusText}`;
    throw new Error(detail);
  }
  return body as T;
}

const BASE = "/api/rules/kec";

export const ruleApi = {
  status: () => request<RuleStatus>(`${BASE}/status`),
  preview: () => request<RulePreview>(`${BASE}/preview`),
  trades: () => request<RuleTrade[]>(`${BASE}/trades`),
  events: (date?: string) => request<RuleEvent[]>(`${BASE}/events${date ? `?date=${date}` : ""}`),
  start: (mode: RuleMode, notional: number, confirm?: string) =>
    request<{ status: string; mode: RuleMode; notional: number }>(`${BASE}/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, notional, ...(confirm ? { confirm } : {}) }),
    }),
  stop: () => request<{ status: string; position_left_open?: boolean }>(`${BASE}/stop`, { method: "POST" }),
};
