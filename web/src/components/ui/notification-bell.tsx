"use client";

import { useState, useRef, useEffect } from "react";
import { useNotificationStore } from "@/lib/notification-store";

const typeColor: Record<string, string> = {
  info: "text-[#d4a015]",
  success: "text-[#2da44e]",
  error: "text-[#f85149]",
};

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const notifications = useNotificationStore((s) => s.notifications);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const count = notifications.length;

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="relative flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted/50 hover:text-foreground transition-colors"
        title="Notifications"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M4 6a4 4 0 0 1 8 0c0 3 1.5 4.5 2 5H2c.5-.5 2-2 2-5Z" />
          <path d="M6 11v.5a2 2 0 0 0 4 0V11" />
        </svg>
        {count > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-[#d4a015] text-[8px] font-bold text-black">
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-10 z-50 w-72 rounded-lg border border-[rgba(28,39,54,0.5)] bg-[#161d26] overflow-hidden">
          <div className="px-3 py-2 border-b border-[rgba(28,39,54,0.5)]">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-[#5a6a7f]">Notifications</span>
          </div>
          <div className="max-h-64 overflow-y-auto">
            {notifications.length === 0 ? (
              <div className="px-3 py-4 text-center text-xs text-[#5a6a7f]">No recent notifications</div>
            ) : (
              notifications.map((n) => (
                <div key={n.id} className="px-3 py-2 border-b border-[rgba(28,39,54,0.3)] last:border-0">
                  <p className={`text-[11px] font-semibold ${typeColor[n.type] ?? "text-[#5a6a7f]"}`}>{n.title}</p>
                  <p className="text-[10px] text-[#5a6a7f] mt-0.5">{n.message}</p>
                  <p className="text-[9px] text-[#5a6a7f]/50 mt-0.5">
                    {new Date(n.timestamp).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
                  </p>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
