import { create } from "zustand";
import type { WsEvent } from "@/types";

interface Notification {
  id: number;
  type: "info" | "success" | "error";
  title: string;
  message: string;
  timestamp: number;
}

interface NotificationStore {
  notifications: Notification[];
  handleEvent: (event: WsEvent) => void;
  dismiss: (id: number) => void;
}

let nextId = 1;

function push(
  set: (fn: (s: NotificationStore) => Partial<NotificationStore>) => void,
  type: Notification["type"],
  title: string,
  message: string,
) {
  const id = nextId++;
  set((s) => ({
    notifications: [
      { id, type, title, message, timestamp: Date.now() },
      ...s.notifications,
    ].slice(0, 10),
  }));
  setTimeout(() => {
    set((s) => ({
      notifications: s.notifications.filter((n) => n.id !== id),
    }));
  }, 8000);
}

export const useNotificationStore = create<NotificationStore>((set) => ({
  notifications: [],

  handleEvent: (event: WsEvent) => {
    const { type, data } = event;

    if (type === "exec.auto_start") {
      const mode = (data.mode as string) ?? "paper";
      const legs = data.legs ?? 0;
      push(set, "info", "Auto Execution", `Starting ${mode} execution (${legs} legs)`);
    }
    if (type === "analysis.auto_start") {
      const td = (data.trade_date as string) ?? "";
      push(set, "info", "Auto Analysis", `Running analysis for ${td}`);
    }
    if (type === "sync.started") {
      push(set, "info", "Data Sync", "Daily sync started");
    }
    if (type === "sync.complete") {
      const stocks = data.stocks_synced ?? 0;
      const rows = data.rows_written ?? 0;
      push(set, "success", "Data Sync Complete", `${stocks} stocks, ${rows} rows synced`);
    }
    if (type === "review.started") {
      const td = (data.trade_date as string) || "";
      push(set, "info", "Nightly Review", td ? `Reviewing ${td}...` : "Running review...");
    }
    if (type === "review.complete") {
      const grade = (data.grade as string) || "?";
      const td = (data.trade_date as string) || "";
      const skipped = data.skipped as boolean;
      if (skipped) {
        push(set, "info", "Nightly Review", `Skipped ${td} — no trading activity`);
      } else {
        push(set, "success", "Nightly Review Complete", `${td} — Grade: ${grade}`);
      }
    }
    if (type === "review.failed") {
      push(set, "error", "Nightly Review", "Review failed — check server logs");
    }
  },

  dismiss: (id) =>
    set((s) => ({
      notifications: s.notifications.filter((n) => n.id !== id),
    })),
}));

export function toast(type: Notification["type"], title: string, message: string) {
  const { notifications, dismiss } = useNotificationStore.getState();
  const id = nextId++;
  useNotificationStore.setState({
    notifications: [
      { id, type, title, message, timestamp: Date.now() },
      ...notifications,
    ].slice(0, 10),
  });
  setTimeout(() => {
    useNotificationStore.setState((s) => ({
      notifications: s.notifications.filter((n) => n.id !== id),
    }));
  }, 8000);
}
