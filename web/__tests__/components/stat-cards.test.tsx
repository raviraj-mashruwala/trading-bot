import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatCards } from "@/components/dashboard/stat-cards";
import type { TradeStats } from "@/types";

const mockStats: TradeStats = {
  trade_count: 15,
  win_rate: 0.6,
  total_pnl: 5200.50,
  avg_pnl: 346.70,
  max_drawdown: -1200,
  best_day: 2000,
  worst_day: -800,
};

describe("StatCards", () => {
  it("renders all 4 stat cards with data", () => {
    render(<StatCards stats={mockStats} />);
    expect(screen.getByText("Total P&L")).toBeInTheDocument();
    expect(screen.getByText("Win Rate")).toBeInTheDocument();
    expect(screen.getByText("Trades")).toBeInTheDocument();
    expect(screen.getByText("Max Drawdown")).toBeInTheDocument();
    expect(screen.getByText(/5,20[01]/)).toBeInTheDocument();
    expect(screen.getByText("60%")).toBeInTheDocument();
    expect(screen.getByText("15")).toBeInTheDocument();
  });

  it("renders zeros gracefully when no trades", () => {
    const empty: TradeStats = { trade_count: 0, win_rate: 0, total_pnl: 0, avg_pnl: 0, max_drawdown: 0, best_day: 0, worst_day: 0 };
    render(<StatCards stats={empty} />);
    expect(screen.getByText("0%")).toBeInTheDocument();
  });
});
