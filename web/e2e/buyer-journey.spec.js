// @ts-check
import { expect, test } from "@playwright/test";

function uniqueEmail(prefix) {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 10000)}@e2e.kavachsaathi.test`;
}

test("buyer can sign up, browse, add to cart, verify address, and place a real order", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByPlaceholder("Try Saree, Kurti or Search by Product Code")).toBeVisible();

  // Sign up as a new buyer -- exercises real POST /v1/auth/signup, not a hardcoded B-001.
  await page.getByRole("button", { name: "Login" }).click();
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.getByLabel("Full name").fill("E2E Test Buyer");
  await page.getByLabel("Email").fill(uniqueEmail("buyer"));
  await page.getByLabel("Password").fill("correct-horse-1");
  await page.getByRole("button", { name: "Create account" }).click();
  // Real bcrypt hashing + a real DB round trip -- slower than Playwright's 5s default.
  await expect(page.getByRole("button", { name: "Login" })).not.toBeVisible({ timeout: 40_000 });

  // Find the golden demo product and open its real, deep-linkable product page.
  await page.getByPlaceholder("Try Saree, Kurti or Search by Product Code").fill("Maroon");
  const productCard = page.getByRole("button", { name: /^Open .*Maroon.*Kurta/i }).first();
  await expect(productCard).toBeVisible();
  await page.goto("/products/P-001");
  await expect(page).toHaveURL(/\/products\/P-001$/);
  await expect(page.getByRole("main", { name: "Maroon Floral Cotton Kurta" })).toBeVisible({ timeout: 30_000 });

  // Select a size (the product has a real size chart) and add to a real cart_items row.
  const sizeButtons = page.locator(".size-row button");
  await expect(sizeButtons.first()).toBeVisible();
  await sizeButtons.first().click();
  await page.getByRole("button", { name: "Add to cart" }).click();
  await expect(page.getByText(/added to cart/i)).toBeVisible();
  const productQuantity = page.getByRole("main").getByLabel("Current quantity");
  await expect(productQuantity).toHaveText("1");

  // Quantity controls write through to the backend and render the returned cart.
  await page.getByRole("main").getByRole("button", { name: "Increase quantity" }).click();
  await expect(productQuantity).toHaveText("2");
  await page.getByRole("main").getByRole("button", { name: "Decrease quantity" }).click();
  await expect(productQuantity).toHaveText("1");

  // The full product page exposes a direct cart action; checkout remains a real
  // POST /v1/orders, not a fixture confirmation.
  await page.getByRole("button", { name: /Go to cart/i }).click();
  await expect(page.getByRole("dialog", { name: "Shopping cart" })).toBeVisible();
  await page.getByRole("button", { name: "Continue to secure checkout" }).click();
  await page.getByRole("button", { name: "+ Add New Address" }).click();
  await page.getByRole("button", { name: "Add New Address" }).click();
  await page.getByLabel("Recipient Name *").fill("E2E Test Buyer");
  await page.getByLabel("Phone Number *").fill("+919999999999");
  await page.getByRole("button", { name: "Verify via OTP" }).click();
  await page.getByPlaceholder("123456").fill(process.env.E2E_OTP_CODE || "123456");
  await page.getByRole("button", { name: "Verify Code" }).click();
  await expect(page.getByText("Phone number verified successfully!")).toBeVisible();
  await page.getByLabel("Address Line 1 *").fill("Hanuman Mandir ke peeche, gali no. 3");
  await page.getByLabel("Address Line 2 (Optional)").fill("Near main market");
  await page.getByLabel("Locality (Optional)").fill("Bilaspur");
  await page.getByLabel("City *").fill("Bilaspur");
  await page.getByLabel("District *").fill("Bilaspur");
  await page.getByLabel("State *").fill("Chhattisgarh");
  await page.getByLabel("Postal PIN *").fill("495001");
  await page.getByRole("button", { name: "Save Address" }).click();
  await expect(page.getByText("Address saved successfully!")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("dialog", { name: "Manage Addresses" }).getByRole("button", { name: "Close" }).click();

  await page.getByRole("button", { name: /Open cart with/ }).click();
  await page.getByRole("button", { name: "Continue to secure checkout" }).click();
  await page.getByRole("button", { name: "Confirm availability & place COD order" }).click();

  // The success heading must show the real order ID this run created, not a hardcoded
  // golden ID -- a fixture-cheat regression would show "Order O-GOLDEN is protected"
  // even for a brand-new order.
  const heading = page.locator(".success-state h3");
  await expect(heading).toBeVisible({ timeout: 20_000 });
  await expect(heading).toHaveText(/^Order O-[A-Z0-9]{10} is protected$/);
  await expect(heading).not.toHaveText("Order O-GOLDEN is protected");
  await expect(page.getByRole("button", { name: "Go to My Orders" })).toBeVisible();
});
