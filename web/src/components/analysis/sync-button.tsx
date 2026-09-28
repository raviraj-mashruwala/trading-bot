"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function SyncButton() {
  const queryClient = useQueryClient();

  const { data: kiteStatus } = useQuery({
    queryKey: ["kite-status"],
    queryFn: api.getKiteStatus,
    refetchInterval: 30_000,
  });

  const { data: syncStatus } = useQuery({
    queryKey: ["sync-status"],
    queryFn: api.getSyncStatus,
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 2_000 : 30_000,
  });

  const syncMutation = useMutation({
    mutationFn: api.postSync,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sync-status"] });
    },
  });

  const isRunning = syncStatus?.status === "running";
  const isComplete = syncStatus?.status === "complete";
  const isFailed = syncStatus?.status === "failed";
  const notAuthenticated = !kiteStatus?.authenticated;

  return (
    <div className="flex items-center gap-3">
      <button
        onClick={() => syncMutation.mutate()}
        disabled={isRunning || notAuthenticated || syncMutation.isPending}
        className="px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed bg-[#161d26] text-[#c9d1d9] border border-[#1c2736]/50 hover:bg-[#1c2736]"
      >
        {isRunning ? "Syncing..." : "Sync Data"}
      </button>
      {isRunning && (
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 border-2 border-[#d4a015] border-t-transparent rounded-full animate-spin" />
          <span className="text-xs text-[#d4a015]">{syncStatus?.progress}</span>
        </div>
      )}
      {isComplete && syncStatus?.progress && (
        <span className="text-xs text-[#2da44e]">{syncStatus.progress}</span>
      )}
      {isFailed && (
        <span className="text-xs text-[#f85149]">Failed: {syncStatus?.progress}</span>
      )}
      {notAuthenticated && !isRunning && (
        <span className="text-xs text-[#5a6a7f]">Connect Kite first</span>
      )}
    </div>
  );
}
