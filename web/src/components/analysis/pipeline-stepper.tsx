"use client";

import { usePipelineStore } from "@/lib/store";
import { PipelineStepCard } from "./pipeline-step-card";

const STEP_LABELS: Record<string, string> = {
  "scan.universe": "1. Fetch Universe",
  "scan.filtered": "2. Filter Candidates",
  "scan.context": "3. Market Context",
  "scan.shortlist": "4. LLM Shortlist",
  "strategy.indicators": "5. Technical Indicators",
  "strategy.backtest": "6. Backtest",
  "strategy.setups": "7. Strategy Setups",
  "strategy.sized": "8. Risk Sizing",
};

const STEP_ORDER = Object.keys(STEP_LABELS);

export function PipelineStepper() {
  const steps = usePipelineStore((s) => s.steps);

  return (
    <div className="flex flex-col gap-2">
      {STEP_ORDER.map((key) => (
        <PipelineStepCard
          key={key}
          label={STEP_LABELS[key]}
          status={steps[key]?.status ?? "pending"}
          data={steps[key]?.data ?? null}
        />
      ))}
    </div>
  );
}
