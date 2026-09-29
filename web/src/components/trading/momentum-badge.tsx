import type { MomentumData } from "@/types";

export function MomentumBadge({ momentum }: { momentum: MomentumData | undefined }) {
  if (!momentum) return null;

  const m5 = momentum["5m"];
  const arrow = m5 > 0 ? "↑" : m5 < 0 ? "↓" : "→";
  const color =
    m5 > 30
      ? "text-[#2da44e]"
      : m5 < -30
        ? "text-[#f85149]"
        : "text-muted-foreground";

  return (
    <span className={`inline-flex items-center gap-1 text-xs font-mono ${color}`}>
      <span>
        {m5 > 0 ? "+" : ""}
        {m5.toFixed(0)}
        {arrow}
      </span>
      {momentum.volume_ratio > 1.5 && (
        <span
          className="text-[10px] text-[#d4a015]"
          title={`Volume ${momentum.volume_ratio.toFixed(1)}x`}
        >
          VOL
        </span>
      )}
      {momentum.trend_alignment && (
        <span className="h-1.5 w-1.5 rounded-full bg-[#2da44e]" title="Trend aligned" />
      )}
    </span>
  );
}
