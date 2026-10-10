"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

interface ScoutStatsData {
  total: number;
  wins: number;
  losses: number;
  timeouts: number;
  win_rate: number;
  avg_pnl_pct: number;
}

export function ScoutStats() {
  const { data } = useQuery({
    queryKey: ["scout-stats"],
    queryFn: async (): Promise<ScoutStatsData> => {
      const raw = await api.getScoutStats();
      return raw as unknown as ScoutStatsData;
    },
    refetchInterval: 30_000,
  });

  if (!data || data.total === 0) return null;

  const winColor =
    data.win_rate > 50
      ? "text-[#2da44e]"
      : data.win_rate < 40
        ? "text-[#f85149]"
        : "text-[#d4a015]";

  const pnlColor = data.avg_pnl_pct >= 0 ? "text-[#2da44e]" : "text-[#f85149]";

  return (
    <div className="flex items-center gap-4 rounded-lg border border-border/20 bg-card/30 px-4 py-2 text-xs">
      <div className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-[#d4a015]" />
        <span className="text-muted-foreground font-medium uppercase tracking-wider">Scout</span>
      </div>
      <div className="flex items-center gap-3 text-muted-foreground">
        <span>{data.total} alerts</span>
        <span className="text-border/50">|</span>
        <span>
          Win rate: <span className={`font-medium ${winColor}`}>{data.win_rate.toFixed(1)}%</span>
        </span>
        <span className="text-border/50">|</span>
        <span>
          Avg P&L: <span className={`font-medium ${pnlColor}`}>{data.avg_pnl_pct >= 0 ? "+" : ""}{data.avg_pnl_pct.toFixed(3)}%</span>
        </span>
        <span className="text-border/50">|</span>
        <span className="text-muted-foreground/60">
          {data.wins}W {data.losses}L {data.timeouts}T
        </span>
      </div>
    </div>
  );
}
