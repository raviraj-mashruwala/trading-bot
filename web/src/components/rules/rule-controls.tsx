"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ruleApi, type RuleMode, type RuleSizing, type RuleStatus } from "@/lib/rule-api";
import { Button } from "@/components/ui/button";
import { AlertDialog, Dialog } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export const BUFFER_KEY = "kec-rule-buffer";
export const DEFAULT_BUFFER = "2500";
export const STOP_KEY = "kec-rule-stop-mult";
export const DEFAULT_STOP = "0.65";

export function stopMultValid(v: string) {
  const n = Number(v);
  return v !== "" && Number.isFinite(n) && n >= 0.1 && n <= 2;
}

function inr(n: number | undefined | null) {
  return n == null ? "—" : `₹${Math.round(n).toLocaleString("en-IN")}`;
}

interface Props {
  status: RuleStatus | undefined;
  buffer: string;
  onBufferChange: (value: string) => void;
  stopMult: string;
  onStopMultChange: (value: string) => void;
  sizing: RuleSizing | null | undefined;
}

export function RuleControls({ status, buffer, onBufferChange, stopMult, onStopMultChange, sizing }: Props) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<RuleMode>("paper");
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

  const bufferValue = Number(buffer);
  const bufferValid = buffer !== "" && Number.isFinite(bufferValue) && bufferValue >= 0 && bufferValue <= 1000000;

  const start = useMutation({
    mutationFn: (args: { mode: RuleMode; confirm?: string }) => ruleApi.start(args.mode, bufferValue, Number(stopMult), args.confirm),
    onSuccess: (r) => {
      setMessage(`Started in ${r.mode} mode, keeping ₹${r.buffer.toLocaleString("en-IN")} unused, stop ${r.stop_adr_mult}× ADR`);
      try {
        localStorage.setItem(BUFFER_KEY, buffer);
        localStorage.setItem(STOP_KEY, stopMult);
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
          Keep unused ₹
          <input
            inputMode="numeric"
            value={buffer}
            disabled={running}
            onChange={(e) => onBufferChange(e.target.value.replace(/[^0-9]/g, ""))}
            className="h-9 w-24 rounded-md border border-[rgba(28,39,54,0.5)] bg-[rgba(22,29,38,0.3)] px-3 font-mono-nums text-sm text-foreground outline-none focus:border-[rgba(212,160,21,0.5)] disabled:opacity-50"
          />
        </label>

        <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
          Stop × ADR
          <input
            inputMode="decimal"
            value={stopMult}
            disabled={running}
            onChange={(e) => onStopMultChange(e.target.value.replace(/[^0-9.]/g, ""))}
            className="h-9 w-16 rounded-md border border-[rgba(28,39,54,0.5)] bg-[rgba(22,29,38,0.3)] px-3 font-mono-nums text-sm text-foreground outline-none focus:border-[rgba(212,160,21,0.5)] disabled:opacity-50"
          />
        </label>

        {!running ? (
          <Button
            onClick={onStart}
            disabled={!bufferValid || !stopMultValid(stopMult) || start.isPending}
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

      <p className="text-[11px] text-muted-foreground">
        Quantity is set at 09:20 from your Kite balance minus this amount, using Kite&apos;s intraday margin per share.
      </p>
      {!stopMultValid(stopMult) && !running && (
        <p className="text-[11px] text-[#f85149]">Stop must be between 0.1 and 2 × ADR.</p>
      )}
      {!bufferValid && !running && (
        <p className="text-[11px] text-[#f85149]">Enter an amount between ₹0 and ₹10,00,000.</p>
      )}
      {running && (
        <p className="text-[11px] text-muted-foreground">
          To switch between paper and live, stop the running session first.
        </p>
      )}
      {message && <p className="text-xs text-muted-foreground">{message}</p>}

      <Dialog open={liveOpen} onClose={() => setLiveOpen(false)}>
        <h3 className="mb-2 text-sm font-semibold text-[#e6edf3]">Start live trading</h3>
        <p className="mb-2 text-xs leading-relaxed text-[#c9d1d9]">
          This places real MIS orders on Kite: a short in KEC at 09:20 if today&apos;s signal fires, sized to your Kite
          balance minus ₹{bufferValue.toLocaleString("en-IN")}, with a stop-loss order {stopMult}× the 14-day average range above entry and a buy-back by 15:15.
        </p>
        {sizing && (
          <p className="mb-2 text-xs leading-relaxed text-[#c9d1d9]">
            At the current price that is about {sizing.quantity} shares ({inr(sizing.position_value)}). If the stop is hit
            you lose about <span className="text-[#f85149]">{inr(sizing.loss_at_stop)}</span>
            {sizing.loss_at_stop_pct_of_balance != null && ` (${sizing.loss_at_stop_pct_of_balance}% of your balance)`} plus charges.
          </p>
        )}
        <p className="mb-3 text-xs text-[#c9d1d9]">Type LIVE to confirm.</p>
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
