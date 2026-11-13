import { test, expect } from "@playwright/test";
import {
  deferred, fixtureAuthorization, fixturePassword, fillSetupOwner, mockOnboarding, noStoredSecrets,
} from "./onboarding-fixtures";

test("unconfigured setup is visibly disabled and never initializes", async ({ page }) => {
  const state = await mockOnboarding(page, null);
  state.setup.authorization_configured = false;
  await page.goto("/setup");
  await expect(page.getByTestId("setup-unconfigured")).toContainText("Setup is disabled");
  await expect(page.getByTestId("setup-form")).toHaveCount(0);
  expect(state.calls.some((call) => call.path === "/setup/initialize")).toBe(false);
  state.setup.authorization_configured = true;
  await page.getByRole("button", { name: "Check instance status" }).click();
  await expect(page.getByTestId("setup-form")).toBeVisible();
  await expect(page.getByTestId("setup-next-1")).toBeEnabled();
});

test("an initialized incomplete instance cannot be overwritten or called complete", async ({ page }) => {
  const state = await mockOnboarding(page, null);
  state.setup.is_initialized = true;
  await page.goto("/setup");
  await expect(page.getByTestId("setup-initialized")).toContainText("cannot replace existing data");
  await expect(page.getByTestId("setup-form")).toHaveCount(0);
  await expect(page.getByTestId("setup-complete")).toHaveCount(0);
  expect(state.calls.some((call) => call.path === "/setup/initialize")).toBe(false);
});

test("missing status flags and untrusted status errors fail closed without tenant identity", async ({ page }) => {
  const state = await mockOnboarding(page, null);
  state.setupResponse = { is_setup_complete: false, tenant_id: "private-tenant-marker", company_name: "private-company-marker" };
  await page.goto("/setup");
  await expect(page.getByTestId("setup-status-error")).toContainText("Initialization is disabled");
  await expect(page.getByTestId("setup-form")).toHaveCount(0);
  expect(await page.locator("body").evaluate((body) => (body.textContent || "").includes("private-company-marker"))).toBe(false);
  state.setupResponse = null;
  await page.getByRole("button", { name: "Retry status check" }).click();
  await expect(page.getByTestId("setup-form")).toBeVisible();
});

test("completed status presents sign-in without exposing legacy identity or creating an account", async ({ page }) => {
  const state = await mockOnboarding(page, null);
  state.setupResponse = { is_setup_complete: true, is_initialized: true, authorization_configured: true,
    tenant_id: "private-tenant-marker", company_name: "private-company-marker" };
  await page.goto("/setup");
  await expect(page.getByTestId("setup-complete")).toContainText("Sign in");
  await expect(page.getByTestId("setup-form")).toHaveCount(0);
  expect(await page.locator("body").evaluate((body) => (body.textContent || "").includes("private-company-marker"))).toBe(false);
  expect(state.calls.some((call) => call.path === "/setup/initialize")).toBe(false);
});

for (const [label, authorization] of [
  ["missing", ""], ["short", "test-only-short"], ["malformed", "invalid,operator authorization"], ["low diversity", "a".repeat(40)],
]) {
  test(`${label} private authorization is rejected locally with no initialization request`, async ({ page }) => {
    const state = await mockOnboarding(page, null);
    await page.goto("/setup");
    await fillSetupOwner(page, fixturePassword, authorization);
    await page.getByTestId("setup-next-2").click();
    await expect(page.getByTestId("setup-authorization")).toHaveAttribute("aria-invalid", "true");
    await expect(page.getByTestId("setup-warehouse-0")).toHaveCount(0);
    expect(state.calls.some((call) => call.path === "/setup/initialize")).toBe(false);
  });
}

for (const [label, password] of [
  ["11 characters", "a".repeat(11)], ["six surrogate-pair characters", "\u{1f600}".repeat(6)], ["75 UTF-8 bytes", "\u754c".repeat(25)],
]) {
  test(`setup rejects ${label} instead of advertising an unsafe password policy`, async ({ page }) => {
    const state = await mockOnboarding(page, null);
    await page.goto("/setup");
    await fillSetupOwner(page, password);
    await page.getByTestId("setup-next-2").click();
    await expect(page.getByTestId("setup-admin-password")).toHaveAttribute("aria-invalid", "true");
    await expect(page.getByText("Use at least 12 characters and no more than 72 UTF-8 bytes.", { exact: true })).toBeVisible();
    expect(state.calls.some((call) => call.path === "/setup/initialize")).toBe(false);
  });
}

