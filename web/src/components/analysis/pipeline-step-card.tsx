"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import type { StepStatus } from "@/types";

const STATUS_CONFIG: Record<StepStatus, { dot: string; border: string; bg: string; text: string; label: string }> = {
  pending: { dot: "bg-muted-foreground/30", border: "border-border/30", bg: "", text: "text-muted-foreground/50", label: "Pending" },
  active: { dot: "bg-[#d4a015] animate-pulse", border: "border-[#d4a015]/40", bg: "bg-[#d4a015]/5", text: "text-[#d4a015]", label: "Running" },
  complete: { dot: "bg-[#2da44e]", border: "border-[#2da44e]/30", bg: "bg-[#2da44e]/5", text: "text-[#2da44e]", label: "Done" },
  failed: { dot: "bg-red-400", border: "border-[#f85149]/30", bg: "bg-[#f85149]/5", text: "text-[#f85149]", label: "Failed" },
};

interface Props {
  label: string;
  stepNumber: number;
  status: StepStatus;
  data: Record<string, unknown> | null;
  isLast?: boolean;
}

export function PipelineStepCard({ label, stepNumber, status, data, isLast }: Props) {
  const [expanded, setExpanded] = useState(false);
  const canExpand = status === "complete" && data !== null;
  const cfg = STATUS_CONFIG[status];

  return (
    <div className="relative flex gap-3">
      <div className="flex flex-col items-center">
        <div className={cn("flex h-7 w-7 items-center justify-center rounded-full border text-[11px] font-semibold", cfg.border, cfg.bg, cfg.text)}>
          {status === "complete" ? "✓" : stepNumber}
        </div>
        {!isLast && (
          <div className={cn("w-px flex-1 min-h-[8px]", status === "complete" ? "bg-[#2da44e]/30" : "bg-border/40")} />
        )}
      </div>
      <div
        data-testid="step-card"
        className={cn(
          "mb-1.5 flex-1 rounded-lg border px-4 py-2.5 transition-all duration-200",
          cfg.border, cfg.bg,
          canExpand && "cursor-pointer hover:bg-muted/30",
          status === "pending" && "opacity-50"
        )}
        onClick={() => canExpand && setExpanded(!expanded)}
      >
        <div className="flex items-center justify-between">
          <span className={cn("text-[13px] font-medium", cfg.text)}>{label}</span>
          <span className={cn("text-[10px] uppercase tracking-wider", cfg.text)}>{cfg.label}</span>
        </div>
        {status === "active" && data?.message && (
          <p className="mt-1 text-[11px] text-muted-foreground">{String(data.message)}</p>
        )}
        {expanded && data && (
          <pre className="mt-2 max-h-40 overflow-auto rounded bg-black/30 p-2 text-[11px] text-muted-foreground">
            {JSON.stringify(data, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
