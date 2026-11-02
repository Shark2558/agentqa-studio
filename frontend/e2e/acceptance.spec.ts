import { expect, test } from "@playwright/test";

/** M0.5 acceptance: sign in → create the demo project → start the pipeline → see live events.
 *  Needs: the backend on 8700 with the built app, the demo portals on 8800/8810, and an owner account whose
 *  credentials are given as AGENTQA_E2E_EMAIL / AGENTQA_E2E_PASSWORD (never committed). */
const email = process.env.AGENTQA_E2E_EMAIL ?? "";
const password = process.env.AGENTQA_E2E_PASSWORD ?? "";

test.skip(!email || !password, "set AGENTQA_E2E_EMAIL and AGENTQA_E2E_PASSWORD to run the acceptance flow");

test("sign in, create the demo, start the pipeline and watch it live", async ({ page }) => {
  await page.goto("/app/");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();

  await page.getByRole("button", { name: "Try the demo" }).click();
  await expect(page.getByRole("heading", { name: "Demo Certificate Portal" })).toBeVisible();

  const run = page.getByRole("button", { name: /Run full pipeline|Running…/ });
  if (await run.isEnabled()) await run.click();
  await expect(page.getByRole("heading", { name: "Live View" })).toBeVisible();
  await expect(page.locator(".evt").first()).toBeVisible({ timeout: 120_000 });
  await expect(page.locator(".agent").first()).toBeVisible();
});
