"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { DayGroup } from "@/components/history/day-group";
import { StatCards } from "@/components/dashboard/stat-cards";
import { Button } from "@/components/ui/button";
import type { Trade } from "@/types";

const PERIODS = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "All", days: 9999 },
];

function groupByDate(trades: Trade[]): Map<string, { trades: Trade[]; pnl: number }> {
  const groups = new Map<string, { trades: Trade[]; pnl: number }>();
  for (const t of trades) {
    const existing = groups.get(t.trade_date) ?? { trades: [], pnl: 0 };
    existing.trades.push(t);
    existing.pnl += t.pnl;
    groups.set(t.trade_date, existing);
  }
  return new Map([...groups.entries()].sort(([a], [b]) => b.localeCompare(a)));
}

export default function HistoryPage() {
  const [days, setDays] = useState(30);
  const { data: stats } = useQuery({ queryKey: ["trade-stats", days], queryFn: () => api.getTradeStats(days) });
  const { data: trades } = useQuery({ queryKey: ["trades", days], queryFn: () => api.getTrades(days) });

  const grouped = groupByDate(trades ?? []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Trade History</h1>
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <Button
              key={p.label}
              size="sm"
              variant={days === p.days ? "default" : "outline"}
              onClick={() => setDays(p.days)}
            >
              {p.label}
            </Button>
          ))}
        </div>
      </div>

      {stats && <StatCards stats={stats} />}

      <div className="flex flex-col gap-2">
        {grouped.size === 0 ? (
          <div className="py-8 text-center text-muted-foreground">No trades in this period</div>
        ) : (
          [...grouped.entries()].map(([date, { trades: dayTrades, pnl }]) => (
            <DayGroup key={date} date={date} trades={dayTrades} dailyPnl={pnl} />
          ))
        )}
      </div>
    </div>
  );
}
