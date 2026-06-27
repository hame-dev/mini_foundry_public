import { test, expect } from "@playwright/test";

// Golden path: the login form posts to /auth/login and lands on /workspace.
// All API calls are mocked so the test needs no backend.
test("logs in and navigates to the workspace", async ({ page }) => {
  await page.route("**/api/v1/**", (route) => {
    const url = route.request().url();
    if (url.includes("/auth/login")) {
      // Set the session cookie the middleware requires for guarded routes.
      return route.fulfill({
        status: 200,
        headers: { "set-cookie": "mf_session=e2e; Path=/; SameSite=Lax" },
        json: { token_type: "cookie" },
      });
    }
    if (url.includes("/auth/me")) {
      return route.fulfill({ status: 200, json: { id: "u1", email: "admin@mini.local", roles: ["admin"] } });
    }
    // Everything the workspace shell loads → harmless empty payloads.
    return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.goto("/login");
  await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page).toHaveURL(/\/workspace/);
});
