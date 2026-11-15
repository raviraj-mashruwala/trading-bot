"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import type { ExecutionDecision } from "@/types";
import { getExplanation } from "@/lib/decision-explanations";

const typeColor: Record<string, string> = {
  ENTRY_ENTER: "text-[#2da44e]",
  ENTRY_VETO: "text-[#f85149]",
  ENTRY_WAIT: "text-[#d4a015]",
  MOMENTUM_EXIT: "text-orange-500",
  PATTERN_EXIT: "text-orange-500",
  TRAIL_STOP: "text-blue-500",
  STOP_HIT: "text-[#f85149]",
  BOOK_TARGET_1: "text-[#2da44e]",
  BOOK_TARGET_2: "text-[#2da44e]",
  LLM_ESCALATION: "text-purple-500",
  KILL_SWITCH: "text-[#f85149]",
  SQUARE_OFF: "text-[#d4a015]",
};

const typeBgColor: Record<string, string> = {
  ENTRY_ENTER: "bg-[#2da44e]/15",
  ENTRY_VETO: "bg-[#f85149]/15",
  ENTRY_WAIT: "bg-[#d4a015]/15",
  MOMENTUM_EXIT: "bg-orange-500/15",
  PATTERN_EXIT: "bg-orange-500/15",
  TRAIL_STOP: "bg-blue-500/15",
  STOP_HIT: "bg-[#f85149]/15",
  BOOK_TARGET_1: "bg-[#2da44e]/15",
  BOOK_TARGET_2: "bg-[#2da44e]/15",
  LLM_ESCALATION: "bg-purple-500/15",
  KILL_SWITCH: "bg-[#f85149]/15",
  SQUARE_OFF: "bg-[#d4a015]/15",
};

const typeLabel: Record<string, string> = {
  ENTRY_ENTER: "ENTER",
  ENTRY_VETO: "VETO",
  ENTRY_WAIT: "WAIT",
  MOMENTUM_EXIT: "MOM EXIT",
  PATTERN_EXIT: "PAT EXIT",
  TRAIL_STOP: "TRAIL",
  STOP_HIT: "STOP",
  BOOK_TARGET_1: "T1 HIT",
  BOOK_TARGET_2: "T2 HIT",
  LLM_ESCALATION: "AI",
  KILL_SWITCH: "KILL",
  SQUARE_OFF: "SQ OFF",
};

function formatTime(timestamp: string): string {
  try {
    const d = new Date(timestamp);
    return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  } catch {
    return timestamp.slice(11, 19);
  }
}

function formatDateLabel(dateStr: string): string {
  try {
    const d = new Date(dateStr + "T00:00:00");
    return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
  } catch {
    return dateStr;
  }
}

function todayIST(): string {
  const now = new Date();
  const ist = new Date(now.getTime() + (5.5 * 60 * 60 * 1000));
  return ist.toISOString().slice(0, 10);
}

