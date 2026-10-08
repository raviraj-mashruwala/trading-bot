"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import type { PlanSummary } from "@/types";

export function LastAnalysis() {
  const { data: status } = useQuery({ queryKey: ["analysis-status"], queryFn: api.getAnalysisStatus });
  const { data: plans } = useQuery({ queryKey: ["plans"], queryFn: api.getPlans });

  const latest: PlanSummary | undefined = plans
    ?.slice()
    .sort((a, b) => b.generated_at.localeCompare(a.generated_at))
    .at(0);

  return (
    <Card className="border-border/50 bg-card/80">
      <CardContent className="p-4">
        <div className="mb-3 text-[11px] font-medium text-muted-foreground">Last Analysis</div>
        <div className="flex items-center gap-2">
          <span className={`inline-flex h-1.5 w-1.5 rounded-full ${status?.status === "running" ? "bg-[#d4a015] animate-pulse" : status?.status === "complete" ? "bg-[#2da44e]" : "bg-muted-foreground/40"}`} />
          <span className="text-sm text-foreground/80">{status?.status ?? "unknown"}</span>
        </div>
        {latest ? (
          <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
            <div>
              <div className="text-[10px] text-muted-foreground/60">Date</div>
              <div className="font-mono-nums text-foreground/80">{latest.trade_date}</div>
            </div>
            <div>
              <div className="text-[10px] text-muted-foreground/60">Legs</div>
              <div className="font-mono-nums text-foreground/80">{latest.legs_count}</div>
            </div>
            <div>
              <div className="text-[10px] text-muted-foreground/60">Regime</div>
              <div className="text-foreground/80">{latest.market_regime}</div>
            </div>
          </div>
        ) : (
          <div className="mt-3 text-sm text-muted-foreground/50">No plans generated yet</div>
        )}
      </CardContent>
    </Card>
  );
}
