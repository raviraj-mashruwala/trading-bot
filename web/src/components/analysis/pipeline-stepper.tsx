"use client";

import { usePipelineStore } from "@/lib/store";
import { PipelineStepCard } from "./pipeline-step-card";

const STEPS = [
  { key: "scan.context", label: "Market Context" },
  { key: "scan.universe", label: "Fetch Universe" },
  { key: "scan.filtered", label: "Filter Candidates" },
  { key: "scan.shortlist", label: "LLM Shortlist" },
  { key: "strategy.indicators", label: "Technical Indicators" },
  { key: "strategy.backtest", label: "Backtest" },
  { key: "strategy.deep_analysis", label: "Deep Analysis" },
  { key: "strategy.setups", label: "Strategy Setups" },
  { key: "strategy.sized", label: "Risk Sizing" },
];

export function PipelineStepper() {
  const steps = usePipelineStore((s) => s.steps);

  return (
    <div className="flex flex-col">
      {STEPS.map((step, i) => (
        <PipelineStepCard
          key={step.key}
          label={step.label}
          stepNumber={i + 1}
          status={steps[step.key]?.status ?? "pending"}
          data={steps[step.key]?.data ?? null}
          isLast={i === STEPS.length - 1}
        />
      ))}
    </div>
  );
}
