"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";

const STATUS_CONFIG: Record<string, { dot: string; label: string; color: string }> = {
  open: { dot: "bg-[#2da44e]", label: "Market Open", color: "text-[#2da44e]" },
  pre_market: { dot: "bg-[#d4a015] animate-pulse", label: "Pre-Market", color: "text-[#d4a015]" },
  post_market: { dot: "bg-[#d4a015]", label: "Post-Market", color: "text-[#d4a015]" },
  closed: { dot: "bg-[#f85149]", label: "Closed", color: "text-[#f85149]" },
  holiday: { dot: "bg-[#d4a015]", label: "Holiday", color: "text-[#d4a015]" },
};

function formatSessionTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffMs = d.getTime() - now.getTime();

  if (diffMs < 0) return "Now";

  const diffH = Math.floor(diffMs / 3_600_000);
  const diffM = Math.floor((diffMs % 3_600_000) / 60_000);

  const dateStr = d.toLocaleDateString("en-IN", { weekday: "short", month: "short", day: "numeric" });
  const timeStr = d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });

  if (diffH < 24) {
    const parts: string[] = [];
    if (diffH > 0) parts.push(`${diffH}h`);
    parts.push(`${diffM}m`);
    return `${dateStr} ${timeStr} (${parts.join(" ")})`;
  }

  return `${dateStr} ${timeStr}`;
}

export function MarketStatus() {
  const queryClient = useQueryClient();
  const [showHolidays, setShowHolidays] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["market-calendar"],
    queryFn: api.getMarketCalendar,
    refetchInterval: 60_000,
  });

  if (isLoading || !data) {
    return (
      <Card className="border-border/50 bg-card/80">
        <CardContent className="flex items-center gap-2 px-4 py-3">
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-[#d4a015] border-t-transparent" />
          <span className="text-xs text-muted-foreground">Loading market status…</span>
        </CardContent>
      </Card>
    );
  }

  const cfg = STATUS_CONFIG[data.status] ?? STATUS_CONFIG.closed;

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await api.refreshMarketCalendar();
      queryClient.invalidateQueries({ queryKey: ["market-calendar"] });
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <Card className="border-border/50 bg-card/80">
      <CardContent className="px-4 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            {/* Status badge */}
            <div className="flex items-center gap-2">
              <span className={`inline-flex h-2 w-2 rounded-full ${cfg.dot}`} />
              <span className={`text-sm font-medium ${cfg.color}`}>
                {data.status === "holiday" && data.holiday_name
                  ? `Holiday: ${data.holiday_name}`
                  : cfg.label}
              </span>
            </div>

            {/* Next session */}
            {data.status !== "open" && (
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-muted-foreground/60">Next</span>
                <span className="font-mono-nums text-xs text-foreground/80">
                  {formatSessionTime(data.next_session)}
                </span>
              </div>
            )}

            {/* Upcoming holidays toggle */}
            {data.holidays.length > 0 && (
              <button
                onClick={() => setShowHolidays(!showHolidays)}
                className="flex items-center gap-1 text-[10px] text-muted-foreground/50 hover:text-muted-foreground/80 transition-colors cursor-pointer"
              >
                <span className={`transition-transform ${showHolidays ? "rotate-90" : ""}`}>▸</span>
                {data.holidays.length} upcoming
              </button>
            )}
          </div>

          <div className="flex items-center gap-2">
            {/* Stale data warning */}
            {!data.current_year_covered && (
              <span className="text-[10px] text-[#f85149]">
                Calendar data outdated
              </span>
            )}

            {/* Refresh button */}
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="rounded-md px-2 py-1 text-[10px] text-muted-foreground/50 hover:text-muted-foreground/80 hover:bg-[#161d26] transition-colors cursor-pointer disabled:opacity-50"
            >
              {refreshing ? "…" : "↻ Refresh"}
            </button>
          </div>
        </div>

        {/* Expandable holidays list */}
        {showHolidays && data.holidays.length > 0 && (
          <div className="mt-3 border-t border-border/30 pt-3">
            <div className="grid gap-1.5">
              {data.holidays.map((h) => (
                <div key={h.date} className="flex items-center justify-between text-xs">
                  <span className="text-foreground/70">{h.name}</span>
                  <span className="font-mono-nums text-muted-foreground/60">
                    {new Date(h.date + "T00:00:00").toLocaleDateString("en-IN", {
                      weekday: "short",
                      month: "short",
                      day: "numeric",
                    })}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
