"use client";

import { useEffect } from "react";
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

  const reset = useExecutionStore((s) => s.reset);

  const { data: statusData } = useQuery({
    queryKey: ["execution-status"],
    queryFn: api.getExecutionStatus,
    refetchInterval: 5_000,
  });

  const isRunning = execStatus === "running" || statusData?.status === "running";

  useEffect(() => {
    if (statusData && execStatus === "running" && statusData.status !== "running") {
      reset();
    }
  }, [statusData, execStatus, reset]);

  const decisions = isRunning && recentDecisions.length > 0
    ? recentDecisions
    : statusData?.decision_log ?? [];

  const positions = statusData?.positions ?? [];
  const totalUnrealisedPnl = positions.reduce((sum, p) => sum + (p.unrealised_pnl ?? 0), 0);
  const hasPositions = positions.length > 0;

  return (
    <div className="space-y-5">
      {/* Hero bar — status + P&L + countdown */}
      <div className="flex items-end justify-between">
        <div>
          {hasPositions ? (
            <>
              <p className="text-xs text-muted-foreground mb-1">Unrealised P&L</p>
              <p className={`hero-number text-4xl ${totalUnrealisedPnl >= 0 ? "text-[#2da44e]" : "text-[#f85149]"}`}>
                {totalUnrealisedPnl >= 0 ? "+" : "-"}₹{Math.abs(totalUnrealisedPnl).toFixed(0)}
              </p>
            </>
          ) : (
            <>
              <p className="text-xs text-muted-foreground mb-1">
                {isRunning ? "Waiting for entry" : "Ready to trade"}
              </p>
              <p className="hero-number text-4xl text-[#e6edf3]">
                {positions.length} positions
              </p>
            </>
          )}
        </div>
        <div className="flex items-center gap-5">
          <SquareOffCountdown />
          <TickerHealthIndicator health={statusData?.ticker_health} />
          <div className="flex items-center gap-1.5">
            <span className={`h-1.5 w-1.5 rounded-full ${isRunning ? "bg-[#2da44e] animate-pulse" : "bg-muted-foreground/30"}`} />
            <span className="text-xs text-muted-foreground">{execStatus}</span>
          </div>
        </div>
      </div>

      <ExecutionControls />

      {/* Positions — inline, no card wrapper */}
      {hasPositions && (
        <div className="space-y-2">
          <PositionsGrid positions={positions} />
        </div>
      )}

      {!hasPositions && isRunning && (
        <p className="text-sm text-muted-foreground py-8 text-center">Evaluating entry conditions...</p>
      )}

      <DecisionTimeline decisions={decisions} />

      {execStatus === "done" && sessionResult && (
        <SessionSummary result={sessionResult} />
      )}
    </div>
  );
}
