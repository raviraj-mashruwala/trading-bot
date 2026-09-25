"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { StepStatus } from "@/types";

const STATUS_STYLES: Record<StepStatus, string> = {
  pending: "border-muted-foreground/20 opacity-50",
  active: "border-yellow-500 bg-yellow-50",
  complete: "border-green-500 bg-green-50",
  failed: "border-red-500 bg-red-50",
};

const STATUS_BADGE: Record<StepStatus, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  pending: { label: "Pending", variant: "outline" },
  active: { label: "Running", variant: "default" },
  complete: { label: "Done", variant: "secondary" },
  failed: { label: "Failed", variant: "destructive" },
};

interface Props {
  label: string;
  status: StepStatus;
  data: Record<string, unknown> | null;
}

export function PipelineStepCard({ label, status, data }: Props) {
  const [expanded, setExpanded] = useState(false);
  const canExpand = status === "complete" && data !== null;

  return (
    <Card
      data-testid="step-card"
      className={cn("cursor-pointer transition-all", STATUS_STYLES[status])}
      onClick={() => canExpand && setExpanded(!expanded)}
    >
      <CardHeader className="flex flex-row items-center justify-between py-3">
        <CardTitle className="text-sm font-medium">{label}</CardTitle>
        <Badge variant={STATUS_BADGE[status].variant}>{STATUS_BADGE[status].label}</Badge>
      </CardHeader>
      {expanded && data && (
        <CardContent className="pt-0">
          <pre className="text-xs text-muted-foreground whitespace-pre-wrap">
            {JSON.stringify(data, null, 2)}
          </pre>
        </CardContent>
      )}
    </Card>
  );
}
