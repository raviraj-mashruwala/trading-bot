import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigSection } from "@/components/settings/config-section";

describe("ConfigSection", () => {
  it("renders all fields with current values", () => {
    render(<ConfigSection name="general" fields={{ mode: "paper", capital: 400000 }} onSave={vi.fn()} />);
    expect(screen.getByDisplayValue("paper")).toBeInTheDocument();
    expect(screen.getByDisplayValue("400000")).toBeInTheDocument();
  });

  it("calls onSave with updated values on submit", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ConfigSection name="general" fields={{ capital: 400000 }} onSave={onSave} />);
    const input = screen.getByDisplayValue("400000");
    await user.clear(input);
    await user.type(input, "500000");
    await user.click(screen.getByRole("button", { name: /save/i }));
    expect(onSave).toHaveBeenCalledWith({ capital: 500000 });
  });

  it("sends only changed fields, not unchanged ones", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ConfigSection name="risk" fields={{ max_risk_per_trade_pct: 0.01, max_daily_loss_pct: 0.02 }} onSave={onSave} />);
    const input = screen.getByDisplayValue("0.01");
    await user.clear(input);
    await user.type(input, "0.015");
    await user.click(screen.getByRole("button", { name: /save/i }));
    expect(onSave).toHaveBeenCalledWith({ max_risk_per_trade_pct: 0.015 });
  });
});
