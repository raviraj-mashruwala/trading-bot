"use client";

import type { PerformanceStatsData } from "@/types";

function Bar({ label, value, maxValue }: { label: string; value: number; maxValue: number }) {
  const width = maxValue > 0 ? Math.max(4, (value / maxValue) * 100) : 0;
  const color = value >= 0.6 ? "bg-[#2da44e]" : value >= 0.45 ? "bg-[#d4a015]" : "bg-[#f85149]";

  return (
    <div className="flex items-center gap-3">
      <span className="w-16 text-right text-xs text-muted-foreground">{label}</span>
      <div className="flex-1 h-6 rounded bg-muted/30 relative overflow-hidden">
        <div className={`h-full rounded ${color} transition-all duration-500`} style={{ width: `${width}%` }} />
      </div>
      <span className="w-12 text-right text-sm font-medium text-foreground">{(value * 100).toFixed(0)}%</span>
    </div>
  );
}

export function ConfluenceChart({ stats }: { stats: PerformanceStatsData }) {
  const buckets = stats.confluence_buckets;
  const cal = stats.confidence_calibration;

  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="rounded-lg border border-border/50 bg-card/80 p-4">
        <h3 className="mb-4 text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Win Rate by Confluence
        </h3>
        <div className="space-y-2">
          <Bar label="Low (1-2)" value={buckets.low ?? 0} maxValue={1} />
          <Bar label="Mid (3)" value={buckets.mid ?? 0} maxValue={1} />
          <Bar label="High (4+)" value={buckets.high ?? 0} maxValue={1} />
        </div>
      </div>

      <div className="rounded-lg border border-border/50 bg-card/80 p-4">
        <h3 className="mb-4 text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Confidence Calibration
        </h3>
        <div className="space-y-2">
          {Object.entries(cal).length === 0 ? (
            <p className="text-sm text-muted-foreground/50">No data yet</p>
          ) : (
            Object.entries(cal).map(([bucket, winRate]) => (
              <Bar key={bucket} label={bucket} value={winRate} maxValue={1} />
            ))
          )}
        </div>
      </div>
    </div>
  );
}
