"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { StatCards } from "@/components/dashboard/stat-cards";
import { EquityCurve } from "@/components/dashboard/equity-curve";
import { DailyPnlChart } from "@/components/dashboard/daily-pnl-chart";
import { WinRateDonut } from "@/components/dashboard/win-rate-donut";
import { LastAnalysis } from "@/components/dashboard/last-analysis";
import { MarketStatus } from "@/components/dashboard/market-status";
import { KeepAwake } from "@/components/dashboard/keep-awake";

export default function DashboardPage() {
  const { data: stats } = useQuery({ queryKey: ["trade-stats"], queryFn: () => api.getTradeStats(30) });
  const { data: trades } = useQuery({ queryKey: ["trades"], queryFn: () => api.getTrades(30) });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Dashboard</h1>
        <KeepAwake />
      </div>

      <MarketStatus />

      {stats && <StatCards stats={stats} />}

      <div className="grid grid-cols-2 gap-3">
        <EquityCurve trades={trades ?? []} />
        <DailyPnlChart trades={trades ?? []} />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <WinRateDonut winRate={stats?.win_rate ?? 0} tradeCount={stats?.trade_count ?? 0} />
        <LastAnalysis />
      </div>
    </div>
  );
}
