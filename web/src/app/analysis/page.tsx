"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { usePipelineStore } from "@/lib/store";
import { PipelineStepper } from "@/components/analysis/pipeline-stepper";
import { PlanLegsCards } from "@/components/analysis/plan-legs-cards";
import { RunHistory } from "@/components/analysis/run-history";
import { RankedSetups } from "@/components/analysis/ranked-setups";
import { Button } from "@/components/ui/button";
import type { TradePlan } from "@/types";

export default function AnalysisPage() {
  const [dateInput, setDateInput] = useState("");
  const queryClient = useQueryClient();
  const pipelineStatus = usePipelineStore((s) => s.status);
  const pipelineError = usePipelineStore((s) => s.error);
  const reset = usePipelineStore((s) => s.reset);

  const { data: analysisStatus } = useQuery({
    queryKey: ["analysis-status"],
    queryFn: api.getAnalysisStatus,
    refetchInterval: pipelineStatus === "running" ? 3_000 : 30_000,
  });

  const { data: latestPlan } = useQuery<TradePlan | null>({
    queryKey: ["latest-plan", analysisStatus?.trade_date],
    queryFn: async () => {
      if (!analysisStatus?.trade_date || analysisStatus.status !== "complete") return null;
      return api.getPlan(analysisStatus.trade_date);
    },
    enabled: analysisStatus?.status === "complete" && !!analysisStatus?.trade_date,
  });

  const runMutation = useMutation({
    mutationFn: (date?: string) => api.postAnalyze(date || undefined),
    onSuccess: () => {
      reset();
      queryClient.invalidateQueries({ queryKey: ["analysis-status"] });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: api.cancelAnalysis,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["analysis-status"] }),
  });

  const isRunning = pipelineStatus === "running" || analysisStatus?.status === "running";
  const isComplete = analysisStatus?.status === "complete";

  // Invalidate v2 queries when analysis completes
  if (isComplete && pipelineStatus !== "running") {
    queryClient.invalidateQueries({ queryKey: ["daily-plan"] });
    queryClient.invalidateQueries({ queryKey: ["analysis-runs"] });
  }

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Analysis Pipeline</h1>
        <div className="flex items-center gap-2">
          <span className={`h-1.5 w-1.5 rounded-full ${isRunning ? "bg-[#d4a015] animate-pulse" : isComplete ? "bg-[#2da44e]" : "bg-muted-foreground/30"}`} />
          <span className="text-xs text-muted-foreground uppercase tracking-wider">
            {analysisStatus?.status ?? "idle"}{analysisStatus?.trade_date ? ` — ${analysisStatus.trade_date}` : ""}
          </span>
        </div>
      </div>

      {/* Controls */}
      <div className="flex items-center gap-3">
        <input
          type="date"
          value={dateInput}
          onChange={(e) => setDateInput(e.target.value)}
          className="h-9 w-44 rounded-lg border border-border/50 bg-card/80 px-3 text-sm text-foreground/90 outline-none focus:ring-1 focus:ring-[#d4a015]/50"
          placeholder="Trade date"
        />
        {isRunning ? (
          <Button variant="destructive" onClick={() => cancelMutation.mutate()} disabled={cancelMutation.isPending}>
            Cancel
          </Button>
        ) : (
          <Button onClick={() => runMutation.mutate(dateInput || undefined)} disabled={runMutation.isPending} className="bg-[#d4a015] text-black font-semibold hover:bg-[#d4a015]">
            Run Analysis
          </Button>
        )}
        {runMutation.isError && <span className="text-xs text-[#f85149]">{runMutation.error.message}</span>}
      </div>

      {/* Pipeline + Run History (side by side) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="lg:col-span-2">
          <PipelineStepper />
        </div>
        <div>
          <RunHistory />
        </div>
      </div>

      {/* V1 legacy plan legs (if v1 was used) */}
      {latestPlan && latestPlan.legs.length > 0 && <PlanLegsCards legs={latestPlan.legs} />}

      {/* V2 ranked setups */}
      <RankedSetups />

      {/* Error state */}
      {pipelineStatus === "failed" && (
        <div className="rounded-lg border border-[#f85149]/30 bg-[#f85149]/5 p-4 text-sm text-[#f85149]">
          Analysis failed: {pipelineError}
        </div>
      )}
    </div>
  );
}
