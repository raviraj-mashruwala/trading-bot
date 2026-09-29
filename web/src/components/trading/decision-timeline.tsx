import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ExecutionDecision } from "@/types";

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
};

function formatTime(timestamp: string): string {
  try {
    const d = new Date(timestamp);
    return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  } catch {
    return timestamp.slice(11, 19);
  }
}

export function DecisionTimeline({ decisions }: { decisions: ExecutionDecision[] }) {
  if (!decisions?.length) {
    return (
      <Card className="border-border/50 bg-card/80">
        <CardHeader className="pb-2 pt-4 px-4">
          <CardTitle className="text-sm">Decision Log</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4 pt-0">
          <p className="text-xs text-muted-foreground">No decisions yet</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-border/50 bg-card/80">
      <CardHeader className="pb-2 pt-4 px-4">
        <CardTitle className="text-sm">Decision Log</CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-4 pt-0">
        <div className="space-y-1 max-h-64 overflow-y-auto">
          {decisions.map((d) => (
            <div key={d.id} className="flex items-start gap-2 text-xs">
              <span className="text-muted-foreground font-mono w-[4.5rem] shrink-0">
                {formatTime(d.timestamp)}
              </span>
              <span className="font-medium w-20 shrink-0">{d.symbol}</span>
              <span className={`font-semibold shrink-0 ${typeColor[d.decision_type] ?? "text-foreground"}`}>
                {d.decision_type}
              </span>
              {d.escalated === 1 && (
                <span className="rounded bg-purple-500/15 px-1 py-0.5 text-[10px] font-semibold text-purple-500 shrink-0">
                  AI
                </span>
              )}
              <span className="text-muted-foreground truncate">{d.reason}</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
