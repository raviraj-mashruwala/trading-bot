"use client";

interface ScoutAlert {
  timestamp: string;
  symbol: string;
  signal: string;
  direction: string;
  confidence: number;
  entry_price: number;
  target_price: number;
  stop_price: number;
  reasoning: string;
}

export function ScoutAlerts({ alerts }: { alerts: ScoutAlert[] }) {
  if (!alerts || alerts.length === 0) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="h-1.5 w-1.5 rounded-full bg-[#d4a015] animate-pulse" />
        <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          Scout Signals (observe only)
        </h3>
      </div>
      <div className="grid gap-2">
        {alerts.map((alert, i) => {
          const isLong = alert.direction === "long";
          const pctTarget = Math.abs(
            ((alert.target_price - alert.entry_price) / alert.entry_price) * 100
          ).toFixed(2);
          const pctStop = Math.abs(
            ((alert.stop_price - alert.entry_price) / alert.entry_price) * 100
          ).toFixed(2);
          const time = alert.timestamp.split("T")[1]?.slice(0, 5) ?? "";

          return (
            <div
              key={`${alert.symbol}-${alert.signal}-${i}`}
              className="flex items-start justify-between rounded-lg border border-border/30 bg-card/50 px-3 py-2"
            >
              <div className="space-y-0.5">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-foreground">
                    {alert.symbol}
                  </span>
                  <span
                    className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
                      isLong
                        ? "bg-[#2da44e]/10 text-[#2da44e]"
                        : "bg-[#f85149]/10 text-[#f85149]"
                    }`}
                  >
                    {alert.direction.toUpperCase()}
                  </span>
                  <span className="text-[10px] text-muted-foreground/60 font-mono">
                    {alert.signal.replace("_", " ")}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">{alert.reasoning}</p>
              </div>
              <div className="text-right text-xs space-y-0.5 shrink-0 ml-4">
                <p className="text-muted-foreground">{time}</p>
                <p className="text-foreground/80">
                  {alert.entry_price.toFixed(2)} T:{pctTarget}% S:{pctStop}%
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
