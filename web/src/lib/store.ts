import { create } from "zustand";
import type { PipelineStatus, StepState, TradePlan, WsEvent } from "@/types";

const PIPELINE_STEPS = [
  "scan.universe", "scan.filtered", "scan.context", "scan.shortlist",
  "strategy.indicators", "strategy.backtest", "strategy.setups", "strategy.sized",
] as const;

interface PipelineStore {
  status: PipelineStatus;
  steps: Record<string, StepState>;
  plan: TradePlan | null;
  error: string | null;
  handleEvent: (event: WsEvent) => void;
  reset: () => void;
}

export const usePipelineStore = create<PipelineStore>((set, get) => ({
  status: "idle",
  steps: {},
  plan: null,
  error: null,

  handleEvent: (event: WsEvent) => {
    const { type, timestamp, data } = event;

    if (type === "analysis.started") {
      const freshSteps: Record<string, StepState> = {};
      for (const step of PIPELINE_STEPS) {
        freshSteps[step] = { status: "pending", data: null, timestamp: null };
      }
      set({ status: "running", steps: freshSteps, plan: null, error: null });
      return;
    }

    if (type === "analysis.complete") {
      set({ status: "complete" });
      return;
    }

    if (type === "analysis.failed") {
      set({ status: "failed", error: (data.error as string) ?? "Unknown error" });
      return;
    }

    if (PIPELINE_STEPS.includes(type as (typeof PIPELINE_STEPS)[number])) {
      const steps = { ...get().steps };
      steps[type] = { status: "complete", data, timestamp };
      const stepIndex = PIPELINE_STEPS.indexOf(type as (typeof PIPELINE_STEPS)[number]);
      const nextStep = PIPELINE_STEPS[stepIndex + 1];
      if (nextStep && steps[nextStep]?.status === "pending") {
        steps[nextStep] = { ...steps[nextStep], status: "active" };
      }
      set({ steps });
    }
  },

  reset: () => set({ status: "idle", steps: {}, plan: null, error: null }),
}));
