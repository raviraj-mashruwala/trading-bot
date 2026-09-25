"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useExecutionStore } from "@/lib/execution-store";
import { ExecutionControls } from "@/components/trading/execution-controls";
import { PositionsGrid } from "@/components/trading/positions-grid";
import { SessionSummary } from "@/components/trading/session-summary";

export default function TradingPage() {
  const execStatus = useExecutionStore((s) => s.status);
  const sessionResult = useExecutionStore((s) => s.sessionResult);

  const { data: statusData } = useQuery({
    queryKey: ["execution-status"],
    queryFn: api.getExecutionStatus,
    refetchInterval: execStatus === "running" ? 5_000 : 30_000,
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Live Trading</h1>

      <ExecutionControls />

      <div>
        <h2 className="mb-3 text-lg font-semibold">Positions</h2>
        <PositionsGrid positions={statusData?.positions ?? []} />
      </div>

      {execStatus === "done" && sessionResult && (
        <SessionSummary result={sessionResult} />
      )}
    </div>
  );
}
