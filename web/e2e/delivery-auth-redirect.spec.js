// @ts-check
import { expect, test } from "@playwright/test";

const deliverySession = {
  access_token: "delivery-e2e-access-token",
  refresh_token: "delivery-e2e-refresh-token",
  token_type: "bearer",
  verification_sent: false,
  user: {
    id: "D-E2E",
    role: "delivery_boy",
    name: "E2E Delivery Person",
    email: "delivery@e2e.kavachsaathi.test",
    phone: null,
    preferred_language: "en",
    email_verified: true,
    phone_verified: false,
  },
};

async function mockDeliveryPortal(page) {
  await page.route("**/agent-api/v1/delivery/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
}

test("delivery-person login redirects to the delivery portal", async ({ page }) => {
  await mockDeliveryPortal(page);
  await page.route("**/agent-api/v1/auth/login", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(deliverySession) });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Login", exact: true }).click();
  const authForm = page.locator(".auth-form");
  await authForm.getByLabel("Email or phone").fill(deliverySession.user.email);
  await authForm.getByLabel("Password").fill("delivery-password");
  await authForm.getByRole("button", { name: "Log in", exact: true }).click();

  await page.waitForURL(/\/delivery$/, { waitUntil: "domcontentloaded", timeout: 30_000 });
  await expect(page.getByText("Kavach Saathi Delivery")).toBeVisible();
});

test("delivery-person signup redirects to the delivery portal", async ({ page }) => {
  await mockDeliveryPortal(page);
  await page.route("**/agent-api/v1/auth/signup", async (route) => {
    const payload = route.request().postDataJSON();
    expect(payload.role).toBe("delivery_boy");
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(deliverySession) });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Login", exact: true }).click();
  await page.getByRole("button", { name: "Sign up", exact: true }).click();
  const authForm = page.locator(".auth-form");
  await authForm.getByLabel("I am a").selectOption("delivery_boy");
  await authForm.getByLabel("Full name").fill(deliverySession.user.name);
  await authForm.getByRole("textbox", { name: "Email", exact: true }).fill(deliverySession.user.email);
  await authForm.getByLabel("Password").fill("delivery-password");
  await authForm.getByRole("button", { name: "Create account", exact: true }).click();

  await page.waitForURL(/\/delivery$/, { waitUntil: "domcontentloaded", timeout: 30_000 });
  await expect(page.getByText("Kavach Saathi Delivery")).toBeVisible();
});
