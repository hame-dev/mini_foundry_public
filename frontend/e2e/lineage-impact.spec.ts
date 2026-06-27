import { expect, test } from "@playwright/test";

test("resource lineage shows hidden-node notice without hidden names", async ({ page, context }) => {
  await context.addCookies([{ name: "mf_session", value: "e2e", domain: "localhost", path: "/" }]);
  await page.route("**/api/v1/**", (route) => {
    const url = route.request().url();
    if (url.includes("/auth/me")) return route.fulfill({ status: 200, json: { id: "u1", email: "admin@mini.local", roles: ["admin"] } });
    if (url.includes("/system/health")) return route.fulfill({ status: 200, json: { status: "ok", checks: {} } });
    if (url.includes("/platform/resources/r1/impact")) return route.fulfill({ status: 200, json: { resource_id: "r1", depth: 2, columns: [], affected: [], by_type: {}, edge_count: 0, hidden_nodes: { count: 0 } } });
    if (url.includes("/platform/resources/r1/lineage")) {
      return route.fulfill({
        status: 200,
        json: {
          resource_id: "r1",
          direction: "both",
          depth: 2,
          branch_name: null,
          include_columns: false,
          hidden_nodes: { count: 1 },
          nodes: [{ id: "r1", resource_type: "dataset", name: "Visible dataset", object_id: "d1" }],
          edges: [{ id: "e1", source_resource_id: null, target_resource_id: "r1", edge_type: "hidden_to_dataset", metadata: {} }],
        },
      });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.goto("/data/lineage/r1");
  await expect(page.getByText(/1 hidden/i)).toBeVisible();
  await expect(page.getByText("Visible dataset", { exact: true })).toBeVisible();
  await expect(page.getByText(/secret/i)).toHaveCount(0);
});
