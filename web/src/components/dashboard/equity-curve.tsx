"use client";

import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { Card, CardContent } from "@/components/ui/card";
import type { Trade } from "@/types";

function computeEquityCurve(trades: Trade[]): Array<{ date: string; cumulative: number }> {
  const dailyPnl = new Map<string, number>();
  for (const t of trades) {
    dailyPnl.set(t.trade_date, (dailyPnl.get(t.trade_date) ?? 0) + t.pnl);
  }
  const sorted = [...dailyPnl.entries()].sort(([a], [b]) => a.localeCompare(b));
  let cumulative = 0;
  return sorted.map(([date, pnl]) => {
    cumulative += pnl;
    return { date, cumulative: Math.round(cumulative) };
  });
}

export function EquityCurve({ trades }: { trades: Trade[] }) {
  const data = computeEquityCurve(trades);

  if (data.length === 0) {
    return (
      <Card className="border-border/50 bg-card/80">
        <CardContent className="p-4">
          <div className="text-[11px] font-medium text-muted-foreground">Equity Curve</div>
          <div className="mt-8 text-center text-sm text-muted-foreground/50">No trades yet</div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-border/50 bg-card/80">
      <CardContent className="p-4">
        <div className="mb-3 text-[11px] font-medium text-muted-foreground">Equity Curve</div>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={data}>
            <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#5a6a7f" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: "#5a6a7f" }} axisLine={false} tickLine={false} />
            <Tooltip
              contentStyle={{ background: "#0f1419", border: "1px solid #1e293b", borderRadius: "8px", fontSize: 12 }}
              labelStyle={{ color: "#5a6a7f" }}
            />
            <Line type="monotone" dataKey="cumulative" stroke="#d4a015" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
