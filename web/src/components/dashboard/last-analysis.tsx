"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { PlanSummary } from "@/types";

export function LastAnalysis() {
  const { data: status } = useQuery({ queryKey: ["analysis-status"], queryFn: api.getAnalysisStatus });
  const { data: plans } = useQuery({ queryKey: ["plans"], queryFn: api.getPlans });

  const latest: PlanSummary | undefined = plans?.at(-1);

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">Last Analysis</CardTitle></CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">Status:</span>
          <Badge variant={status?.status === "running" ? "default" : "secondary"}>{status?.status ?? "unknown"}</Badge>
        </div>
        {latest ? (
          <>
            <div><span className="text-muted-foreground">Date:</span> {latest.trade_date}</div>
            <div><span className="text-muted-foreground">Legs:</span> {latest.legs_count}</div>
            <div><span className="text-muted-foreground">Regime:</span> {latest.market_regime}</div>
          </>
        ) : (
          <div className="text-muted-foreground">No plans generated yet</div>
        )}
      </CardContent>
    </Card>
  );
}
