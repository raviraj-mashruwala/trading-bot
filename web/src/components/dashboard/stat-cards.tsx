import type { TradeStats } from "@/types";

function formatCurrency(n: number): string {
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString("en-IN", { maximumFractionDigits: 0 });
  return n < 0 ? `-₹${formatted}` : `₹${formatted}`;
}

export function StatCards({ stats }: { stats: TradeStats }) {
  const cards = [
    { label: "Total P&L", value: formatCurrency(stats.total_pnl), color: stats.total_pnl >= 0 ? "text-[#2da44e]" : "text-[#f85149]", sub: `Avg ${formatCurrency(stats.avg_pnl)}/trade` },
    { label: "Win rate", value: `${Math.round(stats.win_rate * 100)}%`, color: stats.win_rate >= 0.5 ? "text-[#2da44e]" : "text-[#f85149]", sub: `${stats.trade_count} trades` },
    { label: "Trades", value: String(stats.trade_count), color: "text-[#e6edf3]", sub: `Best ${formatCurrency(stats.best_day)}` },
    { label: "Max drawdown", value: formatCurrency(stats.max_drawdown), color: "text-[#f85149]", sub: `Worst ${formatCurrency(stats.worst_day)}` },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map((c) => (
        <div key={c.label} className="py-3">
          <p className="text-xs text-muted-foreground">{c.label}</p>
          <p className={`mt-0.5 font-mono-nums text-xl font-semibold ${c.color}`}>{c.value}</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground/60">{c.sub}</p>
        </div>
      ))}
    </div>
  );
}
