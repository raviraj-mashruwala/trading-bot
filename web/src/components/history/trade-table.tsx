"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Trade } from "@/types";

function fmt(n: number): string {
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  return n < 0 ? `-₹${formatted}` : `₹${formatted}`;
}

function InlineNotes({ tradeId, initial }: { tradeId: number; initial: string }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(initial || "");
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (notes: string) => api.updateTradeNotes(tradeId, notes),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["trades"] }),
  });

  if (!editing) {
    return (
      <button
        onClick={() => setEditing(true)}
        className="text-left text-xs text-muted-foreground/50 hover:text-muted-foreground transition-colors w-full min-h-[20px]"
        title="Click to add notes"
      >
        {value || "＋ note"}
      </button>
    );
  }

  return (
    <textarea
      autoFocus
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={() => {
        setEditing(false);
        if (value !== initial) mutation.mutate(value);
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          setValue(initial || "");
          setEditing(false);
        }
      }}
      className="w-full bg-card/80 border border-border/50 rounded px-2 py-1 text-xs text-foreground/80 outline-none focus:ring-1 focus:ring-[#d4a015]/50 resize-none"
      rows={2}
      placeholder="Add a note about this trade..."
    />
  );
}

export function TradeTable({ trades }: { trades: Trade[] }) {
  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className="border-b border-border/30 text-left text-[10px] text-muted-foreground/60">
          <th className="py-2 font-medium">Symbol</th>
          <th className="font-medium">Strategy</th>
          <th className="font-medium">Dir</th>
          <th className="text-right font-medium">Qty</th>
          <th className="text-right font-medium">Entry</th>
          <th className="text-right font-medium">Exit</th>
          <th className="text-right font-medium">P&L</th>
          <th className="font-medium">Reason</th>
          <th className="font-medium">Notes</th>
        </tr>
      </thead>
      <tbody>
        {trades.map((t) => (
          <tr key={t.id} className="border-b border-border/20 last:border-0 transition-colors hover:bg-muted/20">
            <td className="py-2 font-medium text-foreground/90">
              <Link href={`/history/trade?symbol=${t.symbol}&date=${t.trade_date}`} className="hover:text-[#d4a015]">
                {t.symbol}
              </Link>
            </td>
            <td className="text-muted-foreground">{t.strategy}</td>
            <td>
              <span className={`text-[11px] font-medium uppercase ${t.direction === "long" ? "text-[#2da44e]" : "text-[#f85149]"}`}>
                {t.direction}
              </span>
            </td>
            <td className="text-right font-mono-nums">{t.quantity}</td>
            <td className="text-right font-mono-nums">₹{t.entry_price.toFixed(2)}</td>
            <td className="text-right font-mono-nums">₹{t.exit_price.toFixed(2)}</td>
            <td className={`text-right font-mono-nums font-medium ${t.pnl >= 0 ? "text-[#2da44e]" : "text-[#f85149]"}`}>
              {fmt(t.pnl)}
            </td>
            <td className="text-muted-foreground">{t.exit_reason}</td>
            <td className="w-40">
              <InlineNotes tradeId={t.id} initial={t.notes ?? ""} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
