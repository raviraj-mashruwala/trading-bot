import { Card, CardContent } from "@/components/ui/card";
import type { TradeStats } from "@/types";

function formatCurrency(n: number): string {
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString("en-IN", { maximumFractionDigits: 0 });
  return n < 0 ? `-₹${formatted}` : `₹${formatted}`;
}

export function StatCards({ stats }: { stats: TradeStats }) {
  const cards = [
    { title: "Total P&L", value: formatCurrency(stats.total_pnl), color: stats.total_pnl >= 0 ? "text-[#2da44e]" : "text-[#f85149]", sub: `Avg ${formatCurrency(stats.avg_pnl)}/trade` },
    { title: "Win Rate", value: `${Math.round(stats.win_rate * 100)}%`, color: stats.win_rate >= 0.5 ? "text-[#2da44e]" : "text-[#f85149]", sub: `${stats.trade_count} trades` },
    { title: "Trades", value: String(stats.trade_count), color: "text-foreground", sub: `Best day ${formatCurrency(stats.best_day)}` },
    { title: "Max Drawdown", value: formatCurrency(stats.max_drawdown), color: "text-[#f85149]", sub: `Worst day ${formatCurrency(stats.worst_day)}` },
  ];

  return (
    <div className="grid grid-cols-4 gap-3">
      {cards.map((c) => (
        <Card key={c.title} className="border-border/50 bg-card/80">
          <CardContent className="p-4">
            <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{c.title}</div>
            <div className={`mt-1 font-mono-nums text-2xl font-semibold ${c.color}`}>{c.value}</div>
            <div className="mt-1 text-[11px] text-muted-foreground/70">{c.sub}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
