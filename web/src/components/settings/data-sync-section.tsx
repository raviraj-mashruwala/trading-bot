"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";

export function DataSyncSection() {
  const [status, setStatus] = useState<Record<string, unknown>>({ status: "loading" });
  const [polling, setPolling] = useState(false);

  const fetchStatus = async () => {
    try {
      const s = await api.getSyncStatus();
      setStatus(s);
      return s;
    } catch {
      setStatus({ status: "error", error: "Failed to fetch sync status" });
      return { status: "error" };
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  useEffect(() => {
    if (!polling) return;
    const interval = setInterval(async () => {
      const s = await fetchStatus();
      if (s.status !== "running" && s.status !== "starting") {
        setPolling(false);
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [polling]);

  const handleStart = async (forceFull = false) => {
    try {
      await api.startSync(forceFull || isEmpty);
      setPolling(true);
      await fetchStatus();
    } catch (e: unknown) {
      setStatus({ status: "error", error: e instanceof Error ? e.message : "Failed to start" });
    }
  };

  const handleCancel = async () => {
    try {
      await api.cancelSync();
      await fetchStatus();
    } catch {
      // ignore
    }
  };

  const st = String(status.status ?? "unknown");
  const freshness = status.freshness as Record<string, string> | undefined;
  const rowCounts = status.row_counts as Record<string, number> | undefined;
  const isEmpty = !freshness || Object.keys(freshness).length === 0;
  const isRunning = st === "running" || st === "starting";
  const isComplete = st === "complete";
  const dailyStale = Boolean(status.daily_stale);
  const daysBehind = Number(status.days_behind ?? 0);

  return (
    <div className="rounded-lg border border-border/50 bg-card/80 p-4">
      <div className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-[#d4a015]/80">
        Data Cache
      </div>

      {isEmpty && !isRunning && !isComplete && (
        <div className="mb-3 rounded bg-[#d4a015]/10 px-3 py-2 text-sm text-[#d4a015]">
          Cache empty — run initial fill to download daily data for ~1,675 stocks from Kite.
          Intraday data is fetched on demand during analysis for shortlisted stocks only.
        </div>
      )}

      {dailyStale && !isEmpty && !isRunning && (
        <div className="mb-3 rounded bg-[#d4a015]/10 px-3 py-2 text-sm text-[#d4a015]">
          Daily sync pending — {daysBehind} trading day{daysBehind !== 1 ? "s" : ""} behind
          {status.last_trading_day ? ` (last session: ${String(status.last_trading_day)})` : ""}.
          Auto-sync runs at 8 PM IST.
        </div>
      )}

      {isRunning && (
        <div className="mb-3 space-y-2">
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 animate-pulse rounded-full bg-[#d4a015]" />
            <span className="text-sm font-medium text-[#d4a015]">Syncing...</span>
            {status.elapsed_sec != null && (
              <span className="text-xs text-muted-foreground">
                {Math.floor(Number(status.elapsed_sec) / 60)}m {Number(status.elapsed_sec) % 60}s
              </span>
            )}
          </div>
          {status.message && (
            <p className="text-xs text-muted-foreground">{String(status.message)}</p>
          )}
        </div>
      )}

      {isComplete && (
        <div className="mb-3 rounded bg-[#2da44e]/10 px-3 py-2 text-sm text-[#2da44e]">
          Sync complete — {String(status.stocks_synced ?? 0)} stocks, {String(status.rows_written ?? 0)} rows
          {status.errors ? `, ${String(status.errors)} errors` : ""}
        </div>
      )}

      {st === "error" && (
        <div className="mb-3 rounded bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {String(status.error ?? "Unknown error")}
        </div>
      )}

      {freshness && Object.keys(freshness).length > 0 && (
        <div className="mb-3 space-y-1">
          <div className="text-xs font-medium text-muted-foreground">Cache freshness:</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            {Object.entries(freshness).map(([interval, date]) => (
              <div key={interval} className="flex justify-between">
                <span className="text-muted-foreground">{interval}</span>
                <span className="font-mono">{String(date)}</span>
              </div>
            ))}
          </div>
          {rowCounts && (
            <div className="mt-1 text-xs text-muted-foreground">
              Total: {Object.values(rowCounts).reduce((a, b) => a + b, 0).toLocaleString()} rows
            </div>
          )}
        </div>
      )}

      <div className="flex gap-2">
        {!isRunning && isEmpty && (
          <button
            onClick={handleStart}
            className="rounded bg-[#d4a015] px-3 py-1.5 text-xs font-semibold text-black hover:bg-[#d4a015]/90"
          >
            Start Initial Fill
          </button>
        )}
        {!isRunning && dailyStale && !isEmpty && (
          <button
            onClick={() => handleStart(false)}
            className="rounded bg-[#d4a015] px-3 py-1.5 text-xs font-semibold text-black hover:bg-[#d4a015]/90"
          >
            Run Daily Sync
          </button>
        )}
        {!isRunning && !isEmpty && !dailyStale && (st === "idle" || st === "error") && (
          <button
            onClick={() => handleStart(false)}
            className="rounded border border-border/50 px-3 py-1.5 text-xs text-muted-foreground hover:bg-card"
          >
            Re-sync
          </button>
        )}
        {!isRunning && isComplete && (
          <button
            onClick={() => handleStart(false)}
            className="rounded border border-border/50 px-3 py-1.5 text-xs text-muted-foreground hover:bg-card"
          >
            Re-sync
          </button>
        )}
        {isRunning && (
          <button
            onClick={handleCancel}
            className="rounded border border-red-500/30 px-3 py-1.5 text-xs text-red-400 hover:bg-red-500/10"
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}
