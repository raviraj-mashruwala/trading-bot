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
