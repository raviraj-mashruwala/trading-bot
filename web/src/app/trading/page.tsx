"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useExecutionStore } from "@/lib/execution-store";
import { ExecutionControls } from "@/components/trading/execution-controls";
import { PositionsGrid } from "@/components/trading/positions-grid";
import { SessionSummary } from "@/components/trading/session-summary";
import { TickerHealthIndicator } from "@/components/trading/ticker-health-indicator";
import { DecisionTimeline } from "@/components/trading/decision-timeline";

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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Live Trading</h1>
        <TickerHealthIndicator health={statusData?.ticker_health} />
      </div>

      <ExecutionControls />

      <div>
        <h2 className="mb-3 text-lg font-semibold">Positions</h2>
        <PositionsGrid positions={statusData?.positions ?? []} />
      </div>

      <DecisionTimeline decisions={decisions} />

      {execStatus === "done" && sessionResult && (
        <SessionSummary result={sessionResult} />
      )}
    </div>
  );
}
