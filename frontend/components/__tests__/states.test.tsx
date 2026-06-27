import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { EmptyState, ErrorState, LoadingState, PermissionDenied } from "@/components/platform/States";

describe("platform States", () => {
  it("EmptyState renders title + detail", () => {
    render(<EmptyState title="No rows" detail="nothing here" />);
    expect(screen.getByText("No rows")).toBeInTheDocument();
    expect(screen.getByText("nothing here")).toBeInTheDocument();
  });

  it("ErrorState renders the message", () => {
    render(<ErrorState message="boom" />);
    expect(screen.getByText("boom")).toBeInTheDocument();
  });

  it("LoadingState renders a label", () => {
    render(<LoadingState label="Loading workers..." />);
    expect(screen.getByText("Loading workers...")).toBeInTheDocument();
  });

  it("PermissionDenied renders a denial message", () => {
    render(<PermissionDenied />);
    expect(screen.getByText(/permission denied/i)).toBeInTheDocument();
  });
});
