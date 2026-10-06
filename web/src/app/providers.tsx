"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { createWsManager } from "@/lib/ws";
import { usePipelineStore } from "@/lib/store";
import { useExecutionStore } from "@/lib/execution-store";

let browserQueryClient: QueryClient | undefined;

function getQueryClient() {
  if (typeof window === "undefined") return new QueryClient();
  browserQueryClient ??= new QueryClient({
    defaultOptions: { queries: { staleTime: 30_000, refetchInterval: 30_000 } },
  });
  return browserQueryClient;
}

export function Providers({ children }: { children: ReactNode }) {
  const handleEvent = usePipelineStore((s) => s.handleEvent);
  const handleExecEvent = useExecutionStore((s) => s.handleEvent);

  const setWsConnected = usePipelineStore((s) => s.setWsConnected);

  useEffect(() => {
    const wsUrl = `ws://${window.location.hostname}:8000/ws`;
    const ws = createWsManager(
      wsUrl,
      (event) => {
        handleEvent(event);
        handleExecEvent(event);
      },
      (status) => setWsConnected(status === "connected"),
    );
    ws.connect();
    return () => ws.disconnect();
  }, [handleEvent, handleExecEvent, setWsConnected]);

  return (
    <QueryClientProvider client={getQueryClient()}>
      {children}
    </QueryClientProvider>
  );
}
