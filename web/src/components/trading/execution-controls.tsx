"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useExecutionStore } from "@/lib/execution-store";
import { Button } from "@/components/ui/button";

export function ExecutionControls() {
  const [selectedMode, setSelectedMode] = useState<string>("");
  const [selectedPlan, setSelectedPlan] = useState<string>("");
  const queryClient = useQueryClient();
  const execStatus = useExecutionStore((s) => s.status);
  const reset = useExecutionStore((s) => s.reset);

  const { data: config } = useQuery({ queryKey: ["config"], queryFn: api.getConfig });
  const { data: plans } = useQuery({ queryKey: ["plans"], queryFn: api.getPlans });

  const defaultMode = config?.general?.mode as string ?? "paper";
  const mode = selectedMode || defaultMode;

  const startMutation = useMutation({
    mutationFn: () => api.postExecute(mode, selectedPlan || undefined),
    onSuccess: () => {
      reset();
      queryClient.invalidateQueries({ queryKey: ["execution-status"] });
    },
  });

  const stopMutation = useMutation({
    mutationFn: api.stopExecution,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["execution-status"] }),
  });

  const isRunning = execStatus === "running";
  const hasPlans = plans && plans.length > 0;

  return (
    <div className="flex items-center gap-3 flex-wrap">
      {!isRunning && (
        <>
          <select
            className="h-9 rounded-lg border border-border/50 bg-card/80 px-3 text-sm text-foreground/90 outline-none focus:ring-1 focus:ring-amber-500/50"
            value={mode}
            onChange={(e) => setSelectedMode(e.target.value)}
          >
            <option value="paper">Paper</option>
            <option value="live">Live</option>
          </select>

          <select
            className="h-9 rounded-lg border border-border/50 bg-card/80 px-3 text-sm text-foreground/90 outline-none focus:ring-1 focus:ring-amber-500/50"
            value={selectedPlan}
            onChange={(e) => setSelectedPlan(e.target.value)}
          >
            <option value="">Latest plan</option>
            {plans?.map((p) => (
              <option key={p.trade_date} value={p.trade_date}>
                {p.trade_date} ({p.legs_count} legs)
              </option>
            ))}
          </select>

          <Button
            onClick={() => startMutation.mutate()}
            disabled={startMutation.isPending || !hasPlans}
            className="bg-amber-500 text-black font-semibold hover:bg-amber-400"
          >
            Start Execution
          </Button>

          {!hasPlans && <span className="text-xs text-muted-foreground/60">No plans — run analysis first</span>}
        </>
      )}

      {isRunning && (
        <Button
          variant="destructive"
          size="lg"
          className="font-bold shadow-lg shadow-red-500/20"
          onClick={() => stopMutation.mutate()}
          disabled={stopMutation.isPending}
        >
          ⛔ Emergency Stop
        </Button>
      )}

      {startMutation.isError && (
        <span className="text-xs text-red-400">{startMutation.error.message}</span>
      )}

      <div className="flex items-center gap-1.5 ml-auto">
        <span className={`h-1.5 w-1.5 rounded-full ${isRunning ? "bg-emerald-400 animate-pulse" : execStatus === "done" ? "bg-amber-400" : "bg-muted-foreground/30"}`} />
        <span className="text-xs text-muted-foreground uppercase tracking-wider">{execStatus}</span>
      </div>
    </div>
  );
}
