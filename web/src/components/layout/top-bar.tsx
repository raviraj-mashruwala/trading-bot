"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { KiteConnectButton } from "@/components/auth/kite-connect-button";
import { KeepAwake } from "@/components/dashboard/keep-awake";
import { Sheet } from "@/components/ui/sheet";
import { SidebarNav } from "@/components/layout/sidebar";

export function TopBar() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: api.getHealth,
    refetchInterval: 15_000,
  });

  const isHealthy = health?.api === "ok" && health?.database === "ok";

  return (
    <>
      <header className="flex h-12 items-center border-b border-border/50 px-4 md:px-6">
        <button
          className="md:hidden mr-3 flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted/50 hover:text-foreground"
          onClick={() => setMobileMenuOpen(true)}
        >
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
            <line x1="3" y1="5" x2="15" y2="5" />
            <line x1="3" y1="9" x2="15" y2="9" />
            <line x1="3" y1="13" x2="15" y2="13" />
          </svg>
        </button>

        <div className="flex items-center gap-4 ml-auto">
          <KeepAwake />
          <KiteConnectButton />
        </div>
        <div className="flex items-center gap-2 ml-4">
          <span className="relative flex h-2 w-2">
            {isHealthy && (
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#2da44e] opacity-75" />
            )}
            <span className={`relative inline-flex h-2 w-2 rounded-full ${isHealthy ? "bg-[#2da44e]" : "bg-[#f85149]"}`} />
          </span>
          <span className="text-xs text-muted-foreground hidden sm:inline">
            {isHealthy ? "Connected" : "Disconnected"}
          </span>
        </div>
      </header>

      <Sheet open={mobileMenuOpen} onClose={() => setMobileMenuOpen(false)} side="left">
        <div className="flex h-full flex-col px-3 py-5">
          <SidebarNav onNavigate={() => setMobileMenuOpen(false)} />
        </div>
      </Sheet>
    </>
  );
}
