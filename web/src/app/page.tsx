"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { EquityCurve } from "@/components/dashboard/equity-curve";
import { DailyPnlChart } from "@/components/dashboard/daily-pnl-chart";
import { WinRateDonut } from "@/components/dashboard/win-rate-donut";
import { LastAnalysis } from "@/components/dashboard/last-analysis";
import { MarketStatus } from "@/components/dashboard/market-status";
import { OnboardingChecklist } from "@/components/dashboard/onboarding-checklist";
import { SectorHeatmap } from "@/components/dashboard/sector-heatmap";

function fmt(n: number): string {
  const abs = Math.abs(n);
  return abs >= 1000 ? `${(abs / 1000).toFixed(1)}k` : abs.toFixed(0);
}

export default function DashboardPage() {
  const { data: stats } = useQuery({ queryKey: ["trade-stats"], queryFn: () => api.getTradeStats(30) });
  const { data: trades } = useQuery({ queryKey: ["trades"], queryFn: () => api.getTrades(30) });

  const pnl = stats?.total_pnl ?? 0;
  const winRate = stats?.win_rate ?? 0;
  const tradeCount = stats?.trade_count ?? 0;
  const wins = Math.round(winRate * tradeCount);
  const losses = tradeCount - wins;

  return (
    <div className="space-y-6">
      <OnboardingChecklist />

      {/* Hero — today's P&L is the face of the watch */}
      <div className="flex items-end justify-between pt-2">
        <div>
          <p className="text-xs text-muted-foreground mb-1">30-day P&L</p>
          <p className={`hero-number text-5xl ${pnl >= 0 ? "text-[#2da44e]" : "text-[#f85149]"}`}>
            {pnl >= 0 ? "+" : "-"}₹{fmt(Math.abs(pnl))}
          </p>
        </div>
        <div className="flex items-center gap-6 text-right">
          <div>
            <p className="text-xs text-muted-foreground">Trades</p>
            <p className="text-2xl font-mono-nums font-semibold text-[#e6edf3]">{tradeCount}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Win rate</p>
            <p className="text-2xl font-mono-nums font-semibold text-[#e6edf3]">{(winRate * 100).toFixed(0)}%</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Record</p>
            <p className="text-lg font-mono-nums">
              <span className="text-[#2da44e]">{wins}W</span>
              <span className="text-muted-foreground mx-1">/</span>
              <span className="text-[#f85149]">{losses}L</span>
            </p>
          </div>
        </div>
      </div>

      <MarketStatus />

      {/* Charts — the subdials */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <EquityCurve trades={trades ?? []} />
        <DailyPnlChart trades={trades ?? []} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <WinRateDonut winRate={winRate} tradeCount={tradeCount} />
        <LastAnalysis />
      </div>

      <SectorHeatmap />
    </div>
  );
}
