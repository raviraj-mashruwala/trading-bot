"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useExecutionStore } from "@/lib/execution-store";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

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
            className="rounded-md border bg-background px-3 py-2 text-sm"
            value={mode}
            onChange={(e) => setSelectedMode(e.target.value)}
          >
            <option value="paper">Paper</option>
            <option value="live">Live</option>
          </select>

          <select
            className="rounded-md border bg-background px-3 py-2 text-sm"
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
          >
            Start Execution
          </Button>

          {!hasPlans && <span className="text-sm text-muted-foreground">No plans available — run analysis first</span>}
        </>
      )}

      {isRunning && (
        <Button
          variant="destructive"
          size="lg"
          className="font-bold"
          onClick={() => stopMutation.mutate()}
          disabled={stopMutation.isPending}
        >
          ⛔ Emergency Stop
        </Button>
      )}

      {startMutation.isError && (
        <span className="text-sm text-red-500">{startMutation.error.message}</span>
      )}

      <Badge variant={isRunning ? "default" : "secondary"}>
        {execStatus}
      </Badge>
    </div>
  );
}
