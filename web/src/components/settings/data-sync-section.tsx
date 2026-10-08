"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";

export function DataSyncSection() {
  const [status, setStatus] = useState<Record<string, unknown>>({ status: "loading" });
  const [polling, setPolling] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const s = await api.getSyncStatus();
      setStatus(s);
      return s;
    } catch {
      setStatus({ status: "error", error: "Failed to fetch sync status" });
      return { status: "error" };
    }
  }, []);

  useEffect(() => {
    fetchStatus().then((s) => {
      if (s.status === "running" || s.status === "starting" || s.status === "filling_gaps") {
        setPolling(true);
      }
    });
  }, [fetchStatus]);

  useEffect(() => {
    if (!polling) return;
    const interval = setInterval(async () => {
      const s = await fetchStatus();
      if (s.status !== "running" && s.status !== "starting" && s.status !== "filling_gaps") {
        setPolling(false);
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [polling, fetchStatus]);

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
  const isRunning = st === "running" || st === "starting" || st === "filling_gaps";
  const isComplete = st === "complete";
  const dailyStale = Boolean(status.daily_stale);
  const daysBehind = Number(status.days_behind ?? 0);
  const msg = String(status.message ?? "");
  const elapsed = status.elapsed_sec != null ? Number(status.elapsed_sec) : null;
  const rowsWritten = status.rows_written;

  // Parse progress from message like "Daily sync 15m: 45/200 stocks"
  const progressMatch = msg.match(/(\d+)\/(\d+)\s+stocks/);
  const progressCurrent = progressMatch ? parseInt(progressMatch[1]) : null;
  const progressTotal = progressMatch ? parseInt(progressMatch[2]) : null;
  const progressPct = progressCurrent != null && progressTotal != null && progressTotal > 0
    ? Math.round((progressCurrent / progressTotal) * 100) : null;

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
          Auto-sync runs at 4 PM IST.
        </div>
      )}

      {isRunning && (
        <div className="mb-3 space-y-2">
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 animate-pulse rounded-full bg-[#d4a015]" />
            <span className="text-sm font-medium text-[#d4a015]">Syncing</span>
            {elapsed != null && (
              <span className="text-xs text-muted-foreground">
                {Math.floor(elapsed / 60)}m {elapsed % 60}s
              </span>
            )}
            {progressPct != null && (
              <span className="text-xs font-mono text-[#d4a015]">{progressPct}%</span>
            )}
          </div>
          {msg && (
            <p className="text-xs text-muted-foreground">{msg}</p>
          )}
          {progressPct != null && (
            <div className="h-1.5 w-full rounded-full bg-[rgba(28,39,54,0.5)] overflow-hidden">
              <div
                className="h-full rounded-full bg-[#d4a015] transition-all duration-500"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          )}
          {rowsWritten != null && (
            <p className="text-[10px] text-muted-foreground font-mono">
              {typeof rowsWritten === "object"
                ? `${Object.values(rowsWritten as Record<string, number>).reduce((a: number, b: number) => a + b, 0).toLocaleString()} rows total`
                : `${Number(rowsWritten).toLocaleString()} rows written`}
            </p>
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
