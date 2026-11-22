import { test, expect, type Page } from "@playwright/test";
import type { AuthUser } from "../src/lib/auth";

const resetToken = "isolated-email-link-token";
const password = "a-new-test-password";
const staff: AuthUser = {
  id: "recovery-staff", tenant_id: "recovery-tenant", email: "staff@example.test",
  full_name: "Recovery Staff", role: "super_admin", is_active: true,
};

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}

async function mockRecovery(page: Page) {
  const state = {
    meUser: null as AuthUser | null,
    meGate: null as Promise<void> | null,
    forgotGate: null as Promise<void> | null,
    resetGate: null as Promise<void> | null,
    forgotStatus: 200,
    resetStatus: 200,
    resetAbort: false,
    calls: [] as { path: string; method: string; body: unknown }[],
  };
  await page.route("**/*", async (route) => {
    const host = new URL(route.request().url()).hostname;
    if (!["localhost", "127.0.0.1"].includes(host)) await route.abort();
    else await route.continue();
  });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    const method = request.method();
    const body = request.postData() ? request.postDataJSON() as unknown : null;
    state.calls.push({ path, method, body });
    let status = 200;
    let data: unknown = {};
    if (path === "/auth/me") {
      const snapshot = state.meUser;
      await state.meGate;
      status = snapshot ? 200 : 401;
      data = snapshot || { detail: "No current session" };
    } else if (path === "/auth/refresh") {
      status = 401;
      data = { detail: "No current session" };
    } else if (path === "/auth/forgot-password") {
      await state.forgotGate;
      status = state.forgotStatus;
      data = status === 200 ? { message: "If an account matches, recovery has been requested." }
        : { detail: status === 429 ? "Please wait before requesting another link." : "Password reset email is not configured." };
    } else if (path === "/auth/reset-password") {
      await state.resetGate;
      if (state.resetAbort) {
        await route.abort("failed");
        return;
      }
      status = state.resetStatus;
      data = status === 200 ? { message: "Password reset successful" }
        : { detail: "This reset link is invalid or expired." };
      if (status === 200) state.meUser = null;
    } else if (path === "/settings") {
      data = { tenant_id: staff.tenant_id, company_name: "Test Company", currency_code: "INR",
        currency_symbol: "INR", locale: "en-IN", values: {} };
    } else {
      status = 404;
      data = { detail: "Unexpected recovery test route" };
    }
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
  });
  return state;
}

async function fillReset(page: Page, value = password, confirmation = value) {
  await page.getByTestId("reset-password").fill(value);
  await page.getByTestId("reset-confirmation").fill(confirmation);
}

test("login links to recovery with an optional business identity and generic acknowledgement", async ({ page }) => {
  const state = await mockRecovery(page);
  await page.goto("/login");
  await page.getByTestId("forgot-password-link").click();
  await expect(page).toHaveURL(/\/forgot-password$/);
  await page.getByTestId("forgot-email").fill("staff@example.test");
  const tenant = "11111111-1111-4111-8111-111111111111";
  await page.getByTestId("forgot-tenant").fill(tenant);
  await page.getByTestId("forgot-submit").click();
  await expect(page.getByTestId("forgot-requested")).toBeVisible();
  expect(state.calls.find((call) => call.path === "/auth/forgot-password")?.body).toEqual({
    email: "staff@example.test", tenant_id: tenant,
  });
  await expect(page.getByTestId("forgot-requested")).not.toContainText("staff@example.test");
  expect(state.calls.some((call) => call.path === "/auth/login")).toBe(false);
});

test("unconfigured and throttled recovery is visible and cannot masquerade as a sent email", async ({ page }) => {
  const state = await mockRecovery(page);
  state.forgotStatus = 503;
  await page.goto("/forgot-password");
  await page.getByTestId("forgot-email").fill("absent@example.test");
  await page.getByTestId("forgot-submit").click();
  await expect(page.getByTestId("forgot-form").getByRole("alert")).toContainText("not configured");
  await expect(page.getByTestId("forgot-requested")).toHaveCount(0);
  state.forgotStatus = 429;
  await page.getByTestId("forgot-submit").click();
  await expect(page.getByTestId("forgot-form").getByRole("alert")).toContainText("Please wait");
  await expect(page.getByTestId("forgot-submit")).toBeEnabled();
  state.forgotStatus = 200;
  await page.getByTestId("forgot-submit").click();
  await expect(page.getByTestId("forgot-requested")).toBeVisible();
});