test("optional company email is validated and trimmed blanks become null with a private header only", async ({ page }) => {
  const state = await mockOnboarding(page, null);
  await page.goto("/setup");
  await page.getByTestId("setup-company-name").fill(" Fixture Company ");
  await page.getByTestId("setup-email").fill("not-an-email");
  await page.getByTestId("setup-next-1").click();
  await expect(page.getByTestId("setup-email")).toHaveAttribute("aria-invalid", "true");
  await page.getByTestId("setup-email").fill("   ");
  await page.getByTestId("setup-phone").fill("   ");
  await page.getByTestId("setup-legal-name").fill("   ");
  await fillSetupOwner(page);
  await page.getByTestId("setup-next-2").click();
  await page.getByLabel("Code *", { exact: true }).fill(" WH-1 ");
  await page.getByLabel("Name *", { exact: true }).fill(" Main Warehouse ");
  await page.getByLabel("City", { exact: true }).fill("  ");
  await page.getByTestId("setup-finish").click();
  await expect(page).toHaveURL(/\/login$/);
  const call = state.calls.find((item) => item.path === "/setup/initialize");
  expect(call?.body).toEqual({ company_name: "Fixture Company", legal_name: null, gstin: null, phone: null,
    email: null, address: null, currency: "INR", admin_email: "owner@fixture.test", admin_password: "[redacted]",
    admin_full_name: "Fixture Owner", warehouses: [{ code: "WH-1", name: "Main Warehouse", city: null, state: null, pincode: null }] });
  expect(call?.authorizationMatches).toBe(true);
  expect(call?.passwordMatches).toBe(true);
  expect(state.calls.filter((item) => item.hasSetupAuthorization).map((item) => item.path)).toEqual(["/setup/initialize"]);
  expect(state.calls.some((item) => item.path === "/auth/login")).toBe(false);
  expect(await noStoredSecrets(page)).toBe(true);
});

test("warehouse codes are trimmed, unique and case-sensitive and a 72-byte password is accepted", async ({ page }) => {
  const state = await mockOnboarding(page, null);
  state.expectedPassword = "\u754c".repeat(24);
  await page.goto("/setup");
  await fillSetupOwner(page, state.expectedPassword);
  await page.getByTestId("setup-next-2").click();
  await page.getByTestId("setup-warehouse-add").click();
  await page.locator("#setup-warehouse-1-code").fill(" WH-1 ");
  await page.locator("#setup-warehouse-1-name").fill("Second warehouse");
  await page.getByTestId("setup-finish").click();
  await expect(page.getByText("Use 1 to 50 warehouses with names and trimmed, unique, case-sensitive codes.")).toBeVisible();
  expect(state.calls.some((call) => call.path === "/setup/initialize")).toBe(false);
  await page.locator("#setup-warehouse-1-code").fill("wh-1");
  await page.getByTestId("setup-finish").click();
  await expect(page).toHaveURL(/\/login$/);
  const call = state.calls.find((item) => item.path === "/setup/initialize");
  expect(call?.passwordMatches).toBe(true);
  expect((call?.body?.warehouses as { code: string }[]).map((warehouse) => warehouse.code)).toEqual(["WH-1", "wh-1"]);
});

for (const [code, message] of [[403, "authorization was rejected"], [422, "Private inputs have been cleared"]] as const) {
  test(`setup ${code} clears both private inputs and sanitizes reflected errors`, async ({ page }) => {
    const state = await mockOnboarding(page, null);
    state.initializeStatus = code;
    state.errorDetail = `${fixtureAuthorization} ${fixturePassword} raw-validation-marker`;
    await page.goto("/setup");
    await fillSetupOwner(page);
    await page.getByTestId("setup-next-2").click();
    await page.getByTestId("setup-finish").click();
    await expect(page.getByTestId("setup-error")).toContainText(message);
    await expect(page.getByTestId("setup-admin-password")).toHaveValue("");
    await expect(page.getByTestId("setup-authorization")).toHaveValue("");
    expect(await page.locator("body").evaluate((body) => (body.textContent || "").includes("raw-validation-marker"))).toBe(false);
    expect(await noStoredSecrets(page)).toBe(true);
    await expect(page.getByTestId("setup-complete")).toHaveCount(0);
    expect(state.calls.filter((call) => call.path === "/setup/initialize")).toHaveLength(1);
  });
}

for (const [code, stateId] of [[409, "setup-initialized"], [503, "setup-unconfigured"]] as const) {
  test(`setup ${code} disables further initialization even when a stale status says empty`, async ({ page }) => {
    const state = await mockOnboarding(page, null);
    state.initializeStatus = code;
    await page.goto("/setup");
    await fillSetupOwner(page);
    await page.getByTestId("setup-next-2").click();
    await page.getByTestId("setup-finish").click();
    await expect(page.getByTestId(stateId)).toBeVisible();
    await expect(page.getByTestId("setup-form")).toHaveCount(0);
    await expect(page.getByTestId("setup-complete")).toHaveCount(0);
    expect(state.calls.filter((call) => call.path === "/setup/initialize")).toHaveLength(1);
  });
}

