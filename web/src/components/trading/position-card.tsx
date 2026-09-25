import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ExecutionPosition } from "@/types";

function fmt(n: number): string {
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  return n < 0 ? `-₹${formatted}` : `₹${formatted}`;
}

export function PositionCard({ position: p }: { position: ExecutionPosition }) {
  return (
    <Card className="border-border/50 bg-card/80">
      <CardHeader className="flex flex-row items-center justify-between pb-2 pt-4 px-4">
        <CardTitle className="text-sm font-semibold">{p.symbol}</CardTitle>
        <span className={`rounded px-2 py-0.5 text-[11px] font-semibold uppercase ${p.direction === "long" ? "bg-emerald-500/15 text-emerald-400" : "bg-red-500/15 text-red-400"}`}>
          {p.direction} x{p.quantity}
        </span>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-x-4 gap-y-1.5 px-4 pb-4 pt-0 text-[13px]">
        <div className="flex justify-between">
          <span className="text-muted-foreground">Entry</span>
          <span className="font-mono-nums">{fmt(p.entry_price)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">LTP</span>
          <span className="font-mono-nums font-medium">{fmt(p.last_price)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Stop</span>
          <span className="font-mono-nums text-red-400/80">{fmt(p.current_stop)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">T1</span>
          <span>{p.target_1_booked ? "✅ Booked" : "❌ Pending"}</span>
        </div>
        <div className="col-span-2 mt-1 flex items-center justify-between rounded-md bg-muted/50 px-3 py-1.5">
          <span className="text-[11px] text-muted-foreground">Unrealised</span>
          <span
            data-testid="unrealised-pnl"
            className={`font-mono-nums text-base font-bold ${p.unrealised_pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}
          >
            {fmt(p.unrealised_pnl)}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
