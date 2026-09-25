"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: "grid" },
  { href: "/analysis", label: "Analysis", icon: "scan" },
  { href: "/trading", label: "Trading", icon: "activity" },
  { href: "/settings", label: "Settings", icon: "sliders" },
  { href: "/history", label: "History", icon: "clock" },
];

const ICONS: Record<string, React.ReactNode> = {
  grid: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="1.5" y="1.5" width="5" height="5" rx="1"/><rect x="9.5" y="1.5" width="5" height="5" rx="1"/><rect x="1.5" y="9.5" width="5" height="5" rx="1"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/></svg>,
  scan: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="8" cy="8" r="6"/><line x1="8" y1="2" x2="8" y2="8"/><line x1="8" y1="8" x2="12" y2="10"/></svg>,
  activity: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><polyline points="1,8 4,8 6,3 8,13 10,6 12,8 15,8"/></svg>,
  sliders: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><line x1="3" y1="2" x2="3" y2="14"/><line x1="8" y1="2" x2="8" y2="14"/><line x1="13" y1="2" x2="13" y2="14"/><circle cx="3" cy="5" r="1.5" fill="currentColor"/><circle cx="8" cy="10" r="1.5" fill="currentColor"/><circle cx="13" cy="7" r="1.5" fill="currentColor"/></svg>,
  clock: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="8" cy="8" r="6"/><line x1="8" y1="4" x2="8" y2="8"/><line x1="8" y1="8" x2="11" y2="8"/></svg>,
};

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-screen w-52 flex-col border-r border-border/50 bg-[#0d1017] px-3 py-5">
      <div className="mb-8 flex items-center gap-2 px-3">
        <div className="h-2 w-2 rounded-full bg-amber-500" />
        <span className="text-sm font-semibold tracking-wide text-foreground/90">TRADINGBOT</span>
      </div>
      <nav className="flex flex-col gap-0.5">
        {NAV_ITEMS.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-[13px] font-medium transition-all duration-150",
                active
                  ? "bg-amber-500/10 text-amber-400"
                  : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
              )}
            >
              {active && (
                <span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-amber-500" />
              )}
              <span className="opacity-80">{ICONS[item.icon]}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="mt-auto px-3 pb-2">
        <div className="text-[11px] text-muted-foreground/50">v0.1.0</div>
      </div>
    </aside>
  );
}
