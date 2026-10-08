"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";

const STORAGE_KEY = "onboarding-complete";

interface Step {
  label: string;
  done: boolean;
  href: string;
}

function CheckIcon() {
  return (
    <svg className="h-4 w-4 text-[#2da44e]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  );
}

function PendingDot() {
  return <span className="h-3 w-3 rounded-full border-2 border-[#d4a015] bg-transparent" />;
}

export function OnboardingChecklist() {
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    setDismissed(localStorage.getItem(STORAGE_KEY) === "true");
  }, []);

  const { data: kiteStatus } = useQuery({
    queryKey: ["kite-status"],
    queryFn: () => api.getKiteStatus().catch(() => ({ authenticated: false })),
    refetchInterval: 30_000,
  });

  const { data: syncStatus } = useQuery({
    queryKey: ["sync-status-onboarding"],
    queryFn: () => api.getSyncStatus().catch(() => ({})),
    refetchInterval: 30_000,
  });

  const { data: stats } = useQuery({
    queryKey: ["trade-stats"],
    queryFn: () => api.getTradeStats(30),
  });

  const { data: plans } = useQuery({
    queryKey: ["plans"],
    queryFn: () => api.getPlans().catch(() => []),
  });

  const kiteConnected = kiteStatus?.authenticated ?? false;
  const hasSyncData = !!(syncStatus?.freshness && Object.keys(syncStatus.freshness as Record<string, unknown>).length > 0);
  const hasPlans = (plans?.length ?? 0) > 0;
  const hasTrades = (stats?.trade_count ?? 0) > 0;

  const steps: Step[] = [
    { label: "Connect Kite broker", done: kiteConnected, href: "/settings" },
    { label: "Sync market data", done: hasSyncData, href: "/settings" },
    { label: "Run first analysis", done: hasPlans, href: "/analysis" },
    { label: "Start paper trading", done: hasTrades, href: "/trading" },
  ];

  const allDone = steps.every((s) => s.done);

  useEffect(() => {
    if (allDone && !dismissed) {
      localStorage.setItem(STORAGE_KEY, "true");
    }
  }, [allDone, dismissed]);

  if (dismissed) return null;

  return (
    <Card className="border-[rgba(28,39,54,0.5)] bg-[#161d26]">
      <CardHeader className="pb-2 pt-4 px-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm text-[#e6edf3]">Getting Started</CardTitle>
          <span className="text-[10px] text-[#5a6a7f] font-mono">
            {steps.filter((s) => s.done).length}/{steps.length}
          </span>
        </div>
      </CardHeader>
      <CardContent className="px-4 pb-4 pt-0">
        <div className="space-y-2">
          {steps.map((step) => (
            <div key={step.label} className="flex items-center gap-3">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center">
                {step.done ? <CheckIcon /> : <PendingDot />}
              </span>
              {step.done ? (
                <span className="text-xs text-[#5a6a7f] line-through">{step.label}</span>
              ) : (
                <Link
                  href={step.href}
                  className="text-xs text-[#d4a015] hover:text-[#e5b320] transition-colors"
                >
                  {step.label}
                </Link>
              )}
            </div>
          ))}
        </div>
        {allDone && (
          <button
            onClick={() => {
              localStorage.setItem(STORAGE_KEY, "true");
              setDismissed(true);
            }}
            className="mt-3 text-[10px] text-[#5a6a7f] hover:text-[#c9d1d9] transition-colors"
          >
            Dismiss
          </button>
        )}
      </CardContent>
    </Card>
  );
}
