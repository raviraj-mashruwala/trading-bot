import Link from "next/link";
import type { Trade } from "@/types";

function fmt(n: number): string {
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  return n < 0 ? `-₹${formatted}` : `₹${formatted}`;
}

export function TradeTable({ trades }: { trades: Trade[] }) {
  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className="border-b border-border/30 text-left text-[10px] uppercase tracking-wider text-muted-foreground/60">
          <th className="py-2 font-medium">Symbol</th>
          <th className="font-medium">Strategy</th>
          <th className="font-medium">Dir</th>
          <th className="text-right font-medium">Qty</th>
          <th className="text-right font-medium">Entry</th>
          <th className="text-right font-medium">Exit</th>
          <th className="text-right font-medium">P&L</th>
          <th className="font-medium">Reason</th>
        </tr>
      </thead>
      <tbody>
        {trades.map((t, i) => (
          <tr key={i} className="border-b border-border/20 last:border-0 transition-colors hover:bg-muted/20 cursor-pointer">
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
          </tr>
        ))}
      </tbody>
    </table>
  );
}
