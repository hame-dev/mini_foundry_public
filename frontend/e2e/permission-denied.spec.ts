import { test, expect } from "@playwright/test";

// A 403 from a guarded resource must surface a safe error state, not a crash.
test("shows an error state when the API returns 403", async ({ page, context }) => {
  // The middleware requires a session cookie to reach guarded routes.
  await context.addCookies([{ name: "mf_session", value: "e2e", domain: "localhost", path: "/" }]);
  await page.route("**/api/v1/**", (route) => {
    const url = route.request().url();
    if (url.includes("/auth/me")) {
      return route.fulfill({ status: 200, json: { id: "u1", email: "a@b.c", roles: ["admin"] } });
    }
    if (url.includes("/governance/roles")) {
      return route.fulfill({ status: 403, json: { detail: "missing capability: manage" } });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.goto("/governance/roles");
  await expect(page.getByText(/missing capability|unable to load roles/i)).toBeVisible();
});
