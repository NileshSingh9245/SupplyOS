import { test, expect, type Page } from "@playwright/test";
import axios, { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";
import { QueryClient } from "@tanstack/react-query";
import { api } from "../src/lib/api";
import { useAuth, type Role } from "../src/lib/auth";
import { canAccessStaffRoute } from "../src/lib/navigation";
import {
  accountPasswordSchema, createStaff, patchStaff, revokeStaffSessions, staffQuery, staffRequestError, staffScope,
  type StaffPatch,
} from "../src/lib/staff";
import {
  deferred, fixturePassword, fillStaff, mockOnboarding, noStoredSecrets, otherOwner, otherStaff, owner, staffMember,
} from "./onboarding-fixtures";

for (const role of ["warehouse_manager", "accountant", "delivery_partner", "customer"] as Role[]) {
  test(`${role} cannot see staff navigation or trigger a staff API request`, async ({ page }) => {
    const state = await mockOnboarding(page, { ...owner, role });
    await page.goto("/staff");
    await expect(page).not.toHaveURL(/\/staff$/);
    await expect(page.getByTestId("nav-staff")).toHaveCount(0);
    await expect(page.getByTestId("staff-page")).toHaveCount(0);
    expect(state.calls.some((call) => call.path.startsWith("/staff"))).toBe(false);
  });
}

for (const [label, user] of [["anonymous", null], ["inactive owner", { ...owner, is_active: false }]] as const) {
  test(`${label} cannot mount staff controls or make staff API calls`, async ({ page }) => {
    const state = await mockOnboarding(page, user);
    await page.goto("/staff");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByTestId("staff-page")).toHaveCount(0);
    expect(state.calls.some((call) => call.path.startsWith("/staff"))).toBe(false);
  });
}

test("the active owner has staff navigation and only supported account controls", async ({ page }) => {
  const state = await mockOnboarding(page);
  await page.goto("/staff");
  await expect(page.getByTestId("nav-staff")).toBeVisible();
  await expect(page.getByTestId(`staff-row-${staffMember.id}`)).toContainText("Warehouse manager");
  await expect(page.getByRole("button", { name: `Edit ${staffMember.full_name}`, exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /delete/i })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /invite|verify email|reset password/i })).toHaveCount(0);
  const call = state.calls.find((item) => item.path === "/staff");
  expect(new URLSearchParams(call?.query).get("page_size")).toBe("50");
  expect(new URLSearchParams(call?.query).get("page")).toBe("1");
});

test("staff loading, empty and redacted error states are distinct and retryable", async ({ page }) => {
  const state = await mockOnboarding(page);
  state.staff[owner.id] = []; state.totalStaff = 0;
  const gate = deferred(); state.staffGate = gate.promise;
  await page.goto("/staff");
  await expect(page.getByTestId("staff-loading")).toBeVisible();
  await expect(page.getByTestId("staff-empty")).toHaveCount(0);
  gate.resolve();
  await expect(page.getByTestId("staff-empty")).toBeVisible();
  state.staffStatus = 503; state.errorDetail = "raw-error-marker";
  await page.getByTestId("staff-refresh").click();
  await expect(page.getByTestId("staff-error")).toContainText("could not be confirmed");
  await expect(page.getByTestId("staff-new")).toBeDisabled();
  await expect(page.getByTestId("staff-empty")).toHaveCount(0);
  expect(await page.locator("body").evaluate((body) => (body.textContent || "").includes("raw-error-marker"))).toBe(false);
  state.staffStatus = 200; state.staff[owner.id] = [staffMember]; state.totalStaff = 1;
  await page.getByRole("button", { name: "Retry staff list" }).click();
  await expect(page.getByTestId(`staff-row-${staffMember.id}`)).toBeVisible();
});

test("staff paging uses the server envelope without stale page rows", async ({ page }) => {
  const state = await mockOnboarding(page); state.totalStaff = 51;
  await page.goto("/staff");
  await expect(page.getByTestId("staff-previous")).toBeDisabled();
  await page.getByTestId("staff-next").click();
  await expect(page.getByTestId("staff-pagination")).toContainText("Page 2 / 51");
  await expect(page.getByTestId(`staff-row-${staffMember.id}`)).toHaveCount(0);
  await expect(page.getByTestId(`staff-row-${otherStaff.id}`)).toBeVisible();
  await expect(page.getByTestId("staff-next")).toBeDisabled();
  await page.getByTestId("staff-previous").click();
  await expect(page.getByTestId(`staff-row-${staffMember.id}`)).toBeVisible();
  expect(state.calls.filter((call) => call.path === "/staff").some((call) => new URLSearchParams(call.query).get("page") === "2")).toBe(true);
});

