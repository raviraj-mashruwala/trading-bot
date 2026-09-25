"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { usePipelineStore } from "@/lib/store";
import { PipelineStepper } from "@/components/analysis/pipeline-stepper";
import { PlanLegsCards } from "@/components/analysis/plan-legs-cards";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Analysis Pipeline</h1>
        <div className="flex items-center gap-3">
          {analysisStatus && (
            <Badge variant={isRunning ? "default" : "secondary"}>
              {analysisStatus.status}{analysisStatus.trade_date ? ` — ${analysisStatus.trade_date}` : ""}
            </Badge>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3">
        <Input
          type="date"
          value={dateInput}
          onChange={(e) => setDateInput(e.target.value)}
          className="w-48"
          placeholder="Trade date (optional)"
        />
        {isRunning ? (
          <Button variant="destructive" onClick={() => cancelMutation.mutate()} disabled={cancelMutation.isPending}>
            Cancel
          </Button>
        ) : (
          <Button onClick={() => runMutation.mutate(dateInput || undefined)} disabled={runMutation.isPending}>
            Run Analysis
          </Button>
        )}
        {runMutation.isError && <span className="text-sm text-red-500">{runMutation.error.message}</span>}
      </div>

      <PipelineStepper />

      {latestPlan && <PlanLegsCards legs={latestPlan.legs} />}

      {pipelineStatus === "failed" && (
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-700">
          Analysis failed: {pipelineError}
        </div>
      )}
    </div>
  );
}
