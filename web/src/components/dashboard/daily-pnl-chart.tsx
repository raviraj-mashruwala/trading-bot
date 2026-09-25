"use client";

import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from "recharts";
import { Card, CardContent } from "@/components/ui/card";
import type { Trade } from "@/types";

function computeDailyPnl(trades: Trade[]): Array<{ date: string; pnl: number }> {
  const daily = new Map<string, number>();
  for (const t of trades) {
    daily.set(t.trade_date, (daily.get(t.trade_date) ?? 0) + t.pnl);
  }
  return [...daily.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([date, pnl]) => ({ date, pnl: Math.round(pnl) }));
}

export function DailyPnlChart({ trades }: { trades: Trade[] }) {
  const data = computeDailyPnl(trades);

  if (data.length === 0) {
    return (
      <Card className="border-border/50 bg-card/80">
        <CardContent className="p-4">
          <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Daily P&L</div>
          <div className="mt-8 text-center text-sm text-muted-foreground/50">No trades yet</div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-border/50 bg-card/80">
      <CardContent className="p-4">
        <div className="mb-3 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Daily P&L</div>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data}>
            <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#64748b" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: "#64748b" }} axisLine={false} tickLine={false} />
            <Tooltip
              contentStyle={{ background: "#111827", border: "1px solid #1e293b", borderRadius: "8px", fontSize: 12 }}
              labelStyle={{ color: "#64748b" }}
            />
            <Bar dataKey="pnl" radius={[3, 3, 0, 0]}>
              {data.map((entry, i) => (
                <Cell key={i} fill={entry.pnl >= 0 ? "#10b981" : "#ef4444"} opacity={0.85} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