test("staff creation requires holder confirmation, disables duplicate intent and sends only the safe API shape", async ({ page }) => {
  const state = await mockOnboarding(page);
  const gate = deferred(); state.mutationGate = gate.promise;
  await page.goto("/staff");
  await page.getByTestId("staff-new").click();
  await expect(page.getByTestId("staff-password")).toHaveValue("");
  expect(await page.getByTestId("staff-role").locator("option").evaluateAll((options) => options.map((option) => (option as HTMLOptionElement).value))).toEqual(["", "warehouse_manager", "accountant", "delivery_partner"]);
  await fillStaff(page);
  await page.getByTestId("staff-confirmed").uncheck();
  await expect(page.getByTestId("staff-submit")).toBeDisabled();
  await page.getByTestId("staff-confirmed").check();
  await page.getByTestId("staff-submit").evaluate((button: HTMLButtonElement) => { button.click(); button.click(); });
  await expect(page.getByTestId("staff-submit")).toBeDisabled();
  await expect(page.getByTestId("staff-password")).toHaveValue("");
  await expect(page.getByTestId("staff-cancel")).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("staff-modal")).toBeVisible();
  await expect.poll(() => state.calls.filter((call) => call.path === "/staff" && call.method === "POST").length).toBe(1);
  expect(await noStoredSecrets(page)).toBe(true);
  gate.resolve();
  await expect(page.getByTestId("staff-modal")).toHaveCount(0);
  const call = state.calls.find((item) => item.path === "/staff" && item.method === "POST");
  expect(call?.body).toEqual({ email: "new-staff@fixture.test", full_name: "New Fixture Staff", phone: null, role: "accountant", password: "[redacted]" });
  expect(call?.passwordMatches).toBe(true);
  expect(state.calls.some((item) => item.path === "/auth/login")).toBe(false);
  await expect(page.getByTestId("me-name")).toContainText(owner.full_name);
});

test("staff passwords enforce character and UTF-8 boundaries without generated credentials", async ({ page }) => {
  const state = await mockOnboarding(page);
  await page.goto("/staff"); await page.getByTestId("staff-new").click();
  await fillStaff(page, "a".repeat(11));
  await expect(page.getByTestId("staff-submit")).toBeDisabled();
  await page.getByTestId("staff-password").fill("\u{1f600}".repeat(6));
  await expect(page.getByTestId("staff-submit")).toBeDisabled();
  await page.getByTestId("staff-password").fill("\u754c".repeat(25));
  await expect(page.getByTestId("staff-submit")).toBeDisabled();
  expect(state.calls.some((call) => call.path === "/staff" && call.method === "POST")).toBe(false);
  state.expectedPassword = "\u754c".repeat(24);
  await page.getByTestId("staff-password").fill(state.expectedPassword);
  await page.getByTestId("staff-confirmed").check();
  await page.getByTestId("staff-submit").click();
  await expect(page.getByTestId("staff-modal")).toHaveCount(0);
  expect(state.calls.find((call) => call.path === "/staff" && call.method === "POST")?.passwordMatches).toBe(true);
});

for (const code of [409, 422]) {
  test(`staff creation ${code} clears the password and sanitizes every server error field`, async ({ page }) => {
    const state = await mockOnboarding(page); state.mutationStatus = code;
    state.errorDetail = `${fixturePassword} private-error-marker`;
    await page.goto("/staff"); await page.getByTestId("staff-new").click();
    await fillStaff(page); await page.getByTestId("staff-submit").click();
    await expect(page.getByTestId("staff-form-error")).toBeVisible();
    await expect(page.getByTestId("staff-password")).toHaveValue("");
    await expect(page.getByTestId("staff-submit")).toBeDisabled();
    expect(await page.locator("body").evaluate((body) => (body.textContent || "").includes("private-error-marker"))).toBe(false);
    expect(await noStoredSecrets(page)).toBe(true);
    await page.getByTestId("staff-cancel").click(); await page.getByTestId("staff-new").click();
    await expect(page.getByTestId("staff-password")).toHaveValue("");
    expect(state.calls.filter((call) => call.path === "/staff" && call.method === "POST")).toHaveLength(1);
  });
}