function shiftDate(dateStr: string, days: number): string {
  const d = new Date(dateStr + "T00:00:00");
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

interface MomentumSnapshot {
  momentum_1m: number;
  momentum_5m: number;
  volume_ratio: number;
  vwap_position: number;
  trend_alignment: boolean;
}

function parseMomentum(raw: string | Record<string, unknown> | null): MomentumSnapshot | null {
  if (!raw) return null;
  try {
    const obj = typeof raw === "string" ? JSON.parse(raw) : raw;
    if (typeof obj.momentum_1m !== "number") return null;
    return obj as MomentumSnapshot;
  } catch {
    return null;
  }
}

function MomentumPills({ m }: { m: MomentumSnapshot }) {
  const m1Color = m.momentum_1m > 20 ? "text-[#2da44e]" : m.momentum_1m < -20 ? "text-[#f85149]" : "text-[#5a6a7f]";
  const m5Color = m.momentum_5m > 20 ? "text-[#2da44e]" : m.momentum_5m < -20 ? "text-[#f85149]" : "text-[#5a6a7f]";
  const volColor = m.volume_ratio > 0.7 ? "text-[#c9d1d9]" : "text-[#f85149]";
  const vwapColor = m.vwap_position > 0.3 ? "text-[#2da44e]" : m.vwap_position < -0.3 ? "text-[#f85149]" : "text-[#5a6a7f]";

  return (
    <div className="flex items-center gap-3">
      <span className={`font-mono text-[10px] ${m1Color}`} title="1-min momentum">
        1m:{m.momentum_1m > 0 ? "+" : ""}{m.momentum_1m.toFixed(0)}
      </span>
      <span className={`font-mono text-[10px] ${m5Color}`} title="5-min momentum">
        5m:{m.momentum_5m > 0 ? "+" : ""}{m.momentum_5m.toFixed(0)}
      </span>
      <span className={`font-mono text-[10px] ${volColor}`} title="Volume ratio (1.0 = normal)">
        vol:{m.volume_ratio.toFixed(1)}x
      </span>
      <span className={`font-mono text-[10px] ${vwapColor}`} title="VWAP position (-1 to +1)">
        vwap:{m.vwap_position > 0 ? "+" : ""}{m.vwap_position.toFixed(1)}
      </span>
      {m.trend_alignment && (
        <span className="h-1.5 w-1.5 rounded-full bg-[#2da44e] shrink-0" title="Trend aligned" />
      )}
    </div>
  );
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const pnlMatch = outcome.match(/pnl=([+-][\d.]+)/);
  if (!pnlMatch) return null;
  const pnl = parseFloat(pnlMatch[1]);
  const color = pnl >= 0 ? "text-[#2da44e] bg-[#2da44e]/10" : "text-[#f85149] bg-[#f85149]/10";
  const exitReason = outcome.split("|")[0];
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] font-mono font-semibold shrink-0 ${color}`}
      title={`Exit: ${exitReason}`}
    >
      {pnl >= 0 ? "+" : ""}{pnl.toFixed(0)}
    </span>
  );
}

function DecisionRow({ d }: { d: ExecutionDecision }) {
  const [expanded, setExpanded] = useState(false);
  const momentum = parseMomentum(d.momentum_snapshot);
  const explanation = getExplanation(d.decision_type, d.reason);
  const hasDetail = momentum || explanation;

  return (
    <div className="border-b border-[rgba(28,39,54,0.3)] last:border-b-0">
      <button
        type="button"
        onClick={() => hasDetail && setExpanded(!expanded)}
        className={`grid grid-cols-[4.5rem_5rem_4.5rem_1fr_auto] gap-2 items-center w-full text-left text-xs px-3 py-1.5 transition-colors ${hasDetail ? "hover:bg-[rgba(212,160,21,0.05)] cursor-pointer" : "cursor-default"}`}
      >
        <span className="text-[#5a6a7f] font-mono text-[11px]">
          {formatTime(d.timestamp)}
        </span>
        <span className="font-medium text-[#e6edf3] font-mono text-[11px] truncate">
          {d.symbol}
        </span>
        <span className={`inline-flex items-center justify-center rounded px-1.5 py-0.5 text-[10px] font-semibold ${typeColor[d.decision_type] ?? "text-[#c9d1d9]"} ${typeBgColor[d.decision_type] ?? "bg-[#c9d1d9]/10"}`}>
          {typeLabel[d.decision_type] ?? d.decision_type}
        </span>
        <span className="text-[#5a6a7f] text-[11px] truncate">
          {d.reason}
          {d.escalated === 1 && (
            <span className="ml-1.5 rounded bg-purple-500/15 px-1 py-0.5 text-[10px] font-semibold text-purple-500">
              AI
            </span>
          )}
        </span>
        <div className="flex items-center gap-1.5">
          {d.outcome && <OutcomeBadge outcome={d.outcome} />}
          {hasDetail && (
            <span className="text-[#5a6a7f] text-[10px]">{expanded ? "▾" : "▸"}</span>
          )}
        </div>
      </button>

      {expanded && (
        <div className="px-3 pb-2 pt-0.5 ml-[4.5rem] space-y-1">
          {momentum && <MomentumPills m={momentum} />}
          {explanation && (
            <div className="rounded bg-[rgba(22,29,38,0.6)] border border-[rgba(28,39,54,0.5)] px-2 py-1.5">
              <p className="text-[11px] font-medium text-[#d4a015]">{explanation.short}</p>
              <p className="text-[10px] text-[#5a6a7f] leading-relaxed mt-0.5">{explanation.detail}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface DecisionTimelineProps {
  decisions?: ExecutionDecision[];
  showDatePicker?: boolean;
}

export function DecisionTimeline({ decisions: externalDecisions, showDatePicker = true }: DecisionTimelineProps) {
  const [selectedDate, setSelectedDate] = useState(todayIST);
  const isToday = selectedDate === todayIST();

  const { data: fetchedDecisions } = useQuery({
    queryKey: ["decisions", selectedDate],
    queryFn: () => api.getDecisions(selectedDate),
    refetchInterval: isToday ? 5_000 : false,
    enabled: showDatePicker && !externalDecisions,
  });

  const decisions = externalDecisions ?? fetchedDecisions ?? [];

  const symbolGroups = decisions.reduce<Record<string, number>>((acc, d) => {
    acc[d.symbol] = (acc[d.symbol] ?? 0) + 1;
    return acc;
  }, {});
  const symbolCount = Object.keys(symbolGroups).length;

  return (
    <Card className="border-[rgba(28,39,54,0.5)] bg-[#0f1419]/80">
      <CardHeader className="pb-2 pt-4 px-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm text-[#e6edf3]">Decision Log</CardTitle>
          <div className="flex items-center gap-3">
            {decisions.length > 0 && (
              <span className="text-[10px] text-[#5a6a7f] font-mono">
                {decisions.length} decisions · {symbolCount} symbol{symbolCount !== 1 ? "s" : ""}
              </span>
            )}
            {showDatePicker && !externalDecisions && (
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setSelectedDate(shiftDate(selectedDate, -1))}
                  className="text-[#5a6a7f] hover:text-[#e6edf3] px-1.5 py-0.5 rounded hover:bg-[rgba(212,160,21,0.05)] transition-colors text-xs"
                  title="Previous day"
                >
                  ‹
                </button>
                <button
                  type="button"
                  onClick={() => setSelectedDate(todayIST())}
                  className={`text-[11px] font-mono px-2 py-0.5 rounded transition-colors ${isToday ? "text-[#d4a015] bg-[rgba(212,160,21,0.1)]" : "text-[#5a6a7f] hover:text-[#e6edf3] hover:bg-[rgba(212,160,21,0.05)]"}`}
                  title="Jump to today"
                >
                  {formatDateLabel(selectedDate)}
                </button>
                <button
                  type="button"
                  onClick={() => setSelectedDate(shiftDate(selectedDate, 1))}
                  disabled={isToday}
                  className="text-[#5a6a7f] hover:text-[#e6edf3] px-1.5 py-0.5 rounded hover:bg-[rgba(212,160,21,0.05)] transition-colors text-xs disabled:opacity-30 disabled:cursor-not-allowed"
                  title="Next day"
                >
                  ›
                </button>
              </div>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="px-0 pb-2 pt-0">
        {decisions.length === 0 ? (
          <p className="text-xs text-[#5a6a7f] px-4 py-3">No decisions{isToday ? " yet" : ` on ${formatDateLabel(selectedDate)}`}</p>
        ) : (
          <>
            {/* Table header */}
            <div className="grid grid-cols-[4.5rem_5rem_4.5rem_1fr_auto] gap-2 items-center px-3 py-1 border-b border-[rgba(28,39,54,0.5)]">
              <span className="text-[10px] text-[#5a6a7f]">Time</span>
              <span className="text-[10px] text-[#5a6a7f]">Symbol</span>
              <span className="text-[10px] text-[#5a6a7f]">Type</span>
              <span className="text-[10px] text-[#5a6a7f]">Reason</span>
              <span className="text-[10px] text-[#5a6a7f]">P&L</span>
            </div>
            <div className="max-h-96 overflow-y-auto">
              {[...decisions].reverse().map((d) => (
                <DecisionRow key={d.id} d={d} />
              ))}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
