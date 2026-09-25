import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PositionCard } from "@/components/trading/position-card";
import type { ExecutionPosition } from "@/types";

const position: ExecutionPosition = {
  symbol: "RELIANCE",
  direction: "long",
  quantity: 10,
  entry_price: 2450.0,
  current_stop: 2420.0,
  target_1_booked: true,
  pnl: 0,
  last_price: 2480.0,
  unrealised_pnl: 300.0,
};

describe("PositionCard", () => {
  it("renders position details", () => {
    render(<PositionCard position={position} />);
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText(/long/i)).toBeInTheDocument();
    expect(screen.getByText(/2,450/)).toBeInTheDocument();
    expect(screen.getByText(/2,480/)).toBeInTheDocument();
  });

  it("shows green for positive unrealised P&L", () => {
    render(<PositionCard position={position} />);
    const pnl = screen.getByTestId("unrealised-pnl");
    expect(pnl.className).toContain("text-emerald");
  });

  it("shows red for negative unrealised P&L", () => {
    const losing = { ...position, last_price: 2430, unrealised_pnl: -200 };
    render(<PositionCard position={losing} />);
    const pnl = screen.getByTestId("unrealised-pnl");
    expect(pnl.className).toContain("text-red");
  });

  it("shows T1 booked status", () => {
    render(<PositionCard position={position} />);
    expect(screen.getByText(/Booked/)).toBeInTheDocument();
  });

  it("shows T1 not booked", () => {
    render(<PositionCard position={{ ...position, target_1_booked: false }} />);
    expect(screen.getByText(/Pending/)).toBeInTheDocument();
  });
});
