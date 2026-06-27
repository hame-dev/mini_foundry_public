import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Badge, StatusPill } from "@/components/foundry/controls";

describe("StatusPill", () => {
  it("renders the status text and computes the tone class", () => {
    const { container } = render(<StatusPill status="Succeeded" />);
    expect(screen.getByText("Succeeded")).toBeInTheDocument();
    expect(container.querySelector(".status-pill")).toHaveClass("badge-success");
  });

  it("lets an explicit tone override the computed one", () => {
    const { container } = render(<StatusPill status="Succeeded" tone="danger" />);
    expect(container.querySelector(".status-pill")).toHaveClass("badge-danger");
  });
});

describe("Badge", () => {
  it("applies the tone class and renders children", () => {
    const { container } = render(<Badge tone="warning">3</Badge>);
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(container.querySelector(".badge")).toHaveClass("badge-warning");
  });
});
