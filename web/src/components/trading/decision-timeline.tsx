"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
    <div className="flex items-center gap-2 mt-1 ml-[4.5rem]">
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
      className={`rounded px-1 py-0.5 text-[10px] font-mono font-semibold shrink-0 ${color}`}
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

  return (
    <div>
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex items-start gap-2 text-xs w-full text-left hover:bg-[rgba(212,160,21,0.05)] rounded px-1 -mx-1 py-0.5 transition-colors"
      >
        <span className="text-[#5a6a7f] font-mono w-[4.5rem] shrink-0">
          {formatTime(d.timestamp)}
        </span>
        <span className="font-medium w-16 shrink-0 text-[#e6edf3]">{d.symbol}</span>
        <span className={`font-semibold w-14 shrink-0 ${typeColor[d.decision_type] ?? "text-[#c9d1d9]"}`}>
          {typeLabel[d.decision_type] ?? d.decision_type}
        </span>
        {d.escalated === 1 && (
          <span className="rounded bg-purple-500/15 px-1 py-0.5 text-[10px] font-semibold text-purple-500 shrink-0">
            AI
          </span>
        )}
        <span className="text-[#5a6a7f] truncate">{d.reason}</span>
        {d.outcome && <OutcomeBadge outcome={d.outcome} />}
        {(momentum || explanation) && (
          <span className="text-[#5a6a7f] shrink-0 ml-auto">{expanded ? "▾" : "▸"}</span>
        )}
      </button>

      {expanded && (
        <div className="ml-[4.5rem] mb-1.5 space-y-1">
          {momentum && <MomentumPills m={momentum} />}
          {explanation && (
            <div className="mt-1 ml-0 rounded bg-[rgba(22,29,38,0.6)] border border-[rgba(28,39,54,0.5)] px-2 py-1.5">
              <p className="text-[11px] font-medium text-[#d4a015]">{explanation.short}</p>
              <p className="text-[10px] text-[#5a6a7f] leading-relaxed mt-0.5">{explanation.detail}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function DecisionTimeline({ decisions }: { decisions: ExecutionDecision[] }) {
  if (!decisions?.length) {
    return (
      <Card className="border-[rgba(28,39,54,0.5)] bg-[#0f1419]/80">
        <CardHeader className="pb-2 pt-4 px-4">
          <CardTitle className="text-sm text-[#e6edf3]">Decision Log</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4 pt-0">
          <p className="text-xs text-[#5a6a7f]">No decisions yet</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-[rgba(28,39,54,0.5)] bg-[#0f1419]/80">
      <CardHeader className="pb-2 pt-4 px-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm text-[#e6edf3]">Decision Log</CardTitle>
          <span className="text-[10px] text-[#5a6a7f] font-mono">{decisions.length} decisions</span>
        </div>
      </CardHeader>
      <CardContent className="px-4 pb-4 pt-0">
        <div className="space-y-0 max-h-80 overflow-y-auto">
          {decisions.map((d) => (
            <DecisionRow key={d.id} d={d} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
