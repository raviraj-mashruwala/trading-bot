"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

interface StrategyRow {
  strategy: string;
  total: number;
  wins: number;
  losses: number;
  total_pnl: number;
  avg_pnl: number;
  best_trade: number;
  worst_trade: number;
}

export function StrategyBreakdown() {
  const { data } = useQuery({
    queryKey: ["strategy-stats"],
    queryFn: api.getStrategyStats,
  });

  const rows = (data ?? []) as StrategyRow[];
  if (rows.length === 0) return null;

  return (
    <div className="space-y-2">
      <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
        Strategy Performance
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-muted-foreground/60 border-b border-border/20">
              <th className="text-left py-1.5 pr-4">Strategy</th>
              <th className="text-right py-1.5 px-2">Trades</th>
              <th className="text-right py-1.5 px-2">Win%</th>
              <th className="text-right py-1.5 px-2">Total P&L</th>
              <th className="text-right py-1.5 px-2">Avg P&L</th>
              <th className="text-right py-1.5 px-2">Best</th>
              <th className="text-right py-1.5 px-2">Worst</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const winRate = r.total > 0 ? (r.wins / r.total) * 100 : 0;
              const profitable = r.total_pnl > 0;
              return (
                <tr
                  key={r.strategy}
                  className={`border-b border-border/10 ${
                    profitable ? "bg-[#2da44e]/5" : "bg-[#f85149]/5"
                  }`}
                >
                  <td className="py-1.5 pr-4 font-medium text-foreground/90">
                    {r.strategy.replace("_", " ")}
                  </td>
                  <td className="text-right py-1.5 px-2 text-muted-foreground">
                    {r.total}
                  </td>
                  <td className="text-right py-1.5 px-2">
                    <span
                      className={
                        winRate >= 50
                          ? "text-[#2da44e]"
                          : winRate >= 40
                          ? "text-[#d4a015]"
                          : "text-[#f85149]"
                      }
                    >
                      {winRate.toFixed(0)}%
                    </span>
                  </td>
                  <td
                    className={`text-right py-1.5 px-2 font-mono ${
                      profitable ? "text-[#2da44e]" : "text-[#f85149]"
                    }`}
                  >
                    {r.total_pnl >= 0 ? "+" : ""}
                    {r.total_pnl.toFixed(0)}
                  </td>
                  <td
                    className={`text-right py-1.5 px-2 font-mono ${
                      r.avg_pnl >= 0 ? "text-[#2da44e]" : "text-[#f85149]"
                    }`}
                  >
                    {r.avg_pnl >= 0 ? "+" : ""}
                    {r.avg_pnl.toFixed(0)}
                  </td>
                  <td className="text-right py-1.5 px-2 font-mono text-[#2da44e]">
                    +{r.best_trade.toFixed(0)}
                  </td>
                  <td className="text-right py-1.5 px-2 font-mono text-[#f85149]">
                    {r.worst_trade.toFixed(0)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
