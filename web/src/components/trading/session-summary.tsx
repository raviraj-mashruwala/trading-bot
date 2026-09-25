import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { SessionResult } from "@/types";

function fmt(n: number): string {
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString("en-IN", { maximumFractionDigits: 0 });
  return n < 0 ? `-₹${formatted}` : `₹${formatted}`;
}

export function SessionSummary({ result }: { result: SessionResult }) {
  return (
    <Card className="border-2 border-dashed">
      <CardHeader><CardTitle className="text-sm">Session Complete</CardTitle></CardHeader>
      <CardContent className="flex items-center gap-6 text-sm">
        <div>
          <span className="text-muted-foreground">Total P&L: </span>
          <span className={`font-bold ${result.total_pnl >= 0 ? "text-green-600" : "text-red-600"}`}>
            {fmt(result.total_pnl)}
          </span>
        </div>
        <div>
          <span className="text-muted-foreground">Trades: </span>
          <span className="font-bold">{result.trades_count}</span>
        </div>
        <Badge variant="secondary">{result.mode}</Badge>
      </CardContent>
    </Card>
  );
}
