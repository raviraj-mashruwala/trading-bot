"use client";

import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
      <Card>
        <CardHeader><CardTitle className="text-sm">Daily P&L</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground">No trades yet</CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">Daily P&L</CardTitle></CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Bar dataKey="pnl">
              {data.map((entry, i) => (
                <Cell key={i} fill={entry.pnl >= 0 ? "#16a34a" : "#dc2626"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