test("a recovery submission survives late anonymous bootstrap without duplicate requests", async ({ page }) => {
  const state = await mockRecovery(page);
  const me = deferred();
  const request = deferred();
  state.meGate = me.promise;
  state.forgotGate = request.promise;
  await page.goto("/forgot-password");
  await page.getByTestId("forgot-email").fill("absent@example.test");
  await page.getByTestId("forgot-submit").click();
  await expect.poll(() => state.calls.filter((call) => call.path === "/auth/forgot-password").length).toBe(1);
  me.resolve();
  await expect.poll(() => state.calls.filter((call) => call.path === "/auth/refresh").length).toBe(1);
  request.resolve();
  await expect(page.getByTestId("forgot-requested")).toBeVisible();
  expect(state.calls.filter((call) => call.path === "/auth/forgot-password")).toHaveLength(1);
});

test("fragment reset links survive bootstrap, never redeem on GET, and require a fresh login", async ({ page }) => {
  const state = await mockRecovery(page);
  state.meUser = staff;
  const me = deferred();
  state.meGate = me.promise;
  const requests: string[] = [];
  page.on("request", (request) => requests.push(`${request.url()} ${request.headers().referer || ""}`));
  await page.goto(`/reset-password#token=${resetToken}`);
  await expect(page.getByTestId("reset-form")).toBeVisible();
  await expect(page).toHaveURL(/\/reset-password$/);
  expect(state.calls.some((call) => call.path === "/auth/reset-password")).toBe(false);
  await expect(page.locator("body")).not.toContainText(resetToken);
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).not.toContain(resetToken);
  await fillReset(page);
  await page.getByTestId("reset-submit").click();
  await expect(page.getByTestId("reset-completed")).toBeVisible();
  me.resolve();
  await expect(page.getByTestId("reset-completed")).toBeVisible();
  expect(state.calls.filter((call) => call.path === "/auth/reset-password")).toEqual([
    { path: "/auth/reset-password", method: "POST", body: { token: resetToken, new_password: password } },
  ]);
  expect(requests.every((request) => !request.includes(resetToken))).toBe(true);
  await page.getByTestId("recovery-login-link").click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByTestId("login-form")).toBeVisible();
});

test("reset memory survives anonymous bootstrap and accepts a newly opened email link", async ({ page }) => {
  const state = await mockRecovery(page);
  const me = deferred();
  state.meGate = me.promise;
  await page.goto(`/reset-password#token=${resetToken}`);
  await expect(page.getByTestId("reset-form")).toBeVisible();
  await expect(page).toHaveURL(/\/reset-password$/);
  me.resolve();
  await expect.poll(() => state.calls.filter((call) => call.path === "/auth/refresh").length).toBe(1);
  await expect(page.getByTestId("reset-form")).toBeVisible();
  const replacement = "replacement-email-link-token";
  await page.evaluate((value) => { window.location.hash = `token=${value}`; }, replacement);
  await expect(page).toHaveURL(/\/reset-password$/);
  await fillReset(page);
  await page.getByTestId("reset-submit").click();
  await expect(page.getByTestId("reset-completed")).toBeVisible();
  expect(state.calls.find((call) => call.path === "/auth/reset-password")?.body).toEqual({
    token: replacement, new_password: password,
  });
});

