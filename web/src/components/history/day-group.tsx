"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { TradeTable } from "./trade-table";
import type { Trade } from "@/types";

function fmt(n: number): string {
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString("en-IN", { maximumFractionDigits: 0 });
  return n < 0 ? `-₹${formatted}` : `₹${formatted}`;
}

interface Props {
  date: string;
  trades: Trade[];
  dailyPnl: number;
}

export function DayGroup({ date, trades, dailyPnl }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <Card className="border-border/50 bg-card/80 cursor-pointer transition-all hover:bg-card/90" onClick={() => setOpen(!open)}>
      <CardHeader className="flex flex-row items-center justify-between py-3 px-4">
        <div className="flex items-center gap-4">
          <span className="font-mono-nums text-sm font-medium text-foreground/90">{date}</span>
          <span className="text-[11px] text-muted-foreground/60">
            {trades.length} trade{trades.length !== 1 ? "s" : ""}
          </span>
        </div>
        <span className={`font-mono-nums text-sm font-semibold ${dailyPnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
          {fmt(dailyPnl)}
        </span>
      </CardHeader>
      {open && trades.length > 0 && (
        <CardContent className="px-4 pb-4 pt-0" onClick={(e) => e.stopPropagation()}>
          <TradeTable trades={trades} />
        </CardContent>
      )}
    </Card>
  );
}
