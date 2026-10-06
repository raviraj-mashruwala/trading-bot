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
  elapsed_s: number | null;
  wsConnected: boolean;
  handleEvent: (event: WsEvent) => void;
  setWsConnected: (connected: boolean) => void;
  hydrateFromStatus: (resp: {
    status: string;
    steps?: Record<string, StepState>;
    elapsed_s?: number | null;
    error?: string | null;
  }) => void;
  reset: () => void;
}

export const usePipelineStore = create<PipelineStore>((set, get) => ({
  status: "idle",
  steps: {},
  plan: null,
  error: null,
  elapsed_s: null,
  wsConnected: false,

  handleEvent: (event: WsEvent) => {
    const { type, timestamp, data } = event;

    if (type === "analysis.started") {
      const freshSteps: Record<string, StepState> = {};
      for (const step of PIPELINE_STEPS) {
        freshSteps[step] = { status: "pending", data: null, timestamp: null };
      }
      set({ status: "running", steps: freshSteps, plan: null, error: null, elapsed_s: 0 });
      return;
    }

    if (type === "analysis.complete") {
      set({ status: "complete", elapsed_s: null });
      return;
    }

    if (type === "analysis.failed") {
      set({ status: "failed", error: String(data.error ?? "Unknown error"), elapsed_s: null });
      return;
    }

    if (PIPELINE_STEPS.includes(type as (typeof PIPELINE_STEPS)[number])) {
      const steps = { ...get().steps };
      const stepStatus = data?.status === "fetching" ? "active" : data?.status === "skipped" ? "complete" : "complete";
      steps[type] = { status: stepStatus, data, timestamp };
      if (stepStatus === "complete") {
        const stepIndex = PIPELINE_STEPS.indexOf(type as (typeof PIPELINE_STEPS)[number]);
        const nextStep = PIPELINE_STEPS[stepIndex + 1];
        if (nextStep && steps[nextStep]?.status === "pending") {
          steps[nextStep] = { ...steps[nextStep], status: "active" };
        }
      }
      set({ steps });
    }
  },

  setWsConnected: (connected) => set({ wsConnected: connected }),

  hydrateFromStatus: (resp) => {
    const current = get();
    if (resp.status === "idle" && current.status === "running") {
      set({ status: "idle", steps: {}, elapsed_s: null, error: null });
      return;
    }
    if (current.status === "running" && current.wsConnected && Object.keys(current.steps).length > 0) {
      if (resp.elapsed_s != null) set({ elapsed_s: resp.elapsed_s });
      return;
    }
    if (resp.status === "running" && resp.steps && Object.keys(resp.steps).length > 0) {
      set({
        status: "running",
        steps: resp.steps,
        elapsed_s: resp.elapsed_s ?? null,
        error: null,
      });
    } else if (resp.status === "complete" && current.status !== "complete") {
      set({ status: "complete", elapsed_s: null });
    } else if (resp.status === "failed" && current.status !== "failed") {
      set({ status: "failed", error: resp.error ?? null, elapsed_s: null });
    }
  },

  reset: () => set({ status: "idle", steps: {}, plan: null, error: null, elapsed_s: null, wsConnected: false }),
}));
