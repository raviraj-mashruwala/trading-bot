import { MomentumBadge } from "@/components/trading/momentum-badge";
import type { ExecutionPosition } from "@/types";

function fmt(n: number): string {
  return n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function progressPct(entry: number, target: number, current: number): number {
  const range = Math.abs(target - entry);
  if (range === 0) return 0;
  const distance = Math.abs(current - entry);
  return Math.min(100, Math.max(0, (distance / range) * 100));
}

export function PositionCard({ position: p }: { position: ExecutionPosition }) {
  const isLong = p.direction === "long";
  const isProfit = p.unrealised_pnl >= 0;
  const pct = progressPct(p.entry_price, p.entry_price + (p.entry_price - p.current_stop) * 2, p.last_price);

  return (
    <div className="py-3 border-b border-[rgba(255,255,255,0.04)] last:border-0">
      {/* Header row */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-[#e6edf3]">{p.symbol}</span>
          <span className={`text-[11px] font-medium ${isLong ? "text-[#2da44e]" : "text-[#f85149]"}`}>
            {p.direction.toUpperCase()} x{p.quantity}
          </span>
          <MomentumBadge momentum={p.momentum} />
          {p.phase === "waiting" && (
            <span className="text-[10px] text-[#d4a015]">waiting</span>
          )}
        </div>
        <span
          className={`font-mono-nums text-base font-semibold ${isProfit ? "text-[#2da44e]" : "text-[#f85149]"}`}
        >
          {isProfit ? "+" : "-"}₹{fmt(Math.abs(p.unrealised_pnl))}
        </span>
      </div>

      {/* Progress bar: SL ─── entry ─── current ─── T1 */}
      <div className="relative h-1.5 w-full rounded-full bg-[rgba(255,255,255,0.04)] mb-2">
        <div
          className={`absolute top-0 left-0 h-full rounded-full transition-all duration-500 ${isProfit ? "bg-[#2da44e]" : "bg-[#f85149]"}`}
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Price markers */}
      <div className="flex items-center justify-between text-[11px] font-mono-nums">
        <span className="text-[#f85149]/60">SL {fmt(p.current_stop)}</span>
        <span className="text-muted-foreground">@ {fmt(p.entry_price)}</span>
        <span className="text-[#e6edf3]">{fmt(p.last_price)}</span>
        <span className={`${p.target_1_booked ? "text-[#2da44e]" : "text-muted-foreground"}`}>
          T1 {p.target_1_booked ? "booked" : "pending"}
        </span>
      </div>

      {p.last_decision?.reason && (p.phase === "vetoed" || p.phase === "waiting") && (
        <p className="mt-1.5 text-[10px] text-muted-foreground/60 truncate">{p.last_decision.reason}</p>
      )}
    </div>
  );
}
