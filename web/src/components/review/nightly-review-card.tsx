"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { NightlyReview } from "@/types";
import { api } from "@/lib/api";

const gradeColor: Record<string, string> = {
  A: "text-[#2da44e] bg-[#2da44e]/10 border-[#2da44e]/30",
  B: "text-[#2da44e] bg-[#2da44e]/10 border-[#2da44e]/20",
  C: "text-[#d4a015] bg-[#d4a015]/10 border-[#d4a015]/20",
  D: "text-[#f85149] bg-[#f85149]/10 border-[#f85149]/20",
  F: "text-[#f85149] bg-[#f85149]/10 border-[#f85149]/30",
};

function parseJsonArray(raw: string): string[] {
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return raw ? [raw] : [];
  }
}

export function NightlyReviewCard({
  review,
  date,
}: {
  review: NightlyReview | null | undefined;
  date: string;
}) {
  const [expanded, setExpanded] = useState(true);
  const queryClient = useQueryClient();

  const runReview = useMutation({
    mutationFn: () => api.runNightlyReview(date),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["nightly-review"] });
    },
  });

  if (!review) {
    return (
      <Card className="border-[rgba(28,39,54,0.5)] bg-[#0f1419]/80">
        <CardContent className="py-4 px-4 flex items-center justify-between">
          <p className="text-xs text-[#5a6a7f]">No nightly review for {date}</p>
          <button
            onClick={() => runReview.mutate()}
            disabled={runReview.isPending}
            className="rounded-md bg-[rgba(212,160,21,0.2)] border border-[rgba(212,160,21,0.3)] px-3 py-1.5 text-xs font-medium text-[#d4a015] hover:bg-[rgba(212,160,21,0.3)] transition-colors disabled:opacity-50"
          >
            {runReview.isPending ? "Reviewing..." : "Run Review"}
          </button>
        </CardContent>
      </Card>
    );
  }

  const lessons = parseJsonArray(review.lessons);
  const improvements = parseJsonArray(review.improvements);
  const winRate = review.trades_count > 0 ? ((review.wins / review.trades_count) * 100).toFixed(0) : "0";

  return (
    <Card className="border-[rgba(28,39,54,0.5)] bg-[#0f1419]/80">
      <CardHeader className="pb-2 pt-4 px-4">
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="flex items-center justify-between w-full text-left"
        >
          <div className="flex items-center gap-3">
            <CardTitle className="text-sm text-[#e6edf3]">Nightly Review</CardTitle>
            <span
              className={`rounded-md border px-2 py-0.5 text-xs font-bold ${gradeColor[review.grade] ?? "text-[#5a6a7f]"}`}
            >
              {review.grade}
            </span>
            <span className="text-[10px] text-[#5a6a7f] font-mono">
              {review.trades_count} trades | {winRate}% WR |{" "}
              <span className={review.total_pnl >= 0 ? "text-[#2da44e]" : "text-[#f85149]"}>
                ₹{review.total_pnl >= 0 ? "+" : ""}{review.total_pnl.toFixed(0)}
              </span>
            </span>
          </div>
          <span className="text-[#5a6a7f] text-xs">{expanded ? "▾" : "▸"}</span>
        </button>
      </CardHeader>

      {expanded && (
        <CardContent className="px-4 pb-4 pt-0 space-y-3">
          <p className="text-xs text-[#c9d1d9] leading-relaxed">{review.summary}</p>

          {lessons.length > 0 && (
            <div>
              <h4 className="text-[10px] text-[#d4a015] font-semibold mb-1">
                Lessons
              </h4>
              <ul className="space-y-1">
                {lessons.map((l, i) => (
                  <li key={i} className="text-[11px] text-[#c9d1d9] leading-relaxed pl-3 relative before:content-['•'] before:absolute before:left-0 before:text-[#d4a015]">
                    {l}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {improvements.length > 0 && (
            <div>
              <h4 className="text-[10px] text-[#2da44e] font-semibold mb-1">
                Improvements
              </h4>
              <ul className="space-y-1">
                {improvements.map((imp, i) => (
                  <li key={i} className="text-[11px] text-[#c9d1d9] leading-relaxed pl-3 relative before:content-['→'] before:absolute before:left-0 before:text-[#2da44e]">
                    {imp}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex items-center justify-between pt-1 border-t border-[rgba(28,39,54,0.5)]">
            <span className="text-[10px] text-[#5a6a7f]">
              Reviewed {new Date(review.reviewed_at).toLocaleString("en-IN", { hour: "2-digit", minute: "2-digit", day: "numeric", month: "short" })}
            </span>
            <span className="text-[10px] text-[#5a6a7f]">
              Cost: ${review.llm_cost_usd.toFixed(4)}
            </span>
          </div>
        </CardContent>
      )}
    </Card>
  );
}
