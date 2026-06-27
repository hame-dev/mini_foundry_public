import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, ApiError } from "@/lib/api";

function mockFetch(status: number, body: unknown, ok = status < 400) {
  return vi.fn(async () => ({
    ok,
    status,
    statusText: "x",
    json: async () => body,
  })) as unknown as typeof fetch;
}

describe("apiFetch", () => {
  beforeEach(() => {
    document.cookie = "";
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns parsed JSON on success", async () => {
    global.fetch = mockFetch(200, { hello: "world" });
    await expect(apiFetch("/ping")).resolves.toEqual({ hello: "world" });
  });

  it("throws ApiError with parsed detail on failure", async () => {
    global.fetch = mockFetch(400, { detail: "bad input" });
    await expect(apiFetch("/x")).rejects.toMatchObject({ status: 400, message: "bad input" });
    await expect(apiFetch("/x")).rejects.toBeInstanceOf(ApiError);
  });

  it("adds the CSRF header for mutations when the cookie is present", async () => {
    document.cookie = "mf_csrf=tok123";
    const fetchMock = mockFetch(200, {});
    global.fetch = fetchMock;
    await apiFetch("/x", { method: "POST", body: JSON.stringify({}) });
    const headers = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1].headers as Headers;
    expect(headers.get("X-CSRF-Token")).toBe("tok123");
  });

  it("redirects to /login on 401 in the browser", async () => {
    const original = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { pathname: "/somewhere", href: "" },
    });
    global.fetch = mockFetch(401, { detail: "no session" });
    await expect(apiFetch("/x")).rejects.toBeInstanceOf(ApiError);
    expect(window.location.href).toBe("/login");
    Object.defineProperty(window, "location", { configurable: true, value: original });
  });
});
