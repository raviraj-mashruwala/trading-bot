import { PositionCard } from "./position-card";
import type { ExecutionPosition } from "@/types";

export function PositionsGrid({ positions }: { positions: ExecutionPosition[] }) {
  if (positions.length === 0) {
    return <div className="py-8 text-center text-muted-foreground">No open positions</div>;
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {positions.map((p) => (
        <PositionCard key={p.symbol} position={p} />
      ))}
    </div>
  );
}
