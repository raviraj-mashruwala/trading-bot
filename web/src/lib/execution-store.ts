import { create } from "zustand";
import type { SessionResult, WsEvent, TickerHealth, ExecutionDecision } from "@/types";

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
  tickerHealth: TickerHealth | null;
  recentDecisions: ExecutionDecision[];
  handleEvent: (event: WsEvent) => void;
  reset: () => void;
}

export const useExecutionStore = create<ExecutionStore>((set) => ({
  status: "idle",
  mode: null,
  fills: [],
  sessionResult: null,
  tickerHealth: null,
  recentDecisions: [],

  handleEvent: (event: WsEvent) => {
    const { type, data } = event;

    if (type === "exec.started") {
      set({
        status: "running",
        mode: (data.mode as string) ?? null,
        fills: [],
        sessionResult: null,
        recentDecisions: [],
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
      return;
    }

    if (type === "ticker_health") {
      set({ tickerHealth: data as unknown as TickerHealth });
      return;
    }

    if (type === "decision") {
      const decision = data as unknown as ExecutionDecision;
      set((state) => ({
        recentDecisions: [decision, ...state.recentDecisions].slice(0, 50),
      }));
      return;
    }
  },

  reset: () => set({
    status: "idle",
    mode: null,
    fills: [],
    sessionResult: null,
    tickerHealth: null,
    recentDecisions: [],
  }),
}));
