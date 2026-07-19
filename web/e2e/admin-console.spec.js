// @ts-check
import { expect, test } from "@playwright/test";

test("admin can log in and see real platform analytics", async ({ page }) => {
  await page.goto("/admin");
  await expect(page.getByLabel("Admin email")).toBeVisible();

  await page.getByLabel("Admin email").fill("admin@kavachsaathi.test");
  await page.getByLabel("Password").fill("KavachDemo@2026");
  await page.getByRole("button", { name: "Log in" }).click();

  // Real bcrypt password check + a real DB round trip -- slower than a 5s default.
  await expect(page.getByRole("button", { name: "Inspection Queue" })).toBeVisible({ timeout: 60_000 });

  // Real /v1/admin/analytics data, not a fixture -- Orders count must be a real number.
  const ordersStat = page.locator(".seller-stat-grid div", { hasText: "Orders" });
  await expect(ordersStat).toBeVisible();
  await expect(ordersStat.locator("strong")).not.toHaveText("0");

  await page.getByRole("button", { name: "Fraud Cases" }).click();
  await expect(page.getByRole("heading", { name: "Stolen-photo products" })).toBeVisible();

  await page.getByRole("button", { name: "Trust Override" }).click();
  await expect(page.getByLabel("Seller ID")).toBeVisible();
});

test("non-admin cannot see the admin console", async ({ page }) => {
  const uniqueEmail = `guard-${Date.now()}@e2e.kavachsaathi.test`;
  await page.goto("/");
  await page.getByRole("button", { name: "Login" }).click();
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.getByLabel("Full name").fill("Guard Buyer");
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(uniqueEmail);
  await page.getByLabel("Password").fill("correct-horse-1");
  await page.getByRole("button", { name: "Create account" }).click();
  // Real bcrypt hashing + a real DB round trip -- slower than Playwright's 5s default.
  await expect(page.getByRole("button", { name: "Login" })).not.toBeVisible({ timeout: 40_000 });

  // The buyer's own JWT is a real, valid token -- just for the wrong role. Reusing it
  // against /admin must be rejected, not silently grant access.
  await page.goto("/admin");
  await expect(page.getByLabel("Admin email")).toBeVisible();
});