test("staff editing is explicitly confirmed and cannot change email, password or active state", async ({ page }) => {
  const state = await mockOnboarding(page);
  state.staff[owner.id] = [{ ...staffMember, phone: "5550100" }];
  await page.goto("/staff"); await page.getByTestId(`staff-edit-${staffMember.id}`).click();
  await expect(page.getByTestId("staff-email")).toHaveAttribute("readonly", "");
  await expect(page.getByTestId("staff-password")).toHaveCount(0);
  await page.getByTestId("staff-confirmed").check();
  await expect(page.getByTestId("staff-submit")).toBeDisabled();
  await page.getByTestId("staff-name").fill(" Updated Fixture Staff ");
  await page.getByTestId("staff-phone").fill("   ");
  await page.getByTestId("staff-role").selectOption("delivery_partner");
  await expect(page.getByTestId("staff-confirmed")).not.toBeChecked();
  await expect(page.getByTestId("staff-submit")).toBeDisabled();
  await page.getByTestId("staff-confirmed").check(); await page.getByTestId("staff-submit").click();
  await expect(page.getByTestId("staff-modal")).toHaveCount(0);
  expect(state.calls.find((call) => call.method === "PATCH")?.body).toEqual({ full_name: "Updated Fixture Staff", phone: null, role: "delivery_partner" });
  await expect(page.getByTestId(`staff-row-${staffMember.id}`)).toContainText("Delivery partner");
});

for (const active of [true, false]) {
  test(`staff ${active ? "deactivation" : "reactivation"} requires confirmation and preserves private credentials`, async ({ page }) => {
    const state = await mockOnboarding(page);
    state.staff[owner.id] = [{ ...staffMember, is_active: active }];
    await page.goto("/staff"); await page.getByTestId(`staff-activity-${staffMember.id}`).click();
    await page.getByTestId("staff-confirm-cancel").click();
    expect(state.calls.some((call) => call.method === "PATCH")).toBe(false);
    await page.getByTestId(`staff-activity-${staffMember.id}`).click();
    await page.getByTestId("staff-confirm").click();
    await expect(page.getByTestId("staff-confirm-modal")).toHaveCount(0);
    expect(state.calls.find((call) => call.method === "PATCH")?.body).toEqual({ is_active: !active });
    await expect(page.getByTestId(`staff-row-${staffMember.id}`)).toContainText(active ? "Inactive" : "Active");
    expect(state.calls.some((call) => call.path.includes("password") || call.method === "DELETE")).toBe(false);
  });
}

test("session revocation is confirmed, single-intent, and never requests a session list", async ({ page }) => {
  const state = await mockOnboarding(page); const gate = deferred(); state.mutationGate = gate.promise;
  await page.goto("/staff"); await page.getByTestId(`staff-revoke-${staffMember.id}`).click();
  await expect(page.getByTestId("staff-confirm-modal")).toContainText("A session list is not available");
  await page.getByTestId("staff-confirm").evaluate((button: HTMLButtonElement) => { button.click(); button.click(); });
  await expect(page.getByTestId("staff-confirm")).toBeDisabled();
  await expect(page.getByTestId("staff-confirm-cancel")).toBeDisabled();
  await expect.poll(() => state.calls.filter((call) => call.path.endsWith("/revoke-sessions")).length).toBe(1);
  gate.resolve(); await expect(page.getByTestId("staff-confirm-modal")).toHaveCount(0);
  const call = state.calls.find((item) => item.path.endsWith("/revoke-sessions"));
  expect(call?.path).toBe(`/staff/${staffMember.id}/revoke-sessions`);
  expect(call?.method).toBe("POST"); expect(call?.body).toEqual({});
  expect(state.calls.some((item) => item.path.includes("/auth/sessions"))).toBe(false);
});

