import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { TradeStats } from "@/types";

function formatCurrency(n: number): string {
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString("en-IN", { maximumFractionDigits: 0 });
  return n < 0 ? `-₹${formatted}` : `₹${formatted}`;
}

export function StatCards({ stats }: { stats: TradeStats }) {
  const cards = [
    { title: "Total P&L", value: formatCurrency(stats.total_pnl), color: stats.total_pnl >= 0 ? "text-green-600" : "text-red-600" },
    { title: "Win Rate", value: `${Math.round(stats.win_rate * 100)}%`, color: stats.win_rate >= 0.5 ? "text-green-600" : "text-red-600" },
    { title: "Trades", value: String(stats.trade_count), color: "" },
    { title: "Max Drawdown", value: formatCurrency(stats.max_drawdown), color: "text-red-600" },
  ];

  return (
    <div className="grid grid-cols-4 gap-4">
      {cards.map((c) => (
        <Card key={c.title}>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">{c.title}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${c.color}`}>{c.value}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
