"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function KiteConnectButton() {
  const { data: status, isLoading } = useQuery({
    queryKey: ["kite-status"],
    queryFn: api.getKiteStatus,
    refetchInterval: 30_000,
  });

  const handleConnect = async () => {
    try {
      const { login_url } = await api.getKiteLoginUrl();
      window.location.href = login_url;
    } catch {
      // Kite API not available — fail silently, button stays red
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-[#0f1419] text-[#5a6a7f] text-xs font-medium">
        <div className="w-2 h-2 rounded-full bg-[#5a6a7f] animate-pulse" />
        Kite
      </div>
    );
  }

  if (status?.authenticated) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-[#0f1419] text-xs font-medium">
        <div className="w-2 h-2 rounded-full bg-[#2da44e]" />
        <span className="text-[#2da44e]">Kite Connected</span>
      </div>
    );
  }

  return (
    <button
      onClick={handleConnect}
      className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-[#d4a015]/10 text-[#d4a015] text-xs font-medium hover:bg-[#d4a015]/20 transition-colors cursor-pointer"
    >
      <div className="w-2 h-2 rounded-full bg-[#f85149]" />
      Connect Kite
    </button>
  );
}
