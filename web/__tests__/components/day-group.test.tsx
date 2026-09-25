import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DayGroup } from "@/components/history/day-group";
import type { Trade } from "@/types";

const trade: Trade = {
  trade_date: "2026-09-25",
  symbol: "RELIANCE",
  strategy: "breakout",
  direction: "long",
  quantity: 10,
  entry_price: 2450.50,
  exit_price: 2480.00,
  pnl: 295.00,
  exit_reason: "target_1",
  status: "closed",
  mode: "paper",
  entered_at: "2026-09-25T09:30:00+05:30",
  exited_at: "2026-09-25T11:15:00+05:30",
};

describe("DayGroup", () => {
  it("renders date header with trade count and daily P&L", () => {
    render(<DayGroup date="2026-09-25" trades={[trade]} dailyPnl={295} />);
    expect(screen.getByText("2026-09-25")).toBeInTheDocument();
    expect(screen.getByText("1 trade")).toBeInTheDocument();
    expect(screen.getByText(/295/)).toBeInTheDocument();
  });

  it("expands to show trade table on click", async () => {
    const user = userEvent.setup();
    render(<DayGroup date="2026-09-25" trades={[trade]} dailyPnl={295} />);
    await user.click(screen.getByText("2026-09-25"));
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText("breakout")).toBeInTheDocument();
  });

  it("renders zero trades gracefully", () => {
    render(<DayGroup date="2026-09-25" trades={[]} dailyPnl={0} />);
    expect(screen.getByText("0 trades")).toBeInTheDocument();
  });
});
