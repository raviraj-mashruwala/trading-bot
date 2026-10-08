"use client";

import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DecisionTimeline } from "@/components/trading/decision-timeline";
import type { Trade, ExecutionDecision } from "@/types";

export default function TradeDetailPage() {
  const params = useSearchParams();
  const symbol = params.get("symbol");
  const date = params.get("date");

  const { data: trades } = useQuery({
    queryKey: ["trades", 9999],
    queryFn: () => api.getTrades(9999),
    enabled: !!symbol && !!date,
  });

  const { data: scorecard } = useQuery({
    queryKey: ["scorecards", date],
    queryFn: () => api.getScorecards(date!),
    enabled: !!date,
  });

  const { data: execStatus } = useQuery({
    queryKey: ["execution-status"],
    queryFn: api.getExecutionStatus,
  });

  if (!symbol || !date) {
    return (
      <div className="py-12 text-center text-sm text-[#5a6a7f]">
        Missing symbol or date.{" "}
        <Link href="/history" className="text-[#d4a015] hover:text-[#e5b320]">Back to History</Link>
      </div>
    );
  }

  const trade = trades?.find((t: Trade) => t.symbol === symbol && t.trade_date === date);
  const sc = scorecard?.find((s) => s.symbol === symbol);
  const decisions = (execStatus?.decision_log ?? []).filter(
    (d: ExecutionDecision) => d.symbol === symbol && d.trade_date === date
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Link href="/history" className="text-[#5a6a7f] hover:text-[#c9d1d9] text-xs">
          ← History
        </Link>
        <h1 className="text-xl font-semibold">{symbol}</h1>
        <span className="text-xs text-[#5a6a7f] font-mono">{date}</span>
      </div>

      {trade ? (
        <Card className="border-[rgba(28,39,54,0.5)] bg-[#0f1419]/80">
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-sm text-[#e6edf3]">Trade Summary</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 pt-0">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-[#5a6a7f]">Direction</span>
                <span className={`font-medium ${trade.direction === "long" ? "text-[#2da44e]" : "text-[#f85149]"}`}>
                  {trade.direction.toUpperCase()}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#5a6a7f]">Strategy</span>
                <span className="text-[#c9d1d9]">{trade.strategy}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#5a6a7f]">Entry</span>
                <span className="font-mono text-[#c9d1d9]">₹{trade.entry_price.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#5a6a7f]">Exit</span>
                <span className="font-mono text-[#c9d1d9]">₹{trade.exit_price.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#5a6a7f]">Quantity</span>
                <span className="font-mono text-[#c9d1d9]">{trade.quantity}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#5a6a7f]">P&L</span>
                <span className={`font-mono font-semibold ${trade.pnl >= 0 ? "text-[#2da44e]" : "text-[#f85149]"}`}>
                  {trade.pnl >= 0 ? "+" : ""}₹{trade.pnl.toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#5a6a7f]">Exit Reason</span>
                <span className="text-[#c9d1d9]">{trade.exit_reason}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#5a6a7f]">Mode</span>
                <span className="text-[#c9d1d9] uppercase">{trade.mode}</span>
              </div>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="py-8 text-center text-sm text-[#5a6a7f]">Trade not found</div>
      )}

      {sc && (
        <Card className="border-[rgba(28,39,54,0.5)] bg-[#0f1419]/80">
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-sm text-[#e6edf3]">Scorecard</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 pt-0">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-[#5a6a7f]">R-Multiple</span>
                <span className={`font-mono ${sc.r_multiple >= 0 ? "text-[#2da44e]" : "text-[#f85149]"}`}>
                  {sc.r_multiple.toFixed(2)}R
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#5a6a7f]">Predicted RR</span>
                <span className="font-mono text-[#c9d1d9]">{sc.predicted_rr.toFixed(1)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#5a6a7f]">Entry Slippage</span>
                <span className="font-mono text-[#c9d1d9]">{sc.entry_slippage.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#5a6a7f]">Hit Target</span>
                <span className={sc.hit_target ? "text-[#2da44e]" : "text-[#f85149]"}>
                  {sc.hit_target ? "Yes" : "No"}
                </span>
              </div>
              {sc.thesis && (
                <div className="col-span-full">
                  <span className="text-[#5a6a7f]">Thesis: </span>
                  <span className="text-[#c9d1d9]">{sc.thesis}</span>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {decisions.length > 0 && (
        <DecisionTimeline decisions={decisions} />
      )}
    </div>
  );
}
