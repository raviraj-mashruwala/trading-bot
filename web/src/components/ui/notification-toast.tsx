"use client";

import { useNotificationStore } from "@/lib/notification-store";

const typeStyles: Record<string, string> = {
  info: "border-[rgba(212,160,21,0.3)] bg-[rgba(212,160,21,0.08)]",
  success: "border-[rgba(45,164,78,0.3)] bg-[rgba(45,164,78,0.08)]",
  error: "border-[rgba(248,81,73,0.3)] bg-[rgba(248,81,73,0.08)]",
};

const titleColor: Record<string, string> = {
  info: "text-[#d4a015]",
  success: "text-[#2da44e]",
  error: "text-[#f85149]",
};

export function NotificationToasts() {
  const notifications = useNotificationStore((s) => s.notifications);
  const dismiss = useNotificationStore((s) => s.dismiss);

  if (!notifications.length) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-72">
      {notifications.map((n) => (
        <div
          key={n.id}
          className={`rounded-lg border px-3 py-2.5 shadow-lg animate-in slide-in-from-right-5 ${typeStyles[n.type] ?? typeStyles.info}`}
        >
          <div className="flex items-start justify-between gap-2">
            <div>
              <p className={`text-xs font-semibold ${titleColor[n.type] ?? titleColor.info}`}>
                {n.title}
              </p>
              <p className="text-[11px] text-[#c9d1d9] mt-0.5">{n.message}</p>
            </div>
            <button
              onClick={() => dismiss(n.id)}
              className="text-[#5a6a7f] hover:text-[#c9d1d9] text-xs shrink-0 mt-0.5"
            >
              ✕
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
