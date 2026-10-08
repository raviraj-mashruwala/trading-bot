export type Direction = "long" | "short";
export type EntryType = "limit" | "stop";
export type StrategyName = "breakout" | "momentum" | "mean_reversion" | "vwap_bounce" | "orb" | "gap_and_go" | "pivot_point" | "relative_strength" | "bollinger_squeeze" | "supply_demand";
export type MarketRegime = "trending_up" | "trending_down" | "range_bound" | "volatile" | "low_vol_squeeze";
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
  history?: Array<{ symbol: string; data: Record<string, unknown>; timestamp: string }>;
}

export type PipelineStatus = "idle" | "running" | "complete" | "failed";

export interface MomentumData {
  "1m": number;
  "5m": number;
  volume_ratio: number;
  vwap_position: number;
  trend_alignment: boolean;
}

export interface TickerHealth {
  status: "healthy" | "reconnecting" | "degraded" | "unknown";
  last_tick_at: string | null;
  reconnect_count: number;
  gap_seconds_today: number;
}

export interface ExecutionDecision {
  id: number;
  trade_date: string;
  timestamp: string;
  symbol: string;
  decision_type: string;
  reason: string | null;
  momentum_snapshot: string | null;
  candle_snapshot: string | null;
  escalated: number;
  llm_response: string | null;
  outcome: string | null;
}

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
  momentum?: MomentumData;
  phase?: string;
  last_decision?: { reason: string };
  original_stop?: number;
}

export interface ExecutionStatusResponse {
  status: string;
  mode: string | null;
  positions: ExecutionPosition[];
  ticker_health: TickerHealth;
  decision_log: ExecutionDecision[];
}

export interface SessionResult {
  total_pnl: number;
  trades_count: number;
  mode: string;
}

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
  backtest_status?: "validated" | "failed" | "unvalidated";
  backtest_win_rate?: number;
  backtest_profit_factor?: number;
  backtest_expectancy_r?: number;
  backtest_total_trades?: number;
  jev_quality_score?: number;
  jev_overfit_risk?: number;
  jev_credibility?: number;
  jev_pass?: boolean;
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

export interface SyncStatus {
  status: "idle" | "running" | "complete" | "failed";
  progress: string;
}

export interface TradeScorecard {
  trade_id: number;
  setup_id: number | null;
  symbol: string;
  strategy: string;
  direction: string;
  trade_date: string;
  predicted_entry: number;
  predicted_stop: number;
  predicted_target_1: number;
  predicted_target_2: number | null;
  confidence: number;
  confluence_count: number;
  regime_at_generation: string;
  thesis: string;
  invalidation_condition: string;
  bear_case: string;
  actual_entry: number;
  actual_exit: number;
  pnl: number;
  exit_reason: string;
  quantity: number;
  r_multiple: number;
  hit_target: boolean;
  invalidation_fired: boolean;
  entry_slippage: number;
  predicted_rr: number;
  actual_rr: number;
}

export interface StrategyStatsData {
  trades: number;
  win_rate: number;
  avg_r: number;
  total_pnl: number;
}

export interface PerformanceStatsData {
  period_days: number;
  total_trades: number;
  win_rate: number;
  avg_r_multiple: number;
  total_pnl: number;
  by_strategy: Record<string, StrategyStatsData>;
  by_regime: Record<string, StrategyStatsData>;
  by_strategy_regime: Record<string, StrategyStatsData>;
  confluence_buckets: Record<string, number>;
  confidence_calibration: Record<string, number>;
}

export interface GeneratePlanResponse {
  status: string;
  trade_date: string;
  legs: number;
}

export interface MarketHoliday {
  date: string;
  name: string;
}

export interface MarketCalendarResponse {
  status: "open" | "pre_market" | "post_market" | "closed" | "holiday";
  reason: string;
  holiday_name: string | null;
  next_session: string;
  today_is_trading_day: boolean;
  holidays: MarketHoliday[];
  total_holidays_this_year: number;
  coverage: { first: string; last: string };
  current_year_covered: boolean;
  data_year: number;
}

export interface NightlyReview {
  id: number;
  trade_date: string;
  reviewed_at: string;
  total_pnl: number;
  trades_count: number;
  wins: number;
  losses: number;
  summary: string;
  lessons: string;
  improvements: string;
  grade: string;
  llm_cost_usd: number;
  skipped?: boolean;
  reason?: string;
}
