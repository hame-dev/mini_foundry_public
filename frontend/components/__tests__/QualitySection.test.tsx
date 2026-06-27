import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ApiError } from "@/lib/api";

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, apiFetch: (...args: unknown[]) => apiFetchMock(...args) };
});

import { QualitySection } from "@/components/data/QualitySection";

describe("QualitySection", () => {
  beforeEach(() => apiFetchMock.mockReset());

  it("shows the empty state when there are no rules", async () => {
    apiFetchMock.mockResolvedValue([]); // rules / results / freshness all resolve empty
    render(<QualitySection datasetId="d1" />);
    await waitFor(() => expect(screen.getByText(/no quality rules yet/i)).toBeInTheDocument());
  });

  it("surfaces a permission-denied error instead of crashing", async () => {
    // The first call (quality-rules) rejects; results/freshness resolve.
    apiFetchMock
      .mockRejectedValueOnce(new ApiError(403, "missing capability: view_metadata"))
      .mockResolvedValue([]);
    render(<QualitySection datasetId="d1" />);
    await waitFor(() => expect(screen.getByText(/missing capability/i)).toBeInTheDocument());
  });
});
