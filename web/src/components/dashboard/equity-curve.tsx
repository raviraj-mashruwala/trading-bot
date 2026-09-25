"use client";

import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
      <Card>
        <CardHeader><CardTitle className="text-sm">Equity Curve</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground">No trades yet</CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">Equity Curve</CardTitle></CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Line type="monotone" dataKey="cumulative" stroke="#16a34a" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
