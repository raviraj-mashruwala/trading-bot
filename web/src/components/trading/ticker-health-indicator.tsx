import type { TickerHealth } from "@/types";

const statusColor: Record<string, string> = {
  healthy: "bg-[#2da44e]",
  reconnecting: "bg-[#d4a015] animate-pulse",
  degraded: "bg-[#f85149]",
  unknown: "bg-muted-foreground/30",
};

const statusLabel: Record<string, string> = {
  healthy: "Live",
  reconnecting: "Reconnecting...",
  degraded: "Degraded (REST only)",
  unknown: "Unknown",
};

export function TickerHealthIndicator({ health }: { health: TickerHealth | undefined }) {
  if (!health) return null;

  const color = statusColor[health.status] ?? statusColor.unknown;
  const label = statusLabel[health.status] ?? health.status;

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className={`inline-block h-2.5 w-2.5 rounded-full ${color}`} />
      <span className="text-muted-foreground">{label}</span>
      {health.reconnect_count > 0 && (
        <span className="text-xs text-muted-foreground/60">
          ({health.reconnect_count} reconnects)
        </span>
      )}
      {health.gap_seconds_today > 60 && (
        <span className="text-xs text-[#f85149]/70">
          {Math.round(health.gap_seconds_today / 60)}m gap
        </span>
      )}
    </div>
  );
}