test("failed access changes never show false success or reflect private server messages", async ({ page }) => {
  const state = await mockOnboarding(page); state.mutationStatus = 404; state.errorDetail = "private-error-marker";
  await page.goto("/staff"); await page.getByTestId(`staff-activity-${staffMember.id}`).click();
  await page.getByTestId("staff-confirm").click();
  await expect(page.getByTestId("staff-confirm-modal").getByRole("alert")).toContainText("unavailable");
  await expect(page.getByText("Staff account deactivated.", { exact: true })).toHaveCount(0);
  expect(await page.locator("body").evaluate((body) => (body.textContent || "").includes("private-error-marker"))).toBe(false);
});

async function signIn(page: Page, email: string) {
  await page.getByTestId("login-email").fill(email);
  await page.getByTestId("login-password").fill(fixturePassword);
  await page.getByTestId("login-submit").click();
}

test("logout and another owner login clear staff data and do not reuse the prior tenant cache", async ({ page }) => {
  const state = await mockOnboarding(page);
  await page.goto("/staff"); await expect(page.getByTestId(`staff-row-${staffMember.id}`)).toBeVisible();
  await page.getByTestId("logout-button").click(); await expect(page).toHaveURL(/\/login$/);
  const gate = deferred(); state.staffGate = gate.promise;
  await signIn(page, otherOwner.email); await expect(page).toHaveURL(/\/dashboard$/);
  await page.getByTestId("nav-staff").click();
  await expect(page.getByTestId("staff-loading")).toBeVisible();
  await expect(page.getByTestId(`staff-row-${staffMember.id}`)).toHaveCount(0);
  gate.resolve(); await expect(page.getByTestId(`staff-row-${otherStaff.id}`)).toBeVisible();
  expect(state.calls.filter((call) => call.path === "/staff" && call.method === "GET")).toHaveLength(2);
});

test("late staff requests cannot refill data after logout or a wrong-role account transition", async ({ page }) => {
  const state = await mockOnboarding(page); const gate = deferred(); state.staffGate = gate.promise;
  await page.goto("/staff"); await expect(page.getByTestId("staff-loading")).toBeVisible();
  await page.getByTestId("logout-button").click(); await expect(page).toHaveURL(/\/login$/);
  state.loginUser = { ...owner, role: "accountant" };
  gate.resolve(); await signIn(page, owner.email);
  await expect(page).toHaveURL(/\/finance$/);
  await page.goto("/staff"); await expect(page).toHaveURL(/\/finance$/);
  await expect(page.getByTestId(`staff-row-${staffMember.id}`)).toHaveCount(0);
  expect(state.calls.filter((call) => call.path.startsWith("/staff"))).toHaveLength(1);
});

for (const role of ["warehouse_manager", "delivery_partner", "customer"] as Role[]) {
  test(`${role} cannot mount customer intake controls or request the customer directory`, async ({ page }) => {
    const state = await mockOnboarding(page, { ...owner, role });
    await page.goto("/customers"); await expect(page).not.toHaveURL(/\/customers$/);
    await expect(page.getByTestId("cust-new")).toHaveCount(0);
    await expect(page.getByTestId("cust-new-account")).toHaveCount(0);
    expect(state.calls.some((call) => call.path === "/customers" || call.path === "/auth/register-customer")).toBe(false);
  });
}

test("customer business records normalize optional contacts and do not create a login", async ({ page }) => {
  const state = await mockOnboarding(page, { ...owner, role: "accountant" });
  await page.goto("/customers"); await page.getByTestId("cust-new").click();
  await expect(page.getByTestId("cust-modal")).toContainText("does not create a login");
  await page.getByTestId("cust-name").fill(" New Fixture Customer ");
  await page.getByTestId("cust-email").fill("   "); await page.getByTestId("cust-phone").fill("   ");
  await page.getByTestId("cust-business").fill("   "); await page.getByTestId("cust-tier").fill("   ");
  await page.getByTestId("cust-limit").fill("12.30"); await page.getByTestId("cust-submit").click();
  await expect(page.getByTestId("cust-modal")).toHaveCount(0);
  const call = state.calls.find((item) => item.path === "/customers" && item.method === "POST");
  expect(call?.body).toEqual({ name: "New Fixture Customer", business_name: null, phone: null, email: null, gstin: null,
    address: null, city: null, state: null, pincode: null, customer_type: "cash", credit_limit: "12.30", price_tier: null });
  expect(state.calls.some((item) => item.path === "/auth/register-customer" || item.path === "/auth/login")).toBe(false);
});

