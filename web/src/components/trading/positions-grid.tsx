import { PositionCard } from "./position-card";
import type { ExecutionPosition } from "@/types";

export function PositionsGrid({ positions }: { positions: ExecutionPosition[] }) {
  if (positions.length === 0) {
    return <div className="py-8 text-center text-sm text-muted-foreground">No open positions</div>;
  }

  return (
    <div>
      {positions.map((p) => (
        <PositionCard key={p.symbol} position={p} />
      ))}
    </div>
  );
}
