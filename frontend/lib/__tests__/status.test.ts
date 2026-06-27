import { describe, expect, it } from "vitest";
import { statusTone, toneBadgeClass } from "@/lib/status";

describe("statusTone", () => {
  it("maps known statuses case-insensitively", () => {
    expect(statusTone("Succeeded")).toBe("success");
    expect(statusTone("FAILED")).toBe("danger");
    expect(statusTone(" running ")).toBe("info");
    expect(statusTone("merged")).toBe("branch");
  });

  it("falls back to neutral for null/unknown", () => {
    expect(statusTone(null)).toBe("neutral");
    expect(statusTone(undefined)).toBe("neutral");
    expect(statusTone("totally-made-up")).toBe("neutral");
  });
});

describe("toneBadgeClass", () => {
  it("returns the matching badge class per tone", () => {
    expect(toneBadgeClass("success")).toBe("badge-success");
    expect(toneBadgeClass("warning")).toBe("badge-warning");
    expect(toneBadgeClass("danger")).toBe("badge-danger");
    expect(toneBadgeClass("info")).toBe("badge-info");
    expect(toneBadgeClass("branch")).toBe("badge-branch");
    expect(toneBadgeClass("masked")).toBe("badge-masked");
  });

  it("returns empty string for neutral", () => {
    expect(toneBadgeClass("neutral")).toBe("");
  });
});
