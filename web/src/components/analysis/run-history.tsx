"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AnalysisRun } from "@/types";

export function RunHistory() {
  const { data: runs, isLoading, isError } = useQuery({
    queryKey: ["analysis-runs"],
    queryFn: () => api.getAnalysisRuns(),
    refetchInterval: 10_000,
    retry: false,
  });

  if (isLoading) {
    return <div className="text-[#5a6a7f] text-sm">Loading runs...</div>;
  }

  if (!runs || runs.length === 0 || isError) {
    return (
      <div className="text-[#5a6a7f] text-sm py-4 text-center">
        No analysis runs today.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <h3 className="text-xs font-medium text-[#5a6a7f] uppercase tracking-wider">
        Today&apos;s Runs
      </h3>
      {runs.map((run: AnalysisRun) => (
        <div
          key={run.run_id}
          className="bg-[#0f1419] rounded-lg p-3 border border-[#1c2736]/50"
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-mono text-[#5a6a7f]">
              {new Date(run.timestamp).toLocaleTimeString("en-IN", {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-[#d4a015]/10 text-[#d4a015]">
              {run.market_regime.replace(/_/g, " ")}
            </span>
          </div>
          <div className="grid grid-cols-4 gap-2 text-xs">
            <div>
              <span className="text-[#5a6a7f] block">Scanned</span>
              <p className="font-mono text-[#c9d1d9]">{run.total_scanned}</p>
            </div>
            <div>
              <span className="text-[#5a6a7f] block">Tier 1</span>
              <p className="font-mono text-[#c9d1d9]">{run.tier1_passed}</p>
            </div>
            <div>
              <span className="text-[#5a6a7f] block">Shortlist</span>
              <p className="font-mono text-[#c9d1d9]">{run.tier2_shortlisted}</p>
            </div>
            <div>
              <span className="text-[#5a6a7f] block">Approved</span>
              <p className="font-mono text-[#2da44e]">{run.setups_approved}</p>
            </div>
          </div>
          <div className="flex items-center gap-3 mt-2 text-xs text-[#5a6a7f]">
            <span>{run.llm_calls} LLM calls</span>
            <span>{run.duration_seconds.toFixed(1)}s</span>
          </div>
        </div>
      ))}
    </div>
  );
}
