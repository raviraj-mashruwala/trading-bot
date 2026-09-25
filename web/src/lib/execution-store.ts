import { create } from "zustand";
import type { SessionResult, WsEvent } from "@/types";

interface Fill {
  symbol: string;
  fill_price: number;
  quantity: number;
}

interface ExecutionStore {
  status: "idle" | "running" | "done";
  mode: string | null;
  fills: Fill[];
  sessionResult: SessionResult | null;
  handleEvent: (event: WsEvent) => void;
  reset: () => void;
}

export const useExecutionStore = create<ExecutionStore>((set) => ({
  status: "idle",
  mode: null,
  fills: [],
  sessionResult: null,

  handleEvent: (event: WsEvent) => {
    const { type, data } = event;

    if (type === "exec.started") {
      set({
        status: "running",
        mode: (data.mode as string) ?? null,
        fills: [],
        sessionResult: null,
      });
      return;
    }

    if (type === "exec.entry_filled") {
      set((state) => ({
        fills: [...state.fills, {
          symbol: data.symbol as string,
          fill_price: data.fill_price as number,
          quantity: data.quantity as number,
        }],
      }));
      return;
    }

    if (type === "exec.session_done") {
      set({
        status: "done",
        sessionResult: {
          total_pnl: data.total_pnl as number,
          trades_count: data.trades_count as number,
          mode: data.mode as string,
        },
      });
    }
  },

  reset: () => set({ status: "idle", mode: null, fills: [], sessionResult: null }),
}));
