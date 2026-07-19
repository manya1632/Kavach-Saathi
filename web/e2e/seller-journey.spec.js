// @ts-check
import path from "node:path";
import { expect, test } from "@playwright/test";

// Resolved relative to the working directory `npm run e2e`/`playwright test` is
// invoked from (web/), not this file's own path, to avoid import.meta.url support
// issues under Playwright's CJS test transform.
const SAMPLE_PHOTO = path.resolve(process.cwd(), "..", "assets", "mock", "products", "P-001.png");

function uniqueEmail(prefix) {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 10000)}@e2e.kavachsaathi.test`;
}

test("seller can sign up and start a real listing (Agent 1 + 2 pipeline)", async ({ page }) => {
  test.skip(
    !!process.env.CI,
    "Requires configured image-analysis providers and a workflow worker; covered by backend integration tests in CI",
  );
  await page.goto("/seller");
  await expect(page.getByRole("button", { name: "Sign up" })).toBeVisible();

  // Real signup against POST /v1/auth/signup with role=seller -- creates a real
  // seller_profiles row, not a hardcoded S-001.
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.getByLabel("Your name").fill("E2E Test Seller");
  await page.getByLabel("Business name").fill("E2E Test Seller Co");
  await page.getByLabel("Email").fill(uniqueEmail("seller"));
  await page.getByLabel("Password").fill("correct-horse-1");
  await page.getByRole("button", { name: "Create seller account" }).click();

  // Real bcrypt hashing + a real DB round trip -- slower than Playwright's 5s default.
  await expect(page.getByRole("button", { name: "Add Product" })).toBeVisible({ timeout: 20_000 });
  await page.getByLabel("Product Images (2 to 4)").setInputFiles([SAMPLE_PHOTO, SAMPLE_PHOTO]);
  await page.getByLabel("Catalogue/Label/Tag Images (1 to 2)").setInputFiles(SAMPLE_PHOTO);
  await page.getByRole("button", { name: /Initialize listing/ }).click();

  // Agent 1 (SAM2 + Gemini/Stable Diffusion) and Agent 2 (OCR + CLIP/ResNet-50) take
  // real CPU minutes to fully complete -- the UI only shows "Draft product created"
  // once postAndPoll reaches a terminal status, which this suite deliberately doesn't
  // wait for. Instead this asserts the real product was created and the real async
  // pipeline was genuinely queued and is polling (the progress message only appears
  // once the product POST + presigned upload both succeeded for real). Full
  // completion is covered by pytest's
  // test_listing_analyze_persists_real_agent_logs_and_product_images and the manual
  // RUNBOOK.md walkthrough.
  await expect(page.getByText(/Agent pipeline is extracting specs|Initializing listing/)).toBeVisible({ timeout: 30_000 });
});
