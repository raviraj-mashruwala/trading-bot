"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

export function TopBar() {
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: api.getHealth,
    refetchInterval: 15_000,
  });

  const isHealthy = health?.api === "ok" && health?.database === "ok";

  return (
    <header className="flex h-14 items-center justify-between border-b px-6">
      <div />
      <div className="flex items-center gap-3">
        <Badge variant={isHealthy ? "default" : "destructive"}>
          {isHealthy ? "API Connected" : "API Disconnected"}
        </Badge>
      </div>
    </header>
  );
}
