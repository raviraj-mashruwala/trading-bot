"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: "📊" },
  { href: "/analysis", label: "Analysis", icon: "🔬" },
  { href: "/settings", label: "Settings", icon: "⚙️" },
  { href: "/history", label: "History", icon: "📜" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-screen w-56 flex-col border-r bg-muted/40 px-3 py-4">
      <div className="mb-6 px-2 text-lg font-semibold">Trading Bot</div>
      <nav className="flex flex-col gap-1">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors hover:bg-accent",
              pathname === item.href && "bg-accent font-medium"
            )}
          >
            <span>{item.icon}</span>
            {item.label}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