test("customer records distinguish loading, sanitized errors, and an actual empty directory", async ({ page }) => {
  const state = await mockOnboarding(page); const gate = deferred(); state.customersGate = gate.promise;
  state.customers[owner.id] = [];
  await page.goto("/customers"); await expect(page.getByTestId("cust-loading")).toBeVisible();
  await expect(page.getByTestId("cust-empty")).toHaveCount(0);
  state.customersStatus = 503; state.errorDetail = "private-customer-error-marker"; gate.resolve();
  await expect(page.getByTestId("cust-error")).toBeVisible();
  await expect(page.getByTestId("cust-empty")).toHaveCount(0);
  state.customersStatus = 200; await page.getByRole("button", { name: "Retry customers" }).click();
  await expect(page.getByTestId("cust-empty")).toBeVisible();
  expect(await page.locator("body").evaluate((body) => (body.textContent || "").includes("private-customer-error-marker"))).toBe(false);
});

test("malformed customer responses cannot masquerade as an empty directory", async ({ page }) => {
  const state = await mockOnboarding(page);
  state.customersResponse = { detail: "private-response-marker", password: "private-response-marker" };
  await page.goto("/customers"); await expect(page.getByTestId("cust-error")).toBeVisible();
  await expect(page.getByTestId("cust-new")).toBeDisabled();
  await expect(page.getByTestId("cust-new-account")).toBeDisabled();
  await expect(page.getByTestId("cust-empty")).toHaveCount(0);
  expect(await page.locator("body").evaluate((body) => (body.textContent || "").includes("private-response-marker"))).toBe(false);
});

async function fillCustomerAccount(page: Page) {
  await page.getByTestId("cust-account-full_name").fill(" New Account Holder ");
  await page.getByTestId("cust-account-email").fill("NEW-CUSTOMER@fixture.test");
  await page.getByTestId("cust-account-phone").fill("   "); await page.getByTestId("cust-account-business_name").fill("   ");
  await page.getByTestId("cust-account-password").fill(fixturePassword);
  await page.getByTestId("cust-account-confirmed").check();
}

test("new customer accounts are separate, holder-confirmed, tenant-derived and never automatically signed in", async ({ page }) => {
  const state = await mockOnboarding(page); const gate = deferred(); state.mutationGate = gate.promise;
  await page.goto("/customers"); await page.getByTestId("cust-new-account").click();
  await expect(page.getByTestId("cust-account-modal")).toContainText("Existing profiles and emails are not merged or linked");
  await fillCustomerAccount(page); await page.getByTestId("cust-account-confirmed").uncheck();
  await expect(page.getByTestId("cust-account-submit")).toBeDisabled();
  await page.getByTestId("cust-account-confirmed").check();
  await page.getByTestId("cust-account-submit").evaluate((button: HTMLButtonElement) => { button.click(); button.click(); });
  await expect(page.getByTestId("cust-account-password")).toHaveValue("");
  await expect(page.getByTestId("cust-account-submit")).toBeDisabled();
  await expect.poll(() => state.calls.filter((call) => call.path === "/auth/register-customer").length).toBe(1);
  gate.resolve(); await expect(page.getByTestId("cust-account-modal")).toHaveCount(0);
  const call = state.calls.find((item) => item.path === "/auth/register-customer");
  expect(call?.body).toEqual({ email: "new-customer@fixture.test", password: "[redacted]", full_name: "New Account Holder", phone: null, business_name: null });
  expect(call?.passwordMatches).toBe(true);
  expect(state.calls.some((item) => item.path === "/auth/login")).toBe(false);
  await expect(page.getByTestId("me-name")).toContainText(owner.full_name);
  expect(await noStoredSecrets(page)).toBe(true);
});

