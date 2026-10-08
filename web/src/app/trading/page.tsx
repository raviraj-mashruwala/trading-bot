"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useExecutionStore } from "@/lib/execution-store";
import { ExecutionControls } from "@/components/trading/execution-controls";
import { PositionsGrid } from "@/components/trading/positions-grid";
import { SessionSummary } from "@/components/trading/session-summary";
import { TickerHealthIndicator } from "@/components/trading/ticker-health-indicator";
import { DecisionTimeline } from "@/components/trading/decision-timeline";
import { SquareOffCountdown } from "@/components/trading/square-off-countdown";

export default function TradingPage() {
  const execStatus = useExecutionStore((s) => s.status);
  const sessionResult = useExecutionStore((s) => s.sessionResult);
  const recentDecisions = useExecutionStore((s) => s.recentDecisions);

  const { data: statusData } = useQuery({
    queryKey: ["execution-status"],
    queryFn: api.getExecutionStatus,
    refetchInterval: execStatus === "running" ? 5_000 : 30_000,
  });

  const decisions = execStatus === "running" && recentDecisions.length > 0
    ? recentDecisions
    : statusData?.decision_log ?? [];

  const positions = statusData?.positions ?? [];
  const totalUnrealisedPnl = positions.reduce((sum, p) => sum + (p.unrealised_pnl ?? 0), 0);
  const hasPositions = positions.length > 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-semibold">Live Trading</h1>
          {hasPositions && (
            <span className={`text-lg font-mono font-semibold ${totalUnrealisedPnl >= 0 ? "text-[#2da44e]" : "text-[#f85149]"}`}>
              {totalUnrealisedPnl >= 0 ? "+" : ""}₹{totalUnrealisedPnl.toFixed(0)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-4">
          <SquareOffCountdown />
          <TickerHealthIndicator health={statusData?.ticker_health} />
        </div>
      </div>

      <ExecutionControls />

      <div>
        <h2 className="mb-3 text-lg font-semibold">Positions</h2>
        <PositionsGrid positions={positions} />
      </div>

      <DecisionTimeline decisions={decisions} />

      {execStatus === "done" && sessionResult && (
        <SessionSummary result={sessionResult} />
      )}
    </div>
  );
}
