"use client";

import type { TradeScorecard } from "@/types";

function RBadge({ value }: { value: number }) {
  const color = value >= 1 ? "text-[#2da44e] bg-[#2da44e]/10" : value >= 0 ? "text-[#d4a015] bg-[#d4a015]/10" : "text-[#f85149] bg-[#f85149]/10";
  return <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${color}`}>{value.toFixed(2)}R</span>;
}

function BoolBadge({ value, trueLabel, falseLabel }: { value: boolean; trueLabel: string; falseLabel: string }) {
  return value
    ? <span className="text-xs text-[#2da44e]">{trueLabel}</span>
    : <span className="text-xs text-muted-foreground/50">{falseLabel}</span>;
}

export function ScorecardTable({ scorecards }: { scorecards: TradeScorecard[] }) {
  if (scorecards.length === 0) {
    return (
      <div className="rounded-lg border border-border/50 bg-card/80 p-8 text-center">
        <p className="text-sm text-muted-foreground/50">No scorecards for this date</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border/50 bg-card/80 overflow-hidden">
      <table className="w-full">
        <thead>
          <tr className="border-b border-border/50 text-[11px] font-medium text-muted-foreground/60">
            <th className="px-4 py-3 text-left">Symbol</th>
            <th className="px-3 py-3 text-left">Strategy</th>
            <th className="px-3 py-3 text-right">Pred Entry</th>
            <th className="px-3 py-3 text-right">Act Entry</th>
            <th className="px-3 py-3 text-right">Slip</th>
            <th className="px-3 py-3 text-right">PnL</th>
            <th className="px-3 py-3 text-center">R</th>
            <th className="px-3 py-3 text-center">Target</th>
            <th className="px-3 py-3 text-center">Inval</th>
            <th className="px-3 py-3 text-right">Conf</th>
            <th className="px-3 py-3 text-right">Confl</th>
            <th className="px-3 py-3 text-left">Exit</th>
          </tr>
        </thead>
        <tbody>
          {scorecards.map((sc) => (
            <tr key={sc.trade_id} className="border-b border-border/30 last:border-0 hover:bg-muted/20 transition-colors">
              <td className="px-4 py-3">
                <span className="text-sm font-medium text-foreground">{sc.symbol}</span>
                <span className={`ml-1.5 text-[10px] ${sc.direction === "long" ? "text-[#2da44e]" : "text-[#f85149]"}`}>
                  {sc.direction.toUpperCase()}
                </span>
              </td>
              <td className="px-3 py-3 text-xs text-muted-foreground">{sc.strategy}</td>
              <td className="px-3 py-3 text-right text-sm text-muted-foreground">₹{sc.predicted_entry.toFixed(1)}</td>
              <td className="px-3 py-3 text-right text-sm text-foreground">₹{sc.actual_entry.toFixed(1)}</td>
              <td className={`px-3 py-3 text-right text-xs ${Math.abs(sc.entry_slippage) > 2 ? "text-[#d4a015]" : "text-muted-foreground/50"}`}>
                {sc.entry_slippage >= 0 ? "+" : ""}{sc.entry_slippage.toFixed(1)}
              </td>
              <td className={`px-3 py-3 text-right text-sm font-medium ${sc.pnl >= 0 ? "text-[#2da44e]" : "text-[#f85149]"}`}>
                ₹{sc.pnl.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
              </td>
              <td className="px-3 py-3 text-center"><RBadge value={sc.r_multiple} /></td>
              <td className="px-3 py-3 text-center">
                <BoolBadge value={sc.hit_target} trueLabel="HIT" falseLabel="MISS" />
              </td>
              <td className="px-3 py-3 text-center">
                <BoolBadge value={sc.invalidation_fired} trueLabel="FIRED" falseLabel="-" />
              </td>
              <td className="px-3 py-3 text-right text-xs text-muted-foreground">{(sc.confidence * 100).toFixed(0)}%</td>
              <td className="px-3 py-3 text-right text-xs text-muted-foreground">{sc.confluence_count}</td>
              <td className="px-3 py-3 text-xs text-muted-foreground">{sc.exit_reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
