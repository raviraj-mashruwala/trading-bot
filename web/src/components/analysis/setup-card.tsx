"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { RankedSuggestion } from "@/types";

const REC_COLORS: Record<string, string> = {
  execute: "bg-[#2da44e]/10 text-[#2da44e]",
  watch: "bg-[#d4a015]/10 text-[#d4a015]",
  conflicting: "bg-[#f85149]/10 text-[#f85149]",
  stale: "bg-[#5a6a7f]/10 text-[#5a6a7f]",
};

export function SetupCard({ suggestion }: { suggestion: RankedSuggestion }) {
  const queryClient = useQueryClient();
  const setup = suggestion.best_setup;

  const mutation = useMutation({
    mutationFn: ({ status, reason }: { status: string; reason?: string }) =>
      api.patchSetup(setup.id, status, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["daily-plan"] });
    },
  });

  const risk = Math.abs(setup.entry_price - setup.stop_loss);
  const reward = Math.abs(setup.target_1 - setup.entry_price);
  const rr = risk > 0 ? reward / risk : 0;

  return (
    <div className="bg-[#0f1419] rounded-lg border border-[#1c2736]/50 p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="text-xs font-mono text-[#5a6a7f]">#{suggestion.rank}</span>
          <span className="text-base font-bold text-[#c9d1d9]">{setup.symbol}</span>
          <span
            className={`text-xs px-2 py-0.5 rounded-full ${
              setup.direction === "long"
                ? "bg-[#2da44e]/10 text-[#2da44e]"
                : "bg-[#f85149]/10 text-[#f85149]"
            }`}
          >
            {setup.direction.toUpperCase()}
          </span>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded-full ${REC_COLORS[suggestion.recommendation] || ""}`}>
          {suggestion.recommendation}
        </span>
      </div>

      {/* Price levels */}
      <div className="grid grid-cols-4 gap-3 mb-3">
        <div>
          <span className="text-xs text-[#5a6a7f] block">Entry</span>
          <span className="font-mono text-sm text-[#c9d1d9]">₹{setup.entry_price.toFixed(1)}</span>
        </div>
        <div>
          <span className="text-xs text-[#5a6a7f] block">Stop Loss</span>
          <span className="font-mono text-sm text-[#f85149]">₹{setup.stop_loss.toFixed(1)}</span>
        </div>
        <div>
          <span className="text-xs text-[#5a6a7f] block">Target 1</span>
          <span className="font-mono text-sm text-[#2da44e]">₹{setup.target_1.toFixed(1)}</span>
        </div>
        <div>
          <span className="text-xs text-[#5a6a7f] block">R:R</span>
          <span className="font-mono text-sm text-[#d4a015]">{rr.toFixed(1)}:1</span>
        </div>
      </div>

      {/* Confidence + consistency */}
      <div className="flex items-center gap-4 mb-3">
        <div className="flex-1">
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-[#5a6a7f]">Confidence</span>
            <span className="font-mono text-[#c9d1d9]">{(suggestion.confidence * 100).toFixed(0)}%</span>
          </div>
          <div className="h-1.5 bg-[#070a0f] rounded-full overflow-hidden">
            <div
              className="h-full bg-[#d4a015] rounded-full transition-all"
              style={{ width: `${suggestion.confidence * 100}%` }}
            />
          </div>
        </div>
        <div className="text-xs text-[#5a6a7f] whitespace-nowrap">
          <span className="font-mono text-[#c9d1d9]">{suggestion.run_count}</span> run{suggestion.run_count !== 1 ? "s" : ""}
          {" "}
          <span className="font-mono text-[#d4a015]">
            ({(suggestion.consistency * 100).toFixed(0)}%)
          </span>
        </div>
      </div>

      {/* Strategy + reasoning */}
      <div className="text-xs text-[#5a6a7f] mb-3">
        <span className="text-[#c9d1d9] font-medium">{setup.strategy.replace(/_/g, " ")}</span>
        {setup.reasoning && <span className="ml-2">— {setup.reasoning}</span>}
      </div>

      {/* Actions */}
      {(setup.status === "approved" || setup.status === "proposed") && (
        <div className="flex items-center gap-2">
          {setup.status === "proposed" && (
            <button
              onClick={() => mutation.mutate({ status: "approved" })}
              disabled={mutation.isPending}
              className="flex-1 px-3 py-1.5 bg-[#d4a015]/10 text-[#d4a015] text-xs font-medium rounded-md hover:bg-[#d4a015]/20 transition-colors disabled:opacity-50 cursor-pointer"
            >
              Approve
            </button>
          )}
          {setup.status === "approved" && (
            <button
              onClick={() => mutation.mutate({ status: "active" })}
              disabled={mutation.isPending}
              className="flex-1 px-3 py-1.5 bg-[#2da44e]/10 text-[#2da44e] text-xs font-medium rounded-md hover:bg-[#2da44e]/20 transition-colors disabled:opacity-50 cursor-pointer"
            >
              Execute
            </button>
          )}
          <button
            onClick={() => mutation.mutate({ status: "rejected", reason: "manual" })}
            disabled={mutation.isPending}
            className="px-3 py-1.5 bg-[#f85149]/10 text-[#f85149] text-xs font-medium rounded-md hover:bg-[#f85149]/20 transition-colors disabled:opacity-50 cursor-pointer"
          >
            Reject
          </button>
        </div>
      )}
      {setup.status === "rejected" && (
        <div className="text-xs text-[#f85149]/60">
          Rejected{setup.rejection_reason ? `: ${setup.rejection_reason}` : ""}
        </div>
      )}
      {setup.status === "active" && (
        <div className="text-xs text-[#2da44e]">Active — awaiting execution</div>
      )}
    </div>
  );
}
