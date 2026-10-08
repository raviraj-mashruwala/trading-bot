"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { TradeLeg } from "@/types";

function LegCard({ leg }: { leg: TradeLeg }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <Card className="cursor-pointer" onClick={() => setExpanded(!expanded)}>
      <CardHeader className="flex flex-row items-center justify-between py-3">
        <CardTitle className="text-sm font-medium">
          {leg.symbol} — {leg.direction.toUpperCase()}
        </CardTitle>
        <div className="flex gap-2">
          <Badge variant="outline">{leg.strategy}</Badge>
          <Badge variant="secondary">{(leg.confidence * 100).toFixed(0)}%</Badge>
        </div>
      </CardHeader>
      {expanded && (
        <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-2 pt-0 text-sm">
          <div>Entry: ₹{leg.entry_price.toFixed(2)}</div>
          <div>Stop Loss: ₹{leg.stop_loss.toFixed(2)}</div>
          <div>Target 1: ₹{leg.target_1.toFixed(2)}</div>
          <div>Target 2: ₹{leg.target_2.toFixed(2)}</div>
          <div>Qty: {leg.quantity}</div>
          <div>Risk: ₹{leg.risk_amount.toFixed(0)}</div>
          <div className="col-span-2 text-muted-foreground">{leg.reasoning}</div>
        </CardContent>
      )}
    </Card>
  );
}

export function PlanLegsCards({ legs }: { legs: TradeLeg[] }) {
  if (legs.length === 0) return null;

  return (
    <div className="mt-6">
      <h3 className="mb-3 text-lg font-semibold">Trade Plan</h3>
      <div className="flex flex-col gap-2">
        {legs.map((leg, i) => (
          <LegCard key={`${leg.symbol}-${i}`} leg={leg} />
        ))}
      </div>
    </div>
  );
}
