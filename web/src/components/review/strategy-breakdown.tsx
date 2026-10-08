"use client";

import type { PerformanceStatsData, StrategyStatsData } from "@/types";

function Row({ label, s }: { label: string; s: StrategyStatsData }) {
  const winColor = s.win_rate >= 0.6 ? "text-[#2da44e]" : s.win_rate >= 0.45 ? "text-[#d4a015]" : "text-[#f85149]";
  return (
    <tr className="border-b border-border/30 last:border-0">
      <td className="py-2 text-sm font-medium text-foreground/90">{label}</td>
      <td className="py-2 text-right text-sm text-muted-foreground">{s.trades}</td>
      <td className={`py-2 text-right text-sm font-medium ${winColor}`}>{(s.win_rate * 100).toFixed(1)}%</td>
      <td className="py-2 text-right text-sm text-muted-foreground">{s.avg_r.toFixed(2)}</td>
      <td className={`py-2 text-right text-sm font-medium ${s.total_pnl >= 0 ? "text-[#2da44e]" : "text-[#f85149]"}`}>
        ₹{s.total_pnl.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
      </td>
    </tr>
  );
}

function Table({ title, data }: { title: string; data: Record<string, StrategyStatsData> }) {
  const entries = Object.entries(data).sort(([, a], [, b]) => b.trades - a.trades);
  if (entries.length === 0) return null;

  return (
    <div className="rounded-lg border border-border/50 bg-card/80 p-4">
      <h3 className="mb-3 text-xs font-medium text-muted-foreground">{title}</h3>
      <table className="w-full">
        <thead>
          <tr className="border-b border-border/50 text-[11px] font-medium text-muted-foreground/60">
            <th className="pb-2 text-left">Name</th>
            <th className="pb-2 text-right">Trades</th>
            <th className="pb-2 text-right">Win %</th>
            <th className="pb-2 text-right">Avg R</th>
            <th className="pb-2 text-right">PnL</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([k, v]) => <Row key={k} label={k.replace("_", " ")} s={v} />)}
        </tbody>
      </table>
    </div>
  );
}

export function StrategyBreakdown({ stats }: { stats: PerformanceStatsData }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      <Table title="By Strategy" data={stats.by_strategy} />
      <Table title="By Regime" data={stats.by_regime} />
    </div>
  );
}
