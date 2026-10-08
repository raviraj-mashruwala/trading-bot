"use client";

import { useQuery } from "@tanstack/react-query";
import { useSearchParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { PerformanceCards } from "@/components/review/performance-cards";
import { StrategyBreakdown } from "@/components/review/strategy-breakdown";
import { ConfluenceChart } from "@/components/review/confluence-chart";
import { ScorecardTable } from "@/components/review/scorecard-table";
import { NightlyReviewCard } from "@/components/review/nightly-review-card";
import { NightlyReviewHistory } from "@/components/review/nightly-review-history";

const PERIODS = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
];

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

export default function ReviewPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const days = Number(searchParams.get("days") ?? 30);
  const scorecardDate = searchParams.get("date") ?? todayStr();
  const setDays = (d: number) => router.replace(`/review?days=${d}&date=${scorecardDate}`);
  const setScorecardDate = (d: string) => router.replace(`/review?days=${days}&date=${d}`);

  const { data: stats } = useQuery({
    queryKey: ["performance-stats", days],
    queryFn: () => api.getPerformanceStats(days),
    refetchInterval: 60_000,
  });

  const { data: scorecards } = useQuery({
    queryKey: ["scorecards", scorecardDate],
    queryFn: () => api.getScorecards(scorecardDate),
    refetchInterval: 30_000,
  });

  const { data: nightlyReview } = useQuery({
    queryKey: ["nightly-review", scorecardDate],
    queryFn: () => api.getNightlyReview(scorecardDate).catch(() => null),
    refetchInterval: 60_000,
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Review</h1>
        <div className="flex gap-0.5 rounded-lg border border-[rgba(255,255,255,0.06)] bg-[#0c1018] p-0.5">
          {PERIODS.map((p) => (
            <button
              key={p.label}
              onClick={() => setDays(p.days)}
              className={`rounded-md px-3 py-1 text-xs font-medium transition-all ${
                days === p.days
                  ? "bg-[#d4a015]/20 text-[#d4a015]"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {stats && (
        <>
          <PerformanceCards stats={stats} />
          <StrategyBreakdown stats={stats} />
          <ConfluenceChart stats={stats} />
        </>
      )}

      <NightlyReviewCard review={nightlyReview} date={scorecardDate} />
      <NightlyReviewHistory />

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-muted-foreground">
            Scorecards
          </h2>
          <input
            type="date"
            value={scorecardDate}
            onChange={(e) => setScorecardDate(e.target.value)}
            className="rounded-md border border-border/50 bg-card/80 px-2 py-1 text-xs text-foreground"
          />
        </div>
        <ScorecardTable scorecards={scorecards ?? []} />
      </div>
    </div>
  );
}
