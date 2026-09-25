"use client";

import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function WinRateDonut({ winRate, tradeCount }: { winRate: number; tradeCount: number }) {
  if (tradeCount === 0) {
    return (
      <Card>
        <CardHeader><CardTitle className="text-sm">Win Rate</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground">No trades yet</CardContent>
      </Card>
    );
  }

  const wins = Math.round(winRate * tradeCount);
  const losses = tradeCount - wins;
  const data = [
    { name: "Wins", value: wins },
    { name: "Losses", value: losses },
  ];

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">Win Rate</CardTitle></CardHeader>
      <CardContent className="flex items-center justify-center">
        <ResponsiveContainer width="100%" height={200}>
          <PieChart>
            <Pie data={data} cx="50%" cy="50%" innerRadius={50} outerRadius={80} dataKey="value" label>
              <Cell fill="#16a34a" />
              <Cell fill="#dc2626" />
            </Pie>
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
