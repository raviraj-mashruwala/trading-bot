"use client";

import { useQuery } from "@tanstack/react-query";
import { useSearchParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { DayGroup } from "@/components/history/day-group";
import { StrategyBreakdown } from "@/components/history/strategy-breakdown";
import { PlanExecutionReport } from "@/components/history/plan-execution-report";
import { StatCards } from "@/components/dashboard/stat-cards";
import type { Trade } from "@/types";

const PERIODS = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "All", days: 9999 },
];

function downloadCsv(trades: Trade[]) {
  const headers = ["date", "symbol", "strategy", "direction", "qty", "entry", "exit", "pnl", "exit_reason", "mode"];
  const rows = trades.map((t) =>
    [t.trade_date, t.symbol, t.strategy, t.direction, t.quantity, t.entry_price, t.exit_price, t.pnl.toFixed(2), t.exit_reason, t.mode].join(",")
  );
  const csv = [headers.join(","), ...rows].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `trades-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

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
  const searchParams = useSearchParams();
  const router = useRouter();
  const days = Number(searchParams.get("days") ?? 30);
  const setDays = (d: number) => router.replace(`/history?days=${d}`);
  const { data: stats } = useQuery({ queryKey: ["trade-stats", days], queryFn: () => api.getTradeStats(days) });
  const { data: trades } = useQuery({ queryKey: ["trades", days], queryFn: () => api.getTrades(days) });

  const grouped = groupByDate(trades ?? []);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">History</h1>
        <div className="flex items-center gap-2">
        {(trades?.length ?? 0) > 0 && (
          <button
            onClick={() => downloadCsv(trades!)}
            className="rounded-md border border-border/50 px-2.5 py-1 text-xs text-muted-foreground hover:bg-card hover:text-foreground transition-colors"
          >
            Export CSV
          </button>
        )}
        <div className="flex gap-0.5 rounded-lg border border-[rgba(255,255,255,0.06)] bg-[#0c1018] p-0.5">
          {PERIODS.map((p) => (
            <button
              key={p.label}
              onClick={() => setDays(p.days)}
              className={`rounded-md px-3 py-1 text-xs font-medium transition-all ${
                days === p.days
                  ? "bg-[#d4a015]/20 text-[#d4a015]"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
        </div>
      </div>

      {stats && <StatCards stats={stats} />}

      <StrategyBreakdown />

      <div className="flex flex-col gap-1.5">
        {grouped.size === 0 ? (
          <div className="py-12 text-center text-sm text-muted-foreground/50">No trades in this period</div>
        ) : (
          [...grouped.entries()].map(([date, { trades: dayTrades, pnl }]) => (
            <DayGroup key={date} date={date} trades={dayTrades} dailyPnl={pnl} />
          ))
        )}
      </div>
    </div>
  );
}
