import { expect, test } from "@playwright/test";

test("app publish review publishes a branch snapshot", async ({ page, context }) => {
  await context.addCookies([{ name: "mf_session", value: "e2e", domain: "localhost", path: "/" }]);
  await page.route("**/api/v1/**", (route) => {
    const url = route.request().url();
    if (url.includes("/auth/me")) return route.fulfill({ status: 200, json: { id: "u1", email: "admin@mini.local", roles: ["admin"] } });
    if (url.includes("/system/health")) return route.fulfill({ status: 200, json: { status: "ok", checks: {} } });
    if (url.includes("/applications/app1/preview")) {
      return route.fulfill({ status: 200, json: { id: "app1", name: "Ops app", pages: [{ title: "Home", page_type: "standard", object_type: null, config: { widgets: [] }, position: 0 }], config: {}, published_at: null, published_version: null, mode: "preview", notices: [] } });
    }
    if (url.includes("/applications/app1/publish")) {
      expect(url).toContain("branch_name=main");
      return route.fulfill({ status: 200, json: { id: "app1", name: "Ops app", description: null, config: {}, status: "published", pages: [], updated_at: new Date().toISOString(), published_at: new Date().toISOString() } });
    }
    if (url.includes("/applications/app1")) {
      return route.fulfill({ status: 200, json: { id: "app1", name: "Ops app", description: null, config: {}, status: "draft", pages: [], updated_at: new Date().toISOString(), published_at: null } });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.goto("/apps/builder/app1/publish");
  await expect(page.getByRole("heading", { name: /ops app/i })).toBeVisible();
  await page.getByRole("button", { name: /^publish$/i }).click();
  await expect(page.getByText(/^Published /)).toBeVisible();
});
