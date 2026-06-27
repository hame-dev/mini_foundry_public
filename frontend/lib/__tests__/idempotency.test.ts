import { describe, expect, it } from "vitest";
import { idempotencyKey } from "@/lib/idempotency";

describe("idempotencyKey", () => {
  it("uses the default prefix", () => {
    expect(idempotencyKey()).toMatch(/^mf_[0-9a-f]+$/);
  });

  it("honors a custom prefix", () => {
    expect(idempotencyKey("job")).toMatch(/^job_[0-9a-f]+$/);
  });

  it("produces unique keys", () => {
    const keys = new Set(Array.from({ length: 50 }, () => idempotencyKey()));
    expect(keys.size).toBe(50);
  });
});
