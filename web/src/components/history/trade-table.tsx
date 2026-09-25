import type { Trade } from "@/types";

function formatCurrency(n: number): string {
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  return n < 0 ? `-₹${formatted}` : `₹${formatted}`;
}

export function TradeTable({ trades }: { trades: Trade[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b text-left text-xs text-muted-foreground">
          <th className="py-2">Symbol</th>
          <th>Strategy</th>
          <th>Direction</th>
          <th className="text-right">Qty</th>
          <th className="text-right">Entry</th>
          <th className="text-right">Exit</th>
          <th className="text-right">P&L</th>
          <th>Exit Reason</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {trades.map((t, i) => (
          <tr key={i} className="border-b last:border-0">
            <td className="py-2 font-medium">{t.symbol}</td>
            <td>{t.strategy}</td>
            <td>{t.direction}</td>
            <td className="text-right">{t.quantity}</td>
            <td className="text-right">₹{t.entry_price.toFixed(2)}</td>
            <td className="text-right">₹{t.exit_price.toFixed(2)}</td>
            <td className={`text-right font-medium ${t.pnl >= 0 ? "text-green-600" : "text-red-600"}`}>
              {formatCurrency(t.pnl)}
            </td>
            <td>{t.exit_reason}</td>
            <td>{t.status}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
