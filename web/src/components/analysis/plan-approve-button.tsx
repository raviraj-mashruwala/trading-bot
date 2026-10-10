"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function PlanApproveButton({ tradeDate }: { tradeDate: string }) {
  const queryClient = useQueryClient();

  const { data } = useQuery({
    queryKey: ["plan-review-status", tradeDate],
    queryFn: () => api.getPlanReviewStatus(tradeDate),
    enabled: !!tradeDate,
  });

  const mutation = useMutation({
    mutationFn: () => api.approvePlan(tradeDate),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["plan-review-status", tradeDate] }),
  });

  const reviewed = data?.reviewed ?? false;

  return (
    <div className="flex items-center gap-3 mt-2">
      {reviewed ? (
        <div className="flex items-center gap-1.5 text-xs text-[#2da44e]">
          <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="currentColor">
            <path d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.75.75 0 0 1 1.06-1.06L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0Z" />
          </svg>
          <span>Plan reviewed</span>
        </div>
      ) : (
        <button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
          className="flex items-center gap-1.5 rounded-lg border border-[#d4a015]/30 bg-[#d4a015]/10 px-3 py-1.5 text-xs font-medium text-[#d4a015] hover:bg-[#d4a015]/20 transition-colors"
        >
          <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M2 8l4 4 8-8" />
          </svg>
          {mutation.isPending ? "Approving..." : "Review & Approve Plan"}
        </button>
      )}
    </div>
  );
}
