"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

interface SectorData {
  sector: string;
  avg_change_pct: number;
  stock_count: number;
}

function intensity(pct: number): string {
  const abs = Math.min(Math.abs(pct), 3);
  const alpha = Math.round((abs / 3) * 40 + 10);
  if (pct > 0) return `rgba(45, 164, 78, ${alpha / 100})`;
  if (pct < 0) return `rgba(248, 81, 73, ${alpha / 100})`;
  return "rgba(255, 255, 255, 0.03)";
}

export function SectorHeatmap() {
  const { data } = useQuery({
    queryKey: ["sector-heatmap"],
    queryFn: api.getSectorHeatmap,
    refetchInterval: 60_000,
  });

  const sectors = (data ?? []) as SectorData[];
  if (sectors.length === 0) return null;

  return (
    <div className="space-y-2">
      <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
        Sector Heatmap
      </h3>
      <div className="grid grid-cols-5 gap-1.5">
        {sectors.map((s) => (
          <div
            key={s.sector}
            className="rounded-md px-2 py-2 text-center border border-border/10"
            style={{ backgroundColor: intensity(s.avg_change_pct) }}
          >
            <p className="text-[10px] text-muted-foreground truncate">{s.sector}</p>
            <p
              className={`text-sm font-mono font-semibold ${
                s.avg_change_pct > 0
                  ? "text-[#2da44e]"
                  : s.avg_change_pct < 0
                  ? "text-[#f85149]"
                  : "text-muted-foreground"
              }`}
            >
              {s.avg_change_pct >= 0 ? "+" : ""}
              {s.avg_change_pct.toFixed(1)}%
            </p>
            <p className="text-[9px] text-muted-foreground/40">{s.stock_count} stocks</p>
          </div>
        ))}
      </div>
    </div>
  );
}
