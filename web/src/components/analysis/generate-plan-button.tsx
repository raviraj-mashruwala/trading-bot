"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function GeneratePlanButton() {
  const [result, setResult] = useState<{ legs: number; date: string } | null>(null);
  const qc = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => api.generatePlan(),
    onSuccess: (data) => {
      setResult({ legs: data.legs, date: data.trade_date });
      qc.invalidateQueries({ queryKey: ["daily-plan"] });
      qc.invalidateQueries({ queryKey: ["plans"] });
    },
  });

  return (
    <div className="flex items-center gap-3">
      <button
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending}
        className="rounded-lg border border-[#d4a015]/30 bg-[#d4a015]/10 px-4 py-2 text-xs font-medium text-[#d4a015] transition-all hover:bg-[#d4a015]/20 disabled:opacity-50"
      >
        {mutation.isPending ? "Generating..." : "Generate Plan"}
      </button>
      {result && (
        <span className="text-xs text-muted-foreground">
          Plan for {result.date}: {result.legs} leg{result.legs !== 1 ? "s" : ""}
        </span>
      )}
      {mutation.isError && (
        <span className="text-xs text-[#f85149]">Failed to generate plan</span>
      )}
    </div>
  );
}