test("uncertain setup is not retried automatically or shown as complete", async ({ page }) => {
  const state = await mockOnboarding(page, null);
  state.abortMutation = true;
  await page.goto("/setup");
  await fillSetupOwner(page);
  await page.getByTestId("setup-next-2").click();
  await page.getByTestId("setup-finish").click();
  await expect(page.getByTestId("setup-error")).toContainText("could not be confirmed");
  await expect(page.getByTestId("setup-admin-password")).toHaveValue("");
  await expect(page.getByTestId("setup-authorization")).toHaveValue("");
  await expect(page.getByTestId("setup-complete")).toHaveCount(0);
  expect(state.calls.filter((call) => call.path === "/setup/initialize")).toHaveLength(1);
});

for (const [label, status, complete] of [["unexpected success status", 200, true], ["incomplete success receipt", 201, false]] as const) {
  test(`${label} cannot produce a false setup completion claim`, async ({ page }) => {
    const state = await mockOnboarding(page, null);
    state.initializeStatus = status;
    state.setupResponse = { ...state.setup, tenant_id: null, company_name: null };
    state.initializeResponse = { is_setup_complete: complete, is_initialized: true, authorization_configured: true };
    await page.goto("/setup"); await fillSetupOwner(page); await page.getByTestId("setup-next-2").click();
    await page.getByTestId("setup-finish").click();
    await expect(page.getByTestId("setup-error")).toContainText("could not be confirmed");
    await expect(page.getByTestId("setup-complete")).toHaveCount(0);
    await expect(page.getByText("Setup complete. Please sign in.", { exact: true })).toHaveCount(0);
    await expect(page.getByTestId("setup-admin-password")).toHaveValue("");
    await expect(page.getByTestId("setup-authorization")).toHaveValue("");
  });
}

test("pending initialization disables duplicate intent and clears private inputs before awaiting", async ({ page }) => {
  const state = await mockOnboarding(page, null);
  const gate = deferred(); state.mutationGate = gate.promise;
  await page.goto("/setup");
  await fillSetupOwner(page);
  await page.getByTestId("setup-next-2").click();
  await page.getByTestId("setup-finish").evaluate((button: HTMLButtonElement) => { button.click(); button.click(); });
  await expect(page.getByTestId("setup-finish")).toBeDisabled();
  await expect(page.getByTestId("setup-back-3")).toBeDisabled();
  await expect.poll(() => state.calls.filter((call) => call.path === "/setup/initialize").length).toBe(1);
  expect(await noStoredSecrets(page)).toBe(true);
  gate.resolve();
  await expect(page).toHaveURL(/\/login$/);
});

test("late anonymous bootstrap and status never expose a writable unverified setup", async ({ page }) => {
  const state = await mockOnboarding(page, null);
  const me = deferred(); const status = deferred();
  state.meGate = me.promise; state.statusGate = status.promise;
  await page.goto("/setup");
  await expect(page.getByText("Checking instance and session status...")).toBeVisible();
  await expect(page.getByTestId("setup-form")).toHaveCount(0);
  me.resolve();
  await expect.poll(() => state.calls.filter((call) => call.path === "/auth/refresh").length).toBe(1);
  await expect(page.getByTestId("setup-form")).toHaveCount(0);
  status.resolve();
  await expect(page.getByTestId("setup-form")).toBeVisible();
  expect(state.calls.some((call) => call.path === "/setup/initialize")).toBe(false);
});

test("an unmounted setup cannot navigate or publish a late initialization result", async ({ page }) => {
  const state = await mockOnboarding(page, null);
  const gate = deferred(); state.mutationGate = gate.promise;
  const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.name));
  await page.goto("/setup");
  await fillSetupOwner(page);
  await page.getByTestId("setup-next-2").click();
  await page.getByTestId("setup-finish").click();
  await expect.poll(() => state.calls.filter((call) => call.path === "/setup/initialize").length).toBe(1);
  await page.goto("/login");
  gate.resolve();
  await expect(page.getByTestId("login-form")).toBeVisible();
  await expect(page.getByText("Setup complete. Please sign in.", { exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
  expect(await noStoredSecrets(page)).toBe(true);
});

test("setup stays labelled and contained on narrow screens with large text", async ({ page }) => {
  await mockOnboarding(page, null);
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto("/setup");
  await page.addStyleTag({ content: "html { font-size: 200%; }" });
  await fillSetupOwner(page);
  await page.getByLabel("Setup authorization *", { exact: true }).focus();
  await expect(page.getByTestId("setup-authorization")).toBeFocused();
  await page.getByTestId("setup-next-2").click();
  await page.getByLabel("State", { exact: true }).fill("Fixture state");
  await page.getByTestId("setup-finish").scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