test("new customer account failures clear private passwords and never claim linking or verified email", async ({ page }) => {
  const state = await mockOnboarding(page); state.mutationStatus = 422;
  state.errorDetail = `${fixturePassword} private-account-error-marker`;
  await page.goto("/customers"); await page.getByTestId("cust-new-account").click();
  await fillCustomerAccount(page); await page.getByTestId("cust-account-submit").click();
  await expect(page.getByTestId("cust-account-error")).toBeVisible();
  await expect(page.getByTestId("cust-account-password")).toHaveValue("");
  await expect(page.getByTestId("cust-account-submit")).toBeDisabled();
  expect(await page.locator("body").evaluate((body) => (body.textContent || "").includes("private-account-error-marker"))).toBe(false);
  expect(await noStoredSecrets(page)).toBe(true);
  await expect(page.getByTestId("me-name")).toContainText(owner.full_name);
  expect(state.calls.some((call) => call.path === "/auth/login")).toBe(false);
});

test("accountant customer intake validates optional email and the shared final-password boundary", async ({ page }) => {
  const state = await mockOnboarding(page, { ...owner, role: "accountant" });
  await page.goto("/customers"); await page.getByTestId("cust-new").click();
  await page.getByTestId("cust-name").fill("Fixture Customer"); await page.getByTestId("cust-email").fill("invalid-contact");
  await expect(page.getByTestId("cust-submit")).toBeDisabled(); await page.getByTestId("cust-cancel").click();
  await page.getByTestId("cust-new-account").click(); await fillCustomerAccount(page);
  await page.getByTestId("cust-account-password").fill("a".repeat(11)); await page.getByTestId("cust-account-confirmed").check();
  await expect(page.getByTestId("cust-account-submit")).toBeDisabled();
  await page.getByTestId("cust-account-password").fill("\u754c".repeat(25)); await page.getByTestId("cust-account-confirmed").check();
  await expect(page.getByTestId("cust-account-submit")).toBeDisabled();
  expect(state.calls.some((call) => call.path === "/auth/register-customer" || call.method === "POST" && call.path === "/customers")).toBe(false);
  state.expectedPassword = "\u754c".repeat(24);
  await page.getByTestId("cust-account-password").fill(state.expectedPassword); await page.getByTestId("cust-account-confirmed").check();
  await page.getByTestId("cust-account-submit").click(); await expect(page.getByTestId("cust-account-modal")).toHaveCount(0);
  expect(state.calls.find((call) => call.path === "/auth/register-customer")?.passwordMatches).toBe(true);
  expect(state.calls.some((call) => call.path === "/auth/login")).toBe(false);
});

test("customer directory cache and private account fields clear across owner transitions", async ({ page }) => {
  const state = await mockOnboarding(page);
  await page.goto("/customers"); await expect(page.getByText("Fixture Customer", { exact: true })).toBeVisible();
  await page.getByTestId("cust-new-account").click(); await fillCustomerAccount(page);
  await page.getByTestId("cust-account-cancel").click(); await page.getByTestId("logout-button").click();
  await expect(page).toHaveURL(/\/login$/); await signIn(page, otherOwner.email);
  await expect(page).toHaveURL(/\/dashboard$/); await page.getByTestId("nav-customers").click();
  await expect(page.getByText("Other Fixture Customer", { exact: true })).toBeVisible();
  await expect(page.getByText("Fixture Customer", { exact: true })).toHaveCount(0);
  await page.getByTestId("cust-new-account").click(); await expect(page.getByTestId("cust-account-password")).toHaveValue("");
  expect(state.calls.some((call) => call.path === "/auth/register-customer")).toBe(false);
});

