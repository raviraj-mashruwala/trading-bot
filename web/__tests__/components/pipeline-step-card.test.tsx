import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PipelineStepCard } from "@/components/analysis/pipeline-step-card";

describe("PipelineStepCard", () => {
  it("renders step label with pending state", () => {
    render(<PipelineStepCard label="Fetch universe" stepNumber={1} status="pending" data={null} />);
    expect(screen.getByText("Fetch universe")).toBeInTheDocument();
  });

  it("shows amber styling for active state", () => {
    render(<PipelineStepCard label="Filter candidates" stepNumber={2} status="active" data={null} />);
    const card = screen.getByTestId("step-card");
    expect(card.className).toContain("border-amber");
  });

  it("expands to show data when complete and clicked", async () => {
    const user = userEvent.setup();
    render(<PipelineStepCard label="Fetch universe" stepNumber={1} status="complete" data={{ count: 500 }} />);
    await user.click(screen.getByText("Fetch universe"));
    expect(screen.getByText(/500/)).toBeInTheDocument();
  });

  it("shows error styling for failed state", () => {
    render(<PipelineStepCard label="Failed step" stepNumber={3} status="failed" data={null} />);
    const card = screen.getByTestId("step-card");
    expect(card.className).toContain("border-red");
  });

  it("renders complete state when mounted after event already processed", () => {
    render(<PipelineStepCard label="Fetch universe" stepNumber={1} status="complete" data={{ count: 200 }} />);
    const card = screen.getByTestId("step-card");
    expect(card.className).toContain("border-emerald");
  });
});
