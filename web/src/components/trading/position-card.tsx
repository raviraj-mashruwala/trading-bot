import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { ExecutionPosition } from "@/types";

function fmt(n: number): string {
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  return n < 0 ? `-₹${formatted}` : `₹${formatted}`;
}

export function PositionCard({ position: p }: { position: ExecutionPosition }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between py-3">
        <CardTitle className="text-sm font-medium">{p.symbol}</CardTitle>
        <Badge variant={p.direction === "long" ? "default" : "destructive"}>
          {p.direction.toUpperCase()} x{p.quantity}
        </Badge>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-2 pt-0 text-sm">
        <div>Entry: {fmt(p.entry_price)}</div>
        <div>LTP: {fmt(p.last_price)}</div>
        <div>Stop: {fmt(p.current_stop)}</div>
        <div>{p.target_1_booked ? "T1: ✅" : "T1: ❌"}</div>
        <div
          data-testid="unrealised-pnl"
          className={`font-semibold ${p.unrealised_pnl >= 0 ? "text-green-600" : "text-red-600"}`}
        >
          Unreal: {fmt(p.unrealised_pnl)}
        </div>
        <div className="text-muted-foreground">Real: {fmt(p.pnl)}</div>
      </CardContent>
    </Card>
  );
}
