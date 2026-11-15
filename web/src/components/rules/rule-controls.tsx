"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ruleApi, type RuleMode, type RuleStatus } from "@/lib/rule-api";
import { Button } from "@/components/ui/button";
import { AlertDialog, Dialog } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

const NOTIONAL_KEY = "kec-rule-notional";

export function RuleControls({ status }: { status: RuleStatus | undefined }) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<RuleMode>("paper");
  const [notional, setNotional] = useState(() => {
    if (typeof window === "undefined") return "100000";
    try {
      return localStorage.getItem(NOTIONAL_KEY) || "100000";
    } catch {
      return "100000";
    }
  });
  const [liveOpen, setLiveOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [stopOpen, setStopOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const running = status?.running ?? false;
  const runningMode = status?.session?.mode;
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["rule-status"] });
    queryClient.invalidateQueries({ queryKey: ["rule-events"] });
    queryClient.invalidateQueries({ queryKey: ["rule-trades"] });
  };

  const start = useMutation({
    mutationFn: (args: { mode: RuleMode; confirm?: string }) =>
      ruleApi.start(args.mode, Number(notional), args.confirm),
    onSuccess: (r) => {
      setMessage(`Started in ${r.mode} mode`);
      try {
        localStorage.setItem(NOTIONAL_KEY, notional);
      } catch {
        /* storage unavailable */
      }
      refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const stop = useMutation({
    mutationFn: ruleApi.stop,
    onSuccess: (r) => {
      setMessage(
        r.position_left_open
          ? "Stopped. The open short keeps its stop order at the broker; restart to manage the exit."
          : "Stopped",
      );
      refresh();
    },
    onError: (e: Error) => setMessage(e.message),
  });

  const notionalValue = Number(notional);
  const notionalValid = Number.isFinite(notionalValue) && notionalValue >= 5000 && notionalValue <= 1000000;

  const onStart = () => {
    setMessage(null);
    if (mode === "live") {
      setConfirmText("");
      setLiveOpen(true);
    } else {
      start.mutate({ mode: "paper" });
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <div
          role="radiogroup"
          aria-label="Trading mode"
          className="inline-flex rounded-md border border-border/50 bg-card/80 p-0.5"
        >
          {(["paper", "live"] as RuleMode[]).map((m) => (
            <button
              key={m}
              role="radio"
              aria-checked={mode === m}
              disabled={running}
              onClick={() => setMode(m)}
              className={cn(
                "h-8 rounded px-4 text-[13px] font-medium transition-colors disabled:opacity-50",
                mode === m
                  ? m === "live"
                    ? "bg-[#f85149]/15 text-[#f85149]"
                    : "bg-[#d4a015]/10 text-[#d4a015]"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {m === "paper" ? "Paper" : "Live"}
            </button>
          ))}
        </div>

        <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
          Per trade ₹
          <input
            inputMode="numeric"
            value={notional}
            disabled={running}
            onChange={(e) => setNotional(e.target.value.replace(/[^0-9]/g, ""))}
            className="h-9 w-28 rounded-md border border-[rgba(28,39,54,0.5)] bg-[rgba(22,29,38,0.3)] px-3 font-mono-nums text-sm text-foreground outline-none focus:border-[rgba(212,160,21,0.5)] disabled:opacity-50"
          />
        </label>

        {!running ? (
          <Button
            onClick={onStart}
            disabled={!notionalValid || start.isPending}
            className={cn(
              mode === "live"
                ? "bg-[#f85149] text-white hover:bg-[#f85149]/90"
                : "bg-[#d4a015] text-[#070a0f] hover:bg-[#e5b320]",
            )}
          >
            {start.isPending ? "Starting…" : mode === "live" ? "Start live" : "Start paper"}
          </Button>
        ) : (
          <Button variant="outline" onClick={() => setStopOpen(true)} disabled={stop.isPending}>
            Stop {runningMode}
          </Button>
        )}
      </div>

      {!notionalValid && !running && (
        <p className="text-[11px] text-[#f85149]">Amount must be between ₹5,000 and ₹10,00,000.</p>
      )}
      {running && (
        <p className="text-[11px] text-muted-foreground">
          To switch between paper and live, stop the running session first.
        </p>
      )}
      {message && <p className="text-xs text-muted-foreground">{message}</p>}

      <Dialog open={liveOpen} onClose={() => setLiveOpen(false)}>
        <h3 className="mb-2 text-sm font-semibold text-[#e6edf3]">Start live trading</h3>
        <p className="mb-3 text-xs leading-relaxed text-[#c9d1d9]">
          This places real MIS orders on Kite: a short of about ₹{notionalValue.toLocaleString("en-IN")} in KEC
          at 09:20 if today&apos;s signal fires, a stop-loss order at the broker, and a buy-back by 15:15.
          Type LIVE to confirm.
        </p>
        <input
          autoFocus
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          aria-label="Type LIVE to confirm"
          className="mb-4 h-9 w-full rounded-md border border-[rgba(28,39,54,0.5)] bg-[rgba(22,29,38,0.3)] px-3 font-mono-nums text-sm text-foreground outline-none focus:border-[rgba(212,160,21,0.5)]"
        />
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={() => setLiveOpen(false)}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={confirmText !== "LIVE"}
            className="bg-[#f85149] text-white hover:bg-[#f85149]/90"
            onClick={() => {
              setLiveOpen(false);
              start.mutate({ mode: "live", confirm: "LIVE" });
            }}
          >
            Start live
          </Button>
        </div>
      </Dialog>

      <AlertDialog
        open={stopOpen}
        onClose={() => setStopOpen(false)}
        onConfirm={() => {
          setStopOpen(false);
          stop.mutate();
        }}
        title="Stop the rule executor?"
        description={
          status?.session?.phase === "in_position"
            ? "A short is open. Stopping leaves it at the broker with its stop order, but nothing will buy it back at 15:15 unless you restart. Zerodha auto-squares MIS positions near 15:20."
            : "No position is open. Today's session will end."
        }
        confirmLabel="Stop"
        variant="destructive"
      />
    </div>
  );
}
