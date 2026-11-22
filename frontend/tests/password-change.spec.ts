import { test, expect, type Page } from "@playwright/test";
import axios, { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";
import { api } from "../src/lib/api";
import { useAuth, type AuthUser, type Role } from "../src/lib/auth";
import { useSettings } from "../src/lib/settings";
import { deferred, mockOnboarding, noStoredSecrets, owner, otherOwner } from "./onboarding-fixtures";

const currentPassword = "current-fixture-password";
const newPassword = "new-holder-fixture-password";
const originalAdapter = api.defaults.adapter;

function response(config: InternalAxiosRequestConfig, status = 200): AxiosResponse {
  const result = { config, data: { message: config.url === "/auth/change-password" ? "Password changed. Sign in again." : "Fixture response" }, status, statusText: String(status), headers: {} };
  if (status >= 400) throw new AxiosError("Fixture failure", undefined, config, undefined, result);
  return result;
}

test.beforeEach(() => {
  useAuth.getState().expire();
  useAuth.setState({ user: owner });
});
test.afterEach(() => {
  useAuth.getState().expire();
  api.defaults.adapter = originalAdapter;
});

async function mockChange(page: Page, user: AuthUser | null = owner) {
  const account = await mockOnboarding(page, user);
  const state = {
    account, status: 200, abort: false, gate: null as Promise<void> | null,
    calls: [] as { keys: string[]; currentMatches: boolean; newMatches: boolean; query: string }[],
  };
  await page.route("**/api/v1/auth/change-password", async (route) => {
    const request = route.request();
    const body = request.postDataJSON() as Record<string, unknown>;
    state.calls.push({ keys: Object.keys(body).sort(), currentMatches: body.current_password === currentPassword,
      newMatches: body.new_password === newPassword, query: new URL(request.url()).search });
    await state.gate;
    if (state.abort) { await route.abort("failed"); return; }
    if (state.status === 200) account.user = null;
    await route.fulfill({ status: state.status, contentType: "application/json", body: JSON.stringify(
      state.status === 200 ? { message: "Password changed. Sign in again." }
        : { detail: [{ msg: currentPassword, input: newPassword, loc: ["body", newPassword] }] },
    ) });
  });
  return state;
}

async function fillChange(page: Page, password = newPassword, confirmation = password) {
  await page.getByLabel("Current password", { exact: true }).fill(currentPassword);
  await page.getByLabel("New password", { exact: true }).fill(password);
  await page.getByLabel("Confirm new password", { exact: true }).fill(confirmation);
}

for (const role of ["super_admin", "warehouse_manager", "accountant", "delivery_partner", "customer"] as Role[]) {
  test(`authenticated ${role} can submit only their own two password fields`, async ({ page }) => {
    const state = await mockChange(page, { ...owner, role });
    await page.goto("/change-password");
    await expect(page.getByTestId("change-password-form")).toBeVisible();
    await fillChange(page);
    await page.getByTestId("change-password-submit").click();
    await expect(page.getByTestId("password-change-changed")).toBeVisible();
    expect(state.calls).toEqual([{ keys: ["current_password", "new_password"], currentMatches: true, newMatches: true, query: "" }]);
    expect(state.account.calls.some((call) => call.path === "/auth/login")).toBe(false);
    expect(await noStoredSecrets(page, [currentPassword, newPassword])).toBe(true);
    await expect(page.locator('input[type="password"]')).toHaveCount(0);
    await page.getByTestId("recovery-login-link").click();
    await expect(page.getByTestId("login-form")).toBeVisible();
  });
}

test("anonymous password changes never expose a form or submit credentials", async ({ page }) => {
  const state = await mockChange(page, null);
  await page.goto("/change-password");
  await expect(page.getByTestId("password-change-sign-in")).toBeVisible();
  await expect(page.getByTestId("change-password-form")).toHaveCount(0);
  expect(state.calls).toHaveLength(0);
});

for (const role of ["super_admin", "warehouse_manager", "accountant"] as const) {
  test(`${role} workspace exposes the private account-security link`, async ({ page }) => {
    await mockChange(page, { ...owner, role });
    await page.goto(role === "super_admin" ? "/dashboard" : role === "warehouse_manager" ? "/inventory" : "/finance");
    await page.getByTestId("change-password-link").click();
    await expect(page).toHaveURL(/\/change-password$/);
    await expect(page.getByTestId("change-password-form")).toBeVisible();
  });
}

test("confirmation, new-password reuse and UTF-8 requirements block submission locally", async ({ page }) => {
  const state = await mockChange(page);
  await page.goto("/change-password");
  for (const [value, confirmation, message] of [
    [newPassword, "mismatching-password", "do not match"],
    [currentPassword, currentPassword, "different"],
    ["too-short", "too-short", "12 characters"],
    ["\u754c".repeat(25), "\u754c".repeat(25), "72 UTF-8 bytes"],
  ]) {
    await fillChange(page, value, confirmation);
    await page.getByTestId("change-password-submit").click();
    await expect(page.getByTestId("change-password-form").getByRole("alert").first()).toContainText(message);
  }
  expect(state.calls).toHaveLength(0);
  await fillChange(page, "\u754c".repeat(24));
  await page.getByTestId("change-password-submit").click();
  await expect(page.getByTestId("password-change-changed")).toBeVisible();
});

for (const status of [400, 403, 422, 429]) {
  test(`explicit ${status} rejects safely without credential echo or session loss`, async ({ page }) => {
    const state = await mockChange(page);
    state.status = status;
    await page.goto("/change-password");
    await fillChange(page);
    await page.getByTestId("change-password-submit").click();
    await expect(page.getByTestId("change-password-form").getByRole("alert")).toBeVisible();
    await expect(page.getByTestId("password-change-changed")).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText(currentPassword);
    await expect(page.locator("body")).not.toContainText(newPassword);
    for (const name of ["currentPassword", "newPassword", "confirmation"]) {
      await expect(page.getByTestId(`change-${name}`)).toHaveValue("");
    }
    expect(state.account.calls.filter((call) => call.path === "/auth/refresh")).toHaveLength(0);
    expect(state.calls).toHaveLength(1);
    state.status = 200;
    await fillChange(page);
    await page.getByTestId("change-password-submit").click();
    await expect(page.getByTestId("password-change-changed")).toBeVisible();
  });
}

for (const status of [408, 500, 503]) {
  test(`ambiguous ${status} requires re-login and never claims success or replays`, async ({ page }) => {
    const state = await mockChange(page);
    state.status = status;
    await page.goto("/change-password");
    await fillChange(page);
    await page.getByTestId("change-password-submit").click();
    await expect(page.getByTestId("password-change-unconfirmed")).toContainText("could not be confirmed");
    await expect(page.getByTestId("password-change-changed")).toHaveCount(0);
    await expect(page.getByTestId("change-password-form")).toHaveCount(0);
    expect(state.calls).toHaveLength(1);
    expect(state.account.calls.filter((call) => call.path === "/auth/refresh")).toHaveLength(0);
    expect(await noStoredSecrets(page, [currentPassword, newPassword])).toBe(true);
  });
}

test("lost password-change response cannot become a success or automatic retry", async ({ page }) => {
  const state = await mockChange(page);
  state.abort = true;
  await page.goto("/change-password");
  await fillChange(page);
  await page.getByTestId("change-password-submit").click();
  await expect(page.getByTestId("password-change-unconfirmed")).toBeVisible();
  expect(state.calls).toHaveLength(1);
  await expect(page.getByTestId("password-change-changed")).toHaveCount(0);
});

test("an expired change session is not renewed and password secrets are discarded", async ({ page }) => {
  const state = await mockChange(page);
  state.status = 401;
  await page.goto("/change-password");
  await fillChange(page);
  await page.getByTestId("change-password-submit").click();
  await expect(page.getByTestId("password-change-session-ended")).toBeVisible();
  await expect(page.getByTestId("change-password-form")).toHaveCount(0);
  expect(state.account.calls.filter((call) => call.path === "/auth/refresh")).toHaveLength(0);
  expect(state.calls).toHaveLength(1);
});

test("duplicate submits share one request and disable password fields while pending", async ({ page }) => {
  const state = await mockChange(page);
  const gate = deferred();
  state.gate = gate.promise;
  await page.goto("/change-password");
  await fillChange(page);
  await page.getByTestId("change-password-form").evaluate((form) => {
    (form as HTMLFormElement).requestSubmit();
    (form as HTMLFormElement).requestSubmit();
  });
  await expect.poll(() => state.calls.length).toBe(1);
  await expect(page.getByTestId("change-password-submit")).toBeDisabled();
  await expect(page.getByTestId("change-currentPassword")).toBeDisabled();
  gate.resolve();
  await expect(page.getByTestId("password-change-changed")).toBeVisible();
  expect(state.calls).toHaveLength(1);
});

test("password page is private, keyboard-accessible and fits a narrow viewport", async ({ page, request }) => {
  const reply = await request.get("/change-password");
  expect(reply.headers()["cache-control"]).toContain("no-store");
  expect(reply.headers()["referrer-policy"]).toBe("no-referrer");
  expect(await reply.text()).toContain('name="robots" content="noindex, nofollow"');
  await mockChange(page);
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/change-password");
  await page.getByTestId("recovery-theme-toggle").click();
  const current = page.getByLabel("Current password", { exact: true });
  await expect(current).toHaveAttribute("type", "password");
  await expect(current).toHaveAttribute("autocomplete", "current-password");
  await current.focus();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("New password", { exact: true })).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("confirmed password mutation clears local identity/settings without renewing or logging in", async () => {
  useSettings.setState({ data: { tenant_id: owner.tenant_id, company_name: "Fixture", currency_code: "INR", currency_symbol: "INR", locale: "en-IN", values: {} } });
  const calls: string[] = [];
  api.defaults.adapter = async (config) => {
    calls.push(config.url!);
    expect(config.timeout).toBe(30_000);
    return response(config);
  };
  const epoch = useAuth.getState().sessionVersion;
  await useAuth.getState().changePassword(currentPassword, newPassword);
  expect(useAuth.getState().user).toBeNull();
  expect(useAuth.getState().passwordChangeOutcome).toBe("changed");
  expect(useSettings.getState().data).toBeNull();
  expect(useAuth.getState().sessionVersion).toBeGreaterThan(epoch);
  expect(calls).toEqual(["/auth/change-password"]);
});

test("new login cancels an older password request without clearing the new identity", async () => {
  const gate = deferred();
  const started = deferred();
  let signal: AbortSignal | undefined;
  api.defaults.adapter = async (config) => {
    if (config.url === "/auth/change-password") {
      signal = config.signal as AbortSignal;
      started.resolve();
      await gate.promise;
      return response(config);
    }
    return { ...response(config), data: { user: otherOwner } };
  };
  const change = useAuth.getState().changePassword(currentPassword, newPassword).catch((error: unknown) => error);
  await started.promise;
  await useAuth.getState().login(otherOwner.email, "synthetic-login-password");
  expect(signal?.aborted).toBe(true);
  gate.resolve();
  expect(axios.isCancel(await change)).toBe(true);
  expect(useAuth.getState().user).toEqual(otherOwner);
  expect(useAuth.getState().passwordChangeOutcome).toBeNull();
});

test("bootstrap and duplicate changes cannot compete with an active password operation", async () => {
  const gate = deferred();
  const started = deferred();
  const calls: string[] = [];
  api.defaults.adapter = async (config) => {
    calls.push(config.url!);
    started.resolve();
    await gate.promise;
    return response(config);
  };
  const pending = useAuth.getState().changePassword(currentPassword, newPassword);
  await started.promise;
  await useAuth.getState().bootstrap();
  const duplicate = await useAuth.getState().changePassword(currentPassword, newPassword).catch((error: unknown) => error);
  expect(axios.isCancel(duplicate)).toBe(true);
  gate.resolve();
  await pending;
  expect(calls).toEqual(["/auth/change-password"]);
});

test("old authenticated reads cannot publish after password reauthentication starts", async () => {
  const gate = deferred();
  const started = deferred();
  api.defaults.adapter = async (config) => {
    if (config.url === "/customers") {
      started.resolve();
      await gate.promise;
    }
    return response(config);
  };
  const read = api.get("/customers").catch((error: unknown) => error);
  await started.promise;
  await useAuth.getState().changePassword(currentPassword, newPassword);
  gate.resolve();
  expect(axios.isCancel(await read)).toBe(true);
});

test("a fresh login to the same account clears a previous password-change outcome", async () => {
  api.defaults.adapter = async (config) => config.url === "/auth/change-password" ? response(config) : ({ ...response(config), data: { user: owner } });
  await useAuth.getState().changePassword(currentPassword, newPassword);
  expect(useAuth.getState().passwordChangeOutcome).toBe("changed");
  await useAuth.getState().login(owner.email, newPassword);
  expect(useAuth.getState().user).toEqual(owner);
  expect(useAuth.getState().passwordChangeOutcome).toBeNull();
});

test("an unexpected successful password reply is unconfirmed, not a fabricated success", async () => {
  api.defaults.adapter = async (config) => ({ ...response(config), data: { message: "Unexpected upstream reply" } });
  await useAuth.getState().changePassword(currentPassword, newPassword).catch(() => undefined);
  expect(useAuth.getState().user).toBeNull();
  expect(useAuth.getState().passwordChangeOutcome).toBe("unconfirmed");
});
