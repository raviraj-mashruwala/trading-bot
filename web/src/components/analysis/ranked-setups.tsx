"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { SetupCard } from "./setup-card";

export function RankedSetups() {
  const { data: plan, isLoading } = useQuery({
    queryKey: ["daily-plan"],
    queryFn: api.getDailyPlan,
    refetchInterval: 10_000,
  });

  if (isLoading) {
    return <div className="text-[#5a6a7f] text-sm py-4">Loading setups...</div>;
  }

  if (!plan || plan.ranked_suggestions.length === 0) {
    return (
      <div className="bg-[#0f1419] rounded-lg border border-[#1c2736]/50 p-6 text-center">
        <p className="text-[#5a6a7f] text-sm">
          No setups yet. Run analysis to generate trade setups.
        </p>
      </div>
    );
  }

  const executeCount = plan.ranked_suggestions.filter(
    (s) => s.recommendation === "execute"
  ).length;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium text-[#5a6a7f] uppercase tracking-wider">
          Ranked Setups
        </h3>
        <div className="flex items-center gap-3 text-xs">
          <span className="text-[#5a6a7f]">{plan.total_runs} run(s)</span>
          <span className="text-[#2da44e]">{executeCount} ready</span>
          <span className="text-[#5a6a7f]">{plan.ranked_suggestions.length} total</span>
        </div>
      </div>
      {plan.ranked_suggestions.map((suggestion) => (
        <SetupCard
          key={`${suggestion.symbol}-${suggestion.rank}`}
          suggestion={suggestion}
        />
      ))}
    </div>
  );
}
