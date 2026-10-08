"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { NightlyReview } from "@/types";
import { api } from "@/lib/api";

const gradeColor: Record<string, string> = {
  A: "text-[#2da44e]",
  B: "text-[#2da44e]",
  C: "text-[#d4a015]",
  D: "text-[#f85149]",
  F: "text-[#f85149]",
};

function parseJsonArray(raw: string): string[] {
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function NightlyReviewHistory() {
  const { data: reviews } = useQuery({
    queryKey: ["nightly-history"],
    queryFn: () => api.getNightlyHistory(10),
    refetchInterval: 60_000,
  });

  if (!reviews?.length) return null;

  return (
    <Card className="border-[rgba(28,39,54,0.5)] bg-[#0f1419]/80">
      <CardHeader className="pb-2 pt-4 px-4">
        <CardTitle className="text-sm text-[#e6edf3]">Review History</CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-4 pt-0">
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {reviews.map((r: NightlyReview) => {
            const lessons = parseJsonArray(r.lessons);
            return (
              <div key={r.trade_date} className="rounded border border-[rgba(28,39,54,0.5)] px-3 py-2">
                <div className="flex items-center gap-3">
                  <span className="text-xs font-mono text-[#5a6a7f]">{r.trade_date}</span>
                  <span className={`text-xs font-bold ${gradeColor[r.grade] ?? "text-[#5a6a7f]"}`}>
                    {r.grade}
                  </span>
                  <span className={`text-xs font-mono ${r.total_pnl >= 0 ? "text-[#2da44e]" : "text-[#f85149]"}`}>
                    {r.total_pnl >= 0 ? "+" : ""}₹{r.total_pnl.toFixed(0)}
                  </span>
                  <span className="text-[10px] text-[#5a6a7f] ml-auto">
                    {r.trades_count} trades
                  </span>
                </div>
                {r.summary && (
                  <p className="text-[10px] text-[#5a6a7f] mt-1 leading-relaxed line-clamp-2">{r.summary}</p>
                )}
                {lessons.length > 0 && (
                  <p className="text-[10px] text-[#d4a015]/70 mt-0.5 truncate">
                    Lesson: {lessons[0]}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
