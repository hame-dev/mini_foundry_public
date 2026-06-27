import { expect, test } from "@playwright/test";

test("pipeline expectations route validates a branch-aware pipeline", async ({ page, context }) => {
  await context.addCookies([{ name: "mf_session", value: "e2e", domain: "localhost", path: "/" }]);
  await page.route("**/api/v1/**", (route) => {
    const url = route.request().url();
    if (url.includes("/auth/me")) return route.fulfill({ status: 200, json: { id: "u1", email: "admin@mini.local", roles: ["admin"] } });
    if (url.includes("/system/health")) return route.fulfill({ status: 200, json: { status: "ok", checks: {} } });
    if (url.includes("/pipelines/p1/validate")) return route.fulfill({ status: 200, json: { status: "ok", warnings: [], errors: [] } });
    if (url.includes("/pipelines/p1")) return route.fulfill({ status: 200, json: pipeline() });
    return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.goto("/build/pipelines/p1/expectations");
  const validation = page.waitForResponse((response) =>
    response.url().includes("/pipelines/p1/validate") && response.status() === 200,
  );
  await page.getByRole("button", { name: /validate/i }).click();
  await validation;
  await expect(page.getByRole("heading", { name: "No issues" })).toBeVisible();
  await expect(page.getByText("Validation completed without warnings.")).toBeVisible();
});

test("AI prompt preview surfaces redaction notices", async ({ page, context }) => {
  await context.addCookies([{ name: "mf_session", value: "e2e", domain: "localhost", path: "/" }]);
  await page.route("**/api/v1/**", (route) => {
    const url = route.request().url();
    if (url.includes("/auth/me")) return route.fulfill({ status: 200, json: { id: "u1", email: "admin@mini.local", roles: ["admin"] } });
    if (url.includes("/system/health")) return route.fulfill({ status: 200, json: { status: "ok", checks: {} } });
    if (url.includes("/ai/prompts/preview")) {
      return route.fulfill({ status: 200, json: { rendered_prompt: "email analyst@example.com", redacted_prompt: "email [REDACTED:email]", redactions: [{ type: "email", count: 1 }], permission_notices: [] } });
    }
    if (url.includes("/ai/prompts")) return route.fulfill({ status: 200, json: [] });
    return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.goto("/ai/prompts");
  await page.getByLabel(/name/i).fill("sql_guard");
  await page.getByLabel(/template/i).fill("email {{user.email}}");
  await page.getByRole("button", { name: /preview redaction/i }).click();
  await expect(page.getByText(/\[REDACTED:email\]/)).toBeVisible();
});

function pipeline() {
  return {
    id: "p1",
    name: "Branch pipeline",
    description: null,
    owner_id: "u1",
    ai_policy: "local_only",
    output_dataset_id: null,
    last_run_at: null,
    last_run_status: "draft",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    graph: {},
    nodes: [],
    edges: [],
    last_run_error: null,
  };
}
