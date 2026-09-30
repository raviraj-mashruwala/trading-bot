"use client";

import type { PerformanceStatsData } from "@/types";

function fmt(n: number, decimals = 0): string {
  return n.toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

export function PerformanceCards({ stats }: { stats: PerformanceStatsData }) {
  const cards = [
    { label: "Total Trades", value: stats.total_trades.toString(), sub: `${stats.period_days}d` },
    { label: "Win Rate", value: pct(stats.win_rate), sub: stats.total_trades > 0 ? `${Math.round(stats.win_rate * stats.total_trades)}W / ${stats.total_trades - Math.round(stats.win_rate * stats.total_trades)}L` : "" },
    { label: "Avg R", value: stats.avg_r_multiple.toFixed(2), sub: "per trade" },
    { label: "Total PnL", value: `₹${fmt(stats.total_pnl)}`, sub: stats.total_pnl >= 0 ? "profit" : "loss", color: stats.total_pnl >= 0 ? "text-[#2da44e]" : "text-[#f85149]" },
  ];

  return (
    <div className="grid grid-cols-4 gap-3">
      {cards.map((c) => (
        <div key={c.label} className="rounded-lg border border-border/50 bg-card/80 p-4">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{c.label}</p>
          <p className={`mt-1 text-2xl font-semibold ${c.color ?? "text-foreground"}`}>{c.value}</p>
          {c.sub && <p className="mt-0.5 text-xs text-muted-foreground/60">{c.sub}</p>}
        </div>
      ))}
    </div>
  );
}
