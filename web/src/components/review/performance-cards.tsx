"use client";

import type { PerformanceStatsData } from "@/types";

function fmt(n: number, decimals = 0): string {
  return n.toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export function PerformanceCards({ stats }: { stats: PerformanceStatsData }) {
  const cards = [
    { label: "Total trades", value: stats.total_trades.toString(), sub: `${stats.period_days}d` },
    { label: "Win rate", value: `${(stats.win_rate * 100).toFixed(1)}%`, sub: stats.total_trades > 0 ? `${Math.round(stats.win_rate * stats.total_trades)}W / ${stats.total_trades - Math.round(stats.win_rate * stats.total_trades)}L` : "", color: stats.win_rate >= 0.5 ? "text-[#2da44e]" : "text-[#f85149]" },
    { label: "Avg R", value: stats.avg_r_multiple.toFixed(2), sub: "per trade" },
    { label: "Total P&L", value: `₹${fmt(stats.total_pnl)}`, sub: stats.total_pnl >= 0 ? "profit" : "loss", color: stats.total_pnl >= 0 ? "text-[#2da44e]" : "text-[#f85149]" },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map((c) => (
        <div key={c.label} className="py-3">
          <p className="text-xs text-muted-foreground">{c.label}</p>
          <p className={`mt-0.5 font-mono-nums text-xl font-semibold ${c.color ?? "text-[#e6edf3]"}`}>{c.value}</p>
          {c.sub && <p className="mt-0.5 text-[11px] text-muted-foreground/60">{c.sub}</p>}
        </div>
      ))}
    </div>
  );
}
