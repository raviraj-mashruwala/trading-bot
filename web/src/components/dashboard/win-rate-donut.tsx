"use client";

import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { Card, CardContent } from "@/components/ui/card";

export function WinRateDonut({ winRate, tradeCount }: { winRate: number; tradeCount: number }) {
  if (tradeCount === 0) {
    return (
      <Card className="border-border/50 bg-card/80">
        <CardContent className="p-4">
          <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Win Rate</div>
          <div className="mt-8 text-center text-sm text-muted-foreground/50">No trades yet</div>
        </CardContent>
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
    <Card className="border-border/50 bg-card/80">
      <CardContent className="p-4">
        <div className="mb-3 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Win Rate</div>
        <div className="flex items-center justify-center">
          <ResponsiveContainer width="100%" height={180}>
            <PieChart>
              <Pie data={data} cx="50%" cy="50%" innerRadius={50} outerRadius={72} dataKey="value" strokeWidth={0}>
                <Cell fill="#10b981" />
                <Cell fill="#ef4444" opacity={0.7} />
              </Pie>
              <Tooltip
                contentStyle={{ background: "#111827", border: "1px solid #1e293b", borderRadius: "8px", fontSize: 12 }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
