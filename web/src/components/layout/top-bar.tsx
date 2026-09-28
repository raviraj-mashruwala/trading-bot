"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { KiteConnectButton } from "@/components/auth/kite-connect-button";

export function TopBar() {
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: api.getHealth,
    refetchInterval: 15_000,
  });

  const isHealthy = health?.api === "ok" && health?.database === "ok";

  return (
    <header className="flex h-12 items-center justify-end border-b border-border/50 px-6">
      <div className="flex items-center gap-4">
        <KiteConnectButton />
      </div>
      <div className="flex items-center gap-2 ml-4">
        <span className="relative flex h-2 w-2">
          {isHealthy && (
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#2da44e] opacity-75" />
          )}
          <span className={`relative inline-flex h-2 w-2 rounded-full ${isHealthy ? "bg-[#2da44e]" : "bg-[#f85149]"}`} />
        </span>
        <span className="text-xs text-muted-foreground">
          {isHealthy ? "Connected" : "Disconnected"}
        </span>
      </div>
    </header>
  );
}
