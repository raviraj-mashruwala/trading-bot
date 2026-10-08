"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useExecutionStore } from "@/lib/execution-store";
import { Button } from "@/components/ui/button";
import { AlertDialog } from "@/components/ui/dialog";

export function ExecutionControls() {
  const [selectedMode, setSelectedMode] = useState<string>("");
  const [selectedPlan, setSelectedPlan] = useState<string>("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [stopConfirmOpen, setStopConfirmOpen] = useState(false);
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

  const handleStart = () => {
    if (mode === "live") {
      setConfirmOpen(true);
    } else {
      startMutation.mutate();
    }
  };

  const handleConfirmStart = () => {
    startMutation.mutate();
    setConfirmOpen(false);
  };

  const handleStop = () => {
    setStopConfirmOpen(true);
  };

  const handleConfirmStop = () => {
    stopMutation.mutate();
    setStopConfirmOpen(false);
  };

  return (
    <div className="flex items-center gap-3 flex-wrap">
      {!isRunning && (
        <>
          <select
            className="h-9 rounded-lg border border-border/50 bg-card/80 px-3 text-sm text-foreground/90 outline-none focus:ring-1 focus:ring-[#d4a015]/50"
            value={mode}
            onChange={(e) => setSelectedMode(e.target.value)}
          >
            <option value="paper">Paper</option>
            <option value="live">Live</option>
          </select>

          <select
            className="h-9 rounded-lg border border-border/50 bg-card/80 px-3 text-sm text-foreground/90 outline-none focus:ring-1 focus:ring-[#d4a015]/50"
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
            onClick={handleStart}
            disabled={startMutation.isPending || !hasPlans}
            className="bg-[#d4a015] text-black font-semibold hover:bg-[#d4a015]"
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
          className="font-bold"
          onClick={handleStop}
          disabled={stopMutation.isPending}
        >
          Emergency Stop
        </Button>
      )}

      {startMutation.isError && (
        <span className="text-xs text-[#f85149]">{startMutation.error.message}</span>
      )}

      <div className="flex items-center gap-1.5 ml-auto">
        <span className={`h-1.5 w-1.5 rounded-full ${isRunning ? "bg-[#2da44e] animate-pulse" : execStatus === "done" ? "bg-[#d4a015]" : "bg-muted-foreground/30"}`} />
        <span className="text-xs text-muted-foreground uppercase tracking-wider">{execStatus}</span>
      </div>

      <AlertDialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={handleConfirmStart}
        title="Start Live Execution?"
        description="This will place real orders on NSE through Kite. Mode: LIVE."
        confirmLabel="Start Live Trading"
        variant="destructive"
        loading={startMutation.isPending}
      />

      <AlertDialog
        open={stopConfirmOpen}
        onClose={() => setStopConfirmOpen(false)}
        onConfirm={handleConfirmStop}
        title="Emergency Stop?"
        description="This will cancel all pending orders and close all open positions at market price."
        confirmLabel="Stop Everything"
        variant="destructive"
        loading={stopMutation.isPending}
      />
    </div>
  );
}
