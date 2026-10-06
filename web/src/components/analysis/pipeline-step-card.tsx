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

function parseProgress(data: Record<string, unknown> | null): { current: number; total: number } | null {
  if (!data?.progress) return null;
  const parts = String(data.progress).split("/");
  if (parts.length !== 2) return null;
  const current = parseInt(parts[0], 10);
  const total = parseInt(parts[1], 10);
  if (isNaN(current) || isNaN(total) || total === 0) return null;
  return { current, total };
}

interface Props {
  label: string;
  stepNumber: number;
  status: StepStatus;
  data: Record<string, unknown> | null;
  history?: Array<{ symbol: string; data: Record<string, unknown>; timestamp: string }>;
  isLast?: boolean;
}

export function PipelineStepCard({ label, stepNumber, status, data, history, isLast }: Props) {
  const [expanded, setExpanded] = useState(false);
  const canExpand = (status === "complete" || status === "active") && (data !== null || (history && history.length > 0));
  const cfg = STATUS_CONFIG[status];
  const progress = status === "active" ? parseProgress(data) : null;
  const symbol = status === "active" && data?.symbol ? String(data.symbol) : null;
  const message = status === "active" && data?.message ? String(data.message) : null;

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
          "mb-1.5 flex-1 rounded-lg border px-4 py-2.5 transition-all duration-200 overflow-hidden",
          cfg.border, cfg.bg,
          canExpand && "cursor-pointer hover:bg-muted/30",
          status === "pending" && "opacity-50"
        )}
        onClick={() => canExpand && setExpanded(!expanded)}
      >
        <div className="flex items-center justify-between">
          <span className={cn("text-[13px] font-medium", cfg.text)}>
            {label}
            {symbol && <span className="ml-2 text-[11px] font-normal text-muted-foreground">{symbol}</span>}
          </span>
          <div className="flex items-center gap-2">
            {progress && (
              <span className="text-[10px] tabular-nums text-muted-foreground">
                {progress.current}/{progress.total}
              </span>
            )}
            <span className={cn("text-[10px] uppercase tracking-wider", cfg.text)}>{cfg.label}</span>
          </div>
        </div>
        {message && (
          <p className="mt-1 text-[11px] text-muted-foreground truncate">{message}</p>
        )}
        {progress && (
          <div className="mt-1.5 h-1 w-full rounded-full bg-border/30 overflow-hidden">
            <div
              className="h-full rounded-full bg-[#d4a015] transition-all duration-500 ease-out"
              style={{ width: `${(progress.current / progress.total) * 100}%` }}
            />
          </div>
        )}
        {expanded && history && history.length > 0 && (
          <div className="mt-2 max-h-48 overflow-auto space-y-1">
            {history.map((h) => {
              const passes = h.data.strategies_passed as number | undefined;
              const setups = h.data.setups_found as number | undefined;
              const skipped = h.data.status === "skipped";
              return (
                <div key={h.symbol} className="flex items-center justify-between rounded bg-black/20 px-2 py-1 text-[11px]">
                  <span className="font-medium text-foreground/80">{h.symbol}</span>
                  <span className="text-muted-foreground">
                    {skipped ? "skipped" : passes !== undefined ? `${passes} strategies` : setups !== undefined ? `${setups} setups` : h.data.message ? String(h.data.message) : "done"}
                  </span>
                </div>
              );
            })}
          </div>
        )}
        {expanded && !history?.length && data && (
          <pre className="mt-2 max-h-40 overflow-auto rounded bg-black/30 p-2 text-[11px] text-muted-foreground">
            {JSON.stringify(data, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
