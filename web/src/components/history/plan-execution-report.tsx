"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

interface LegReport {
  symbol: string;
  direction: string;
  planned_entry: number;
  status: string;
  actual_entry: number | null;
  actual_exit: number | null;
  drift_pct: number | null;
  pnl: number | null;
  exit_reason: string;
  key_decisions: string[];
}

interface Report {
  trade_date: string;
  legs: LegReport[];
  summary: string;
  total_pnl: number;
  entered: number;
  vetoed: number;
  missed: number;
}

const STATUS_BADGE: Record<string, { bg: string; text: string; label: string }> = {
  entered: { bg: "bg-[#2da44e]/10", text: "text-[#2da44e]", label: "ENTERED" },
  vetoed: { bg: "bg-[#f85149]/10", text: "text-[#f85149]", label: "VETOED" },
  timeout: { bg: "bg-[#d4a015]/10", text: "text-[#d4a015]", label: "TIMEOUT" },
  missed: { bg: "bg-[rgba(255,255,255,0.05)]", text: "text-muted-foreground", label: "MISSED" },
};

export function PlanExecutionReport({ date }: { date: string }) {
  const { data } = useQuery({
    queryKey: ["plan-execution-report", date],
    queryFn: () => api.getPlanExecutionReport(date),
    enabled: !!date,
  });

  const report = data as Report | undefined;
  if (!report || !report.legs?.length) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          Plan vs Execution
        </h3>
        <span className="text-xs text-muted-foreground">{report.summary}</span>
      </div>
      <div className="grid gap-2">
        {report.legs.map((leg) => {
          const badge = STATUS_BADGE[leg.status] ?? STATUS_BADGE.missed;
          return (
            <div
              key={leg.symbol}
              className="flex items-start justify-between rounded-lg border border-border/30 bg-card/50 px-3 py-2"
            >
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{leg.symbol}</span>
                  <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
                    leg.direction === "long"
                      ? "bg-[#2da44e]/10 text-[#2da44e]"
                      : "bg-[#f85149]/10 text-[#f85149]"
                  }`}>
                    {leg.direction.toUpperCase()}
                  </span>
                  <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${badge.bg} ${badge.text}`}>
                    {badge.label}
                  </span>
                </div>
                {leg.status === "entered" && (
                  <p className="text-xs text-muted-foreground">
                    Plan: {leg.planned_entry.toFixed(2)} | Fill: {leg.actual_entry?.toFixed(2)} | Exit: {leg.actual_exit?.toFixed(2)}
                    {leg.drift_pct != null && ` | Drift: ${leg.drift_pct.toFixed(1)}%`}
                  </p>
                )}
                {leg.status !== "entered" && (
                  <p className="text-xs text-muted-foreground">
                    Plan: {leg.planned_entry.toFixed(2)} | {leg.exit_reason}
                  </p>
                )}
                {leg.key_decisions.length > 0 && (
                  <div className="text-[10px] text-muted-foreground/50 space-y-0.5">
                    {leg.key_decisions.slice(0, 3).map((d, i) => (
                      <p key={i}>{d}</p>
                    ))}
                  </div>
                )}
              </div>
              <div className="text-right shrink-0 ml-4">
                {leg.pnl != null && (
                  <p className={`text-sm font-mono font-medium ${
                    leg.pnl >= 0 ? "text-[#2da44e]" : "text-[#f85149]"
                  }`}>
                    {leg.pnl >= 0 ? "+" : ""}₹{leg.pnl.toFixed(0)}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
