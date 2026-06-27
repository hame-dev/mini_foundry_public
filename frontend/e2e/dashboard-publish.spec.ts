import { expect, test } from "@playwright/test";

test("dashboard publish route publishes an immutable viewer version", async ({ page, context }) => {
  await context.addCookies([{ name: "mf_session", value: "e2e", domain: "localhost", path: "/" }]);
  await page.route("**/api/v1/**", (route) => {
    const url = route.request().url();
    if (url.includes("/auth/me")) return route.fulfill({ status: 200, json: { id: "u1", email: "admin@mini.local", roles: ["admin"] } });
    if (url.includes("/system/health")) return route.fulfill({ status: 200, json: { status: "ok", checks: {} } });
    if (url.includes("/dashboards/d1/publish")) {
      expect(url).toContain("branch_name=main");
      return route.fulfill({ status: 200, json: dashboard(2) });
    }
    if (url.includes("/dashboards/d1")) return route.fulfill({ status: 200, json: dashboard(1) });
    return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.goto("/apps/dashboards/d1/publish");
  await expect(page.getByRole("heading", { name: /sales board/i })).toBeVisible();
  await page.getByRole("button", { name: /^publish$/i }).click();
  await expect(page.getByText(/published version 2/i)).toBeVisible();
});

function dashboard(version: number) {
  return {
    id: "d1",
    title: "Sales board",
    description: null,
    owner_id: "u1",
    dashboard_kind: "contour",
    published_version: version,
    published_at: null,
    draft_updated_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    layout: { version: 1, components: [], filters: [] },
    components: [],
    is_draft_view: true,
  };
}
