"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function TopBar() {
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: api.getHealth,
    refetchInterval: 15_000,
  });

  const isHealthy = health?.api === "ok" && health?.database === "ok";

  return (
    <header className="flex h-12 items-center justify-end border-b border-border/50 px-6">
      <div className="flex items-center gap-2">
        <span className="relative flex h-2 w-2">
          {isHealthy && (
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
          )}
          <span className={`relative inline-flex h-2 w-2 rounded-full ${isHealthy ? "bg-emerald-500" : "bg-red-500"}`} />
        </span>
        <span className="text-xs text-muted-foreground">
          {isHealthy ? "Connected" : "Disconnected"}
        </span>
      </div>
    </header>
  );
}