test("password confirmation and the UTF-8 byte limit reject unsafe submissions locally", async ({ page }) => {
  const state = await mockRecovery(page);
  await page.goto(`/reset-password#token=${resetToken}`);
  await fillReset(page, password, "a-different-test-password");
  await page.getByTestId("reset-submit").click();
  await expect(page.getByTestId("reset-form").getByRole("alert")).toContainText("do not match");
  await fillReset(page, "\u754c".repeat(25));
  await page.getByTestId("reset-submit").click();
  await expect(page.getByTestId("reset-form").getByRole("alert")).toContainText("72 UTF-8 bytes");
  expect(state.calls.some((call) => call.path === "/auth/reset-password")).toBe(false);
  await fillReset(page, "\u754c".repeat(24));
  await page.getByTestId("reset-submit").click();
  await expect(page.getByTestId("reset-completed")).toBeVisible();
});

test("a response for an earlier reset link cannot discard a newly opened link", async ({ page }) => {
  const state = await mockRecovery(page);
  state.meUser = staff;
  const request = deferred();
  state.resetGate = request.promise;
  await page.goto(`/reset-password#token=${resetToken}`);
  await fillReset(page);
  await page.getByTestId("reset-submit").click();
  await expect.poll(() => state.calls.filter((call) => call.path === "/auth/reset-password").length).toBe(1);
  const replacement = "newer-email-link-token";
  await page.evaluate((value) => { window.location.hash = `token=${value}`; }, replacement);
  await expect(page).toHaveURL(/\/reset-password$/);
  request.resolve();
  await expect(page.getByTestId("reset-submit")).toBeEnabled();
  await expect(page.getByTestId("reset-completed")).toHaveCount(0);
  await fillReset(page);
  await page.getByTestId("reset-submit").click();
  await expect(page.getByTestId("reset-completed")).toBeVisible();
  expect(state.calls.filter((call) => call.path === "/auth/reset-password").map((call) => call.body)).toEqual([
    { token: resetToken, new_password: password },
    { token: replacement, new_password: password },
  ]);
});

test("invalid links and an unconfirmed network result never display false reset success", async ({ page }) => {
  const state = await mockRecovery(page);
  state.resetStatus = 404;
  await page.goto(`/reset-password#token=${resetToken}`);
  await fillReset(page);
  await page.getByTestId("reset-submit").click();
  await expect(page.getByTestId("reset-form").getByRole("alert")).toContainText("invalid or expired");
  await expect(page.getByTestId("reset-completed")).toHaveCount(0);
  state.resetAbort = true;
  await page.getByTestId("reset-submit").click();
  await expect(page.getByTestId("reset-form").getByRole("alert")).toContainText("could not be confirmed");
  await expect(page.getByTestId("reset-completed")).toHaveCount(0);
  expect(state.calls.filter((call) => call.path === "/auth/reset-password")).toHaveLength(2);
});

test("missing, query-only, duplicate and oversized tokens cannot cause reset requests", async ({ page }) => {
  const state = await mockRecovery(page);
  for (const suffix of ["", "?token=unsupported-link", "#token=a&token=b", `#token=${"a".repeat(129)}`]) {
    await page.goto(`/reset-password${suffix}`);
    await expect(page.getByTestId("reset-missing")).toBeVisible();
    await expect(page).toHaveURL(/\/reset-password$/);
    await expect(page.getByTestId("reset-form")).toHaveCount(0);
  }
  expect(state.calls.some((call) => call.path === "/auth/reset-password")).toBe(false);
});

test("account recovery pages have noncacheable and no-referrer privacy boundaries", async ({ request }) => {
  for (const path of ["/forgot-password", "/reset-password"]) {
    const response = await request.get(path);
    expect(response.status()).toBe(200);
    expect(response.headers()["referrer-policy"]).toBe("no-referrer");
    expect(response.headers()["cache-control"]).toContain("no-store");
    expect(await response.text()).toContain('name="robots" content="noindex, nofollow"');
  }
});

test("mobile recovery keeps theme controls, labelled fields and no horizontal overflow", async ({ page }) => {
  await mockRecovery(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/reset-password#token=${resetToken}`);
  await expect(page.getByTestId("reset-form")).toBeVisible();
  await page.getByTestId("recovery-theme-toggle").click();
  await page.getByLabel("New password", { exact: true }).focus();
  await expect(page.getByTestId("reset-password")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("reset-confirmation")).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