test("staff and customer forms retain labels, theme controls and narrow large-text containment", async ({ page }) => {
  const state = await mockOnboarding(page); await page.setViewportSize({ width: 320, height: 844 });
  state.staff[owner.id] = [{ ...staffMember, full_name: "Long".repeat(45), phone: "5".repeat(30) }];
  await page.goto("/staff"); await page.addStyleTag({ content: "html { font-size: 200%; }" });
  await page.getByTestId("mobile-menu-open").click();
  await page.getByTestId("mobile-drawer").getByTestId("theme-toggle").click();
  await page.getByTestId("mobile-drawer").getByTestId("drawer-close").click(); await page.getByTestId("staff-new").click();
  await page.getByLabel("Full name *", { exact: true }).focus(); await expect(page.getByTestId("staff-name")).toBeFocused();
  await page.getByTestId("staff-submit").scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByTestId("staff-cancel").click(); await page.goto("/customers");
  await page.addStyleTag({ content: "html { font-size: 200%; }" }); await page.getByTestId("cust-new-account").click();
  await page.getByLabel("Login email *", { exact: true }).focus(); await expect(page.getByTestId("cust-account-email")).toBeFocused();
  await page.getByTestId("cust-account-submit").scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

function response(config: InternalAxiosRequestConfig, data: unknown, status = 200): AxiosResponse {
  return { config, data, status, statusText: String(status), headers: {} };
}

test.describe("staff client contracts", () => {
  const originalAdapter = api.defaults.adapter;
  test.beforeEach(() => { useAuth.getState().expire(); useAuth.setState({ user: owner, sessionVersion: 50 }); });
  test.afterEach(() => { useAuth.getState().expire(); api.defaults.adapter = originalAdapter; });

  test("owner-only route and query guards deny even manual wrong-role fetches", async () => {
    let calls = 0; api.defaults.adapter = async (config) => { calls += 1; return response(config, {}); };
    const client = new QueryClient();
    for (const user of [null, { ...owner, is_active: false }, ...(["warehouse_manager", "accountant", "customer", "delivery_partner"] as const).map((role) => ({ ...owner, role }))]) {
      useAuth.setState({ user });
      expect(staffScope(user, 50)).toBeNull();
      if (user) expect(canAccessStaffRoute(user, "/staff")).toBe(false);
      const result = await client.fetchQuery(staffQuery(null, 1)).catch((error: unknown) => error);
      expect(axios.isCancel(result)).toBe(true);
    }
    expect(calls).toBe(0); client.clear();
  });

  test("staff cache keys include the owner, tenant and epoch and retain only the safe DTO", async () => {
    const scope = staffScope(owner, 50)!; const client = new QueryClient();
    api.defaults.adapter = async (config) => response(config, { items: [{ ...staffMember, password: "private-marker", access_token: "private-marker", is_email_verified: true }],
      total: 1, page: 1, page_size: 50, credentials: "private-marker" });
    const query = staffQuery(scope, 1); const data = await client.fetchQuery(query);
    expect(query.queryKey).toEqual(["staff", owner.tenant_id, owner.id, 50, 1]);
    expect(Object.keys(data).sort()).toEqual(["items", "page", "page_size", "total"]);
    expect(Object.keys(data.items[0]).sort()).toEqual(["created_at", "email", "full_name", "id", "is_active", "phone", "role"]);
    expect(JSON.stringify(client.getQueryData(query.queryKey)).includes("private-marker")).toBe(false);
    expect(staffQuery(staffScope(otherOwner, 51), 1).queryKey).not.toEqual(query.queryKey);
    client.clear();
  });

  test("create, patch and revoke send exact whitelisted shapes and never return credentials", async () => {
    const calls: { method?: string; url?: string; body: Record<string, unknown>; passwordMatches: boolean }[] = [];
    api.defaults.adapter = async (config) => {
      const body = JSON.parse(String(config.data || "{}")) as Record<string, unknown>;
      const matched = body.password === fixturePassword; const redacted = { ...body };
      if ("password" in redacted) redacted.password = "[redacted]";
      calls.push({ method: config.method, url: config.url, body: redacted, passwordMatches: matched });
      return response(config, config.url?.endsWith("/revoke-sessions") ? { message: "Staff sessions revoked", token: "private-marker" }
        : { ...staffMember, ...body, password: "private-marker", access_token: "private-marker" }, config.method === "post" && config.url === "/staff" ? 201 : 200);
    };
    const scope = staffScope(owner, 50)!; const signal = new AbortController().signal;
    const created = await createStaff(scope, { email: staffMember.email, full_name: staffMember.full_name, phone: "   ", role: staffMember.role, password: fixturePassword }, signal);
    const patched = await patchStaff(scope, staffMember.id, { full_name: " Updated ", phone: " ", role: "accountant", is_active: false,
      email: "unsupported@fixture.test", password: fixturePassword, tenant_id: otherOwner.tenant_id } as StaffPatch, signal);
    await revokeStaffSessions(scope, staffMember.id, signal);
    expect(calls.map((call) => ({ method: call.method, url: call.url, body: call.body }))).toEqual([
      { method: "post", url: "/staff", body: { email: staffMember.email, full_name: staffMember.full_name, phone: null, role: staffMember.role, password: "[redacted]" } },
      { method: "patch", url: `/staff/${staffMember.id}`, body: { full_name: "Updated", phone: null, role: "accountant", is_active: false } },
      { method: "post", url: `/staff/${staffMember.id}/revoke-sessions`, body: {} },
    ]);
    expect(calls[0].passwordMatches).toBe(true);
    expect("password" in created || "access_token" in patched).toBe(false);
  });

  test("account transitions discard delayed staff responses rather than caching them", async () => {
    const gate = deferred(); const started = deferred();
    api.defaults.adapter = async (config) => { started.resolve(); await gate.promise; return response(config, { items: [staffMember], total: 1, page: 1, page_size: 50 }); };
    const client = new QueryClient(); const query = staffQuery(staffScope(owner, 50), 1);
    const pending = client.fetchQuery(query).catch((error: unknown) => error); await started.promise;
    useAuth.setState({ user: otherOwner, sessionVersion: 51 }); gate.resolve();
    expect(axios.isCancel(await pending)).toBe(true);
    expect(client.getQueryData(query.queryKey)).toBeUndefined(); client.clear();
  });

  test("reflected staff errors are sanitized before they enter the query cache", async () => {
    api.defaults.adapter = async (config) => {
      throw new AxiosError("private-error-marker", undefined, config, undefined,
        response(config, { detail: [{ msg: "private-error-marker", input: "private-error-marker" }], password: "private-error-marker" }, 422));
    };
    const client = new QueryClient(); const query = staffQuery(staffScope(owner, 50), 1);
    const error = await client.fetchQuery(query).catch((failure: unknown) => failure);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message.includes("private-error-marker")).toBe(false);
    expect("response" in (error as object)).toBe(false);
    expect(JSON.stringify(client.getQueryState(query.queryKey)?.error).includes("private-error-marker")).toBe(false);
    client.clear();
  });

  test("owner targets and delayed account mutations fail closed without publishing a stale result", async () => {
    const gate = deferred(); const started = deferred(); let calls = 0;
    api.defaults.adapter = async (config) => {
      calls += 1; started.resolve(); await gate.promise;
      return response(config, staffMember, 201);
    };
    const scope = staffScope(owner, 50)!; const signal = new AbortController().signal;
    expect(axios.isCancel(await patchStaff(scope, owner.id, { is_active: false }, signal).catch((error: unknown) => error))).toBe(true);
    expect(axios.isCancel(await revokeStaffSessions(scope, owner.id, signal).catch((error: unknown) => error))).toBe(true);
    expect(calls).toBe(0);
    const pending = createStaff(scope, { email: staffMember.email, full_name: staffMember.full_name, role: staffMember.role, phone: "", password: fixturePassword }, signal).catch((error: unknown) => error);
    await started.promise; useAuth.setState({ user: otherOwner, sessionVersion: 51 }); gate.resolve();
    expect(axios.isCancel(await pending)).toBe(true); expect(calls).toBe(1);
  });

  test("staff errors ignore untrusted detail, input, context and credential fields", () => {
    for (const status of [400, 401, 403, 404, 409, 422, 500]) {
      const error = new AxiosError("private-marker", undefined, undefined, undefined, {
        status, statusText: "fixture", headers: {}, config: {} as InternalAxiosRequestConfig,
        data: { detail: [{ loc: ["body", "private-marker"], msg: "private-marker", input: "private-marker", ctx: { credential: "private-marker" } }], token: "private-marker" },
      });
      expect(staffRequestError(error).includes("private-marker")).toBe(false);
    }
  });

  test("password validation counts Unicode characters and UTF-8 bytes", () => {
    expect(accountPasswordSchema.safeParse("a".repeat(11)).success).toBe(false);
    expect(accountPasswordSchema.safeParse("\u{1f600}".repeat(6)).success).toBe(false);
    expect(accountPasswordSchema.safeParse("\u754c".repeat(25)).success).toBe(false);
    expect(accountPasswordSchema.safeParse("\u754c".repeat(24)).success).toBe(true);
    expect(accountPasswordSchema.safeParse("\ud800".repeat(12)).success).toBe(false);
    expect(accountPasswordSchema.safeParse("\udc00".repeat(12)).success).toBe(false);
    expect(accountPasswordSchema.safeParse("\u{1f600}".repeat(18)).success).toBe(true);
  });
});
