"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { TradeTable } from "./trade-table";
import type { Trade } from "@/types";

function formatCurrency(n: number): string {
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
    <Card className="cursor-pointer" onClick={() => setOpen(!open)}>
      <CardHeader className="flex flex-row items-center justify-between py-3">
        <div className="flex items-center gap-3">
          <span className="font-medium">{date}</span>
          <span className="text-sm text-muted-foreground">
            {trades.length} trade{trades.length !== 1 ? "s" : ""}
          </span>
        </div>
        <span className={`font-semibold ${dailyPnl >= 0 ? "text-green-600" : "text-red-600"}`}>
          {formatCurrency(dailyPnl)}
        </span>
      </CardHeader>
      {open && trades.length > 0 && (
        <CardContent className="pt-0" onClick={(e) => e.stopPropagation()}>
          <TradeTable trades={trades} />
        </CardContent>
      )}
    </Card>
  );
}
