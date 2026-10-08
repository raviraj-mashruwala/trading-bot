import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MomentumBadge } from "@/components/trading/momentum-badge";
import type { ExecutionPosition } from "@/types";

function fmt(n: number): string {
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  return n < 0 ? `-₹${formatted}` : `₹${formatted}`;
}

export function PositionCard({ position: p }: { position: ExecutionPosition }) {
  const trailed = p.original_stop != null && p.original_stop !== p.current_stop;

  return (
    <Card className="border-border/50 bg-card/80">
      <CardHeader className="flex flex-row items-center justify-between pb-2 pt-4 px-4">
        <div className="flex items-center gap-2">
          <CardTitle className="text-sm font-semibold">{p.symbol}</CardTitle>
          <MomentumBadge momentum={p.momentum} />
        </div>
        <div className="flex items-center gap-1.5">
          {p.phase === "vetoed" && (
            <span className="rounded bg-[#f85149]/15 px-1.5 py-0.5 text-[10px] font-semibold text-[#f85149]">
              Vetoed
            </span>
          )}
          {p.phase === "waiting" && (
            <span className="rounded bg-[#d4a015]/15 px-1.5 py-0.5 text-[10px] font-semibold text-[#d4a015]">
              Waiting
            </span>
          )}
          <span className={`rounded px-2 py-0.5 text-[11px] font-semibold uppercase ${p.direction === "long" ? "bg-[#2da44e]/15 text-[#2da44e]" : "bg-[#f85149]/15 text-[#f85149]"}`}>
            {p.direction} x{p.quantity}
          </span>
        </div>
      </CardHeader>
      <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-1.5 px-4 pb-4 pt-0 text-[13px]">
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
          <span className="font-mono-nums">
            {trailed && (
              <span className="text-muted-foreground/50 line-through mr-1">{fmt(p.original_stop!)}</span>
            )}
            <span className="text-[#f85149]/80">{fmt(p.current_stop)}</span>
            {trailed && (
              <span className="ml-1 text-[10px] text-blue-500">trailed</span>
            )}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">T1</span>
          <span className="text-xs">{p.target_1_booked ? "Booked" : "Pending"}</span>
        </div>
        {p.last_decision?.reason && (p.phase === "vetoed" || p.phase === "waiting") && (
          <div className="col-span-2 text-[11px] text-muted-foreground/70 italic truncate">
            {p.last_decision.reason}
          </div>
        )}
        <div className="col-span-2 mt-1 flex items-center justify-between rounded-md bg-muted/50 px-3 py-1.5">
          <span className="text-[11px] text-muted-foreground">Unrealised</span>
          <span
            data-testid="unrealised-pnl"
            className={`font-mono-nums text-base font-bold ${p.unrealised_pnl >= 0 ? "text-[#2da44e]" : "text-[#f85149]"}`}
          >
            {fmt(p.unrealised_pnl)}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
