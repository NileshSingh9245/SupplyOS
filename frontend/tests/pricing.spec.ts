import { test, expect, type Page } from "@playwright/test";
import axios, { type AxiosResponse, type InternalAxiosRequestConfig } from "axios";
import { QueryClient } from "@tanstack/react-query";
import { api } from "../src/lib/api";
import { useAuth, type Role } from "../src/lib/auth";
import { assignCustomerTier, choicesQuery, pricingKey, pricingScope, quoteQuery, removeOverride, saveOverride, saveTier, tiersQuery } from "../src/lib/pricing";
import { deferred, mockOnboarding, owner, otherOwner } from "./onboarding-fixtures";

const customerId = "77777777-7777-4777-8777-777777777777";
const productId = "99999999-9999-4999-8999-999999999999";
const tier = { id: "55555555-5555-4555-8555-555555555555", name: "Wholesale", discount_pct: "5.00" };
const originalAdapter = api.defaults.adapter;

function response(config: InternalAxiosRequestConfig, data: unknown, status = 200): AxiosResponse {
  return { config, data, status, statusText: String(status), headers: {} };
}
test.beforeEach(() => { useAuth.getState().expire(); useAuth.setState({ user: owner }); });
test.afterEach(() => { useAuth.getState().expire(); api.defaults.adapter = originalAdapter; });

async function mockPricing(page: Page, role: Role = "super_admin") {
  const account = await mockOnboarding(page, { ...owner, role });
  const state = {
    tiers: [{ ...tier }], tierName: null as string | null, price: null as string | null,
    quote: "41.80", malformedQuote: false, malformedTiers: false, writeStatus: 0, readStatus: 200,
    gate: null as Promise<void> | null,
    calls: [] as { path: string; method: string; body: Record<string, unknown> | null; params: Record<string, string> }[],
  };
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(), url = new URL(request.url());
    const path = url.pathname.replace("/api/v1", ""), method = request.method();
    if (!(path.startsWith("/pricing/") || path === "/products" || path.startsWith("/customers"))) {
      await route.fallback(); return;
    }
    const body = request.postData() ? request.postDataJSON() as Record<string, unknown> : null;
    state.calls.push({ path, method, body, params: Object.fromEntries(url.searchParams) });
    const status = method === "GET" ? state.readStatus : state.writeStatus || (method === "DELETE" ? 204 : method === "POST" && path === "/pricing/tiers" ? 201 : 200);
    let data: unknown = {};
    const customer = { id: customerId, name: "Fixture Customer", code: "CUS-FIXTURE", price_tier: state.tierName, is_active: true };
    if (method !== "GET") await state.gate;
    if (status >= 400) data = { detail: [{ input: "untrusted-private-marker", msg: "untrusted-private-marker" }] };
    else if (path === "/pricing/tiers" && method === "GET") data = state.malformedTiers ? [{ id: "bad", name: "Bad", discount_pct: "NaN" }] : state.tiers;
    else if (path === "/pricing/tiers" && method === "POST") {
      const created = { id: "66666666-6666-4666-8666-666666666666", name: String(body?.name), discount_pct: String(body?.discount_pct) };
      state.tiers.push(created); data = created;
    } else if (path.startsWith("/pricing/tiers/") && method === "PATCH") {
      const selected = state.tiers.find((row) => path.endsWith(row.id))!;
      selected.discount_pct = String(body?.discount_pct); data = selected;
    } else if (path === "/pricing/resolve") data = { customer_id: customerId, product_id: productId, price: state.malformedQuote ? 41.8 : state.price ?? state.quote };
    else if (path === "/customers" || path === "/products") {
      const pageNumber = Number(url.searchParams.get("page") || 1);
      const item = path === "/customers" ? customer : { id: productId, name: "Fixture product", sku: "SKU-FIXTURE", unit: "pcs" };
      data = { items: [item], page: pageNumber, page_size: 50, total: 51 };
    } else if (path.endsWith("/pricing-tier")) {
      state.tierName = body?.tier_id ? state.tiers.find((row) => row.id === body.tier_id)?.name ?? null : null;
      data = { ...customer, price_tier: state.tierName };
    } else if (path.endsWith("/prices") && method === "GET") data = state.price === null ? [] : [{ id: tier.id, customer_id: customerId, product_id: productId, price: state.price }];
    else if (path.endsWith("/prices") && method === "POST") {
      state.price = String(body?.price); data = { id: tier.id, customer_id: customerId, product_id: productId, price: state.price };
    } else if (method === "DELETE") state.price = null;
    else data = customer;
    if (status === 204) await route.fulfill({ status });
    else await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
  });
  return { state, account };
}

async function selectCustomer(page: Page) {
  await page.getByLabel("Choose customer", { exact: true }).selectOption(customerId);
  await expect(page.getByTestId("pricing-customer-panel")).toBeVisible();
  await expect(page.getByLabel("Customer tier", { exact: true })).toBeVisible();
}

for (const role of ["super_admin", "warehouse_manager", "accountant"] as const) {
  test(`${role} gets only their distinct pricing capabilities`, async ({ page }) => {
    const { state } = await mockPricing(page, role);
    await page.goto("/pricing");
    await expect(page.getByTestId("pricing-tiers-table")).toBeVisible();
    await expect(page.getByTestId("pricing-tier-new")).toHaveCount(role === "accountant" ? 0 : 1);
    await expect(page.getByTestId("pricing-customer-section")).toHaveCount(role === "warehouse_manager" ? 0 : 1);
    if (role === "warehouse_manager") expect(state.calls.some((call) => call.path.startsWith("/customers"))).toBe(false);
  });
}

test("tier creation and discount editing send exact whitelisted fields with review", async ({ page }) => {
  const { state } = await mockPricing(page);
  await page.goto("/pricing");
  await page.getByTestId("pricing-tier-new").click();
  await page.getByLabel("Tier name", { exact: true }).fill("New tier");
  await page.getByLabel("Discount percent", { exact: true }).fill("10.5");
  await page.getByTestId("pricing-tier-save").click();
  expect(state.calls.filter((call) => call.method === "POST")).toHaveLength(0);
  await page.getByLabel("I reviewed the tier and future-order pricing change.").check();
  await page.getByTestId("pricing-tier-save").click();
  await expect(page.getByTestId("pricing-tier-dialog")).toHaveCount(0);
  expect(state.calls.find((call) => call.method === "POST")?.body).toEqual({ name: "New tier", discount_pct: "10.50" });
  await page.getByRole("button", { name: "Edit discount for Wholesale" }).click();
  await expect(page.getByLabel("Tier name", { exact: true })).toHaveAttribute("readonly");
  await page.getByLabel("Discount percent", { exact: true }).fill("0");
  await page.getByLabel("I reviewed the tier and future-order pricing change.").check();
  await page.getByTestId("pricing-tier-save").click();
  await expect(page.getByTestId("pricing-tier-dialog")).toHaveCount(0);
  expect(state.calls.find((call) => call.method === "PATCH")?.body).toEqual({ discount_pct: "0.00" });
});

test("customer tier selection is an ID binding, not an arbitrary tier or tenant string", async ({ page }) => {
  const { state } = await mockPricing(page, "accountant");
  await page.goto("/pricing");
  await selectCustomer(page);
  await page.getByLabel("Customer tier", { exact: true }).selectOption(tier.id);
  await expect(page.getByTestId("pricing-tier-assign")).toBeDisabled();
  await page.getByLabel("I reviewed this customer and the future-order price change.").check();
  await page.getByTestId("pricing-tier-assign").click();
  await expect(page.getByTestId("pricing-customer-panel")).toContainText("Current tier: Wholesale");
  expect(state.calls.find((call) => call.path.endsWith("/pricing-tier"))?.body).toEqual({ tier_id: tier.id });
});

test("zero customer overrides are real server quotes and removal explicitly refetches", async ({ page }) => {
  const { state } = await mockPricing(page);
  await page.goto("/pricing");
  await selectCustomer(page);
  await page.getByLabel("Choose product", { exact: true }).selectOption(productId);
  await expect(page.getByTestId("pricing-effective-price")).toContainText("41.80");
  await page.getByLabel("Customer price before tax", { exact: true }).fill("0");
  await page.getByLabel("I reviewed this customer and the future-order price change.").check();
  await page.getByTestId("pricing-override-save").click();
  await expect(page.getByTestId("pricing-effective-price")).toContainText("0.00");
  expect(state.calls.find((call) => call.method === "POST")?.body).toEqual({ product_id: productId, price: "0.00" });
  await page.getByLabel("I reviewed this customer and the future-order price change.").check();
  await page.getByTestId("pricing-override-remove").click();
  await expect(page.getByTestId("pricing-effective-price")).toContainText("41.80");
  expect(state.calls.filter((call) => call.method === "DELETE")).toHaveLength(1);
});

test("real directory pagination is bounded and carries no tenant authority", async ({ page }) => {
  const { state } = await mockPricing(page);
  await page.goto("/pricing");
  await expect(page.getByLabel("Choose customer", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Next customers", exact: true }).click();
  await expect.poll(() => state.calls.filter((call) => call.path === "/customers").at(-1)?.params.page).toBe("2");
  expect(state.calls.filter((call) => call.path === "/customers").every((call) => call.params.page_size === "50" && !("tenant_id" in call.params))).toBe(true);
});

test("malformed and failed pricing reads are not an empty list or a fabricated zero", async ({ page }) => {
  const { state } = await mockPricing(page);
  state.malformedTiers = true;
  await page.goto("/pricing");
  await expect(page.getByTestId("pricing-page").getByRole("alert")).toContainText("could not be loaded");
  await expect(page.getByTestId("pricing-tier-new")).toBeDisabled();
  state.malformedTiers = false;
  await page.getByRole("button", { name: "Refresh tiers", exact: true }).click();
  await selectCustomer(page);
  state.malformedQuote = true;
  await page.getByLabel("Choose product", { exact: true }).selectOption(productId);
  await expect(page.getByTestId("pricing-customer-panel").getByRole("alert")).toContainText("No price is inferred");
  await expect(page.getByTestId("pricing-effective-price")).toHaveCount(0);
});

test("failed writes are private and require a fresh review rather than an automatic replay", async ({ page }) => {
  const { state } = await mockPricing(page);
  await page.goto("/pricing");
  await selectCustomer(page);
  state.writeStatus = 503;
  await page.getByLabel("I reviewed this customer and the future-order price change.").check();
  await page.getByTestId("pricing-tier-assign").click();
  await expect(page.getByTestId("pricing-customer-panel").getByRole("alert")).toContainText("could not be confirmed");
  await expect(page.locator("body")).not.toContainText("untrusted-private-marker");
  await expect(page.getByTestId("pricing-tier-assign")).toBeDisabled();
  expect(state.calls.filter((call) => call.method === "PATCH")).toHaveLength(1);
  state.writeStatus = 0;
  await page.getByRole("button", { name: "Refresh pricing", exact: true }).click();
  await page.getByLabel("I reviewed this customer and the future-order price change.").check();
  await expect(page.getByTestId("pricing-tier-assign")).toBeEnabled();
});

test("pricing fits narrow screens and private page headers prevent indexing", async ({ page, request }) => {
  const reply = await request.get("/pricing");
  expect(reply.headers()["cache-control"]).toContain("no-store");
  expect(reply.headers()["referrer-policy"]).toBe("no-referrer");
  expect(reply.headers()["x-robots-tag"]).toBe("noindex, nofollow");
  await mockPricing(page);
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/pricing");
  await selectCustomer(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("duplicate tier submits do not create or audit two pricing changes", async ({ page }) => {
  const { state } = await mockPricing(page);
  const gate = deferred();
  state.gate = gate.promise;
  await page.goto("/pricing");
  await page.getByTestId("pricing-tier-new").click();
  await page.getByLabel("Tier name", { exact: true }).fill("Single request tier");
  await page.getByLabel("Discount percent", { exact: true }).fill("5");
  await page.getByLabel("I reviewed the tier and future-order pricing change.").check();
  await page.getByTestId("pricing-tier-dialog").locator("form").evaluate((form) => {
    (form as HTMLFormElement).requestSubmit();
    (form as HTMLFormElement).requestSubmit();
  });
  await expect.poll(() => state.calls.filter((call) => call.method === "POST").length).toBe(1);
  await expect(page.getByTestId("pricing-tier-save")).toBeDisabled();
  gate.resolve();
  await expect(page.getByTestId("pricing-tier-dialog")).toHaveCount(0);
  expect(state.calls.filter((call) => call.method === "POST")).toHaveLength(1);
});

test("late pricing results cannot cross account or role epochs", async () => {
  const gate = deferred(), started = deferred();
  const scope = pricingScope(owner, useAuth.getState().sessionVersion)!;
  api.defaults.adapter = async (config) => { started.resolve(); await gate.promise; return response(config, [tier]); };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const pending = client.fetchQuery(tiersQuery(scope)).catch((error: unknown) => error);
  await started.promise;
  useAuth.setState({ user: otherOwner, sessionVersion: scope.sessionVersion + 1 });
  gate.resolve();
  expect(axios.isCancel(await pending)).toBe(true);
  expect(client.getQueryData([...pricingKey(scope), "tiers"])).toBeUndefined();
  client.clear();
});

test("privileged pricing helpers reject stale roles and malformed IDs before HTTP", async () => {
  let calls = 0;
  api.defaults.adapter = async (config) => { calls += 1; return response(config, []); };
  const manager = { ...owner, role: "warehouse_manager" as const };
  useAuth.setState({ user: manager });
  const scope = pricingScope(manager, useAuth.getState().sessionVersion)!;
  const failure = await saveOverride(scope, customerId, productId, "1.00", new AbortController().signal).catch((error: unknown) => error);
  expect(axios.isCancel(failure)).toBe(true);
  useAuth.setState({ user: owner });
  const ownerScope = pricingScope(owner, useAuth.getState().sessionVersion)!;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await client.fetchQuery(quoteQuery(ownerScope, "../auth/login", productId)).catch(() => undefined);
  client.clear();
  expect(calls).toBe(0);
});

test("write helpers whitelist fields, retain decimal strings and bind returned targets", async () => {
  const scope = pricingScope(owner, useAuth.getState().sessionVersion)!;
  const sent: unknown[] = [];
  api.defaults.adapter = async (config) => {
    sent.push(config.data ? JSON.parse(config.data as string) : null);
    if (config.method === "delete") return response(config, "", 204);
    if (config.url?.includes("/pricing/tiers")) return response(config, { ...tier, discount_pct: "5.00", unknown_secret: "private-marker" });
    if (config.url?.endsWith("/pricing-tier")) return response(config, { id: customerId, name: "Customer", code: "C", price_tier: tier.name, is_active: true });
    return response(config, { id: tier.id, customer_id: customerId, product_id: productId, price: "0.00" });
  };
  const signal = new AbortController().signal;
  const result = await saveTier(scope, tier, "ignored rename", "5", signal);
  expect(Object.keys(result).sort()).toEqual(["discount_pct", "id", "name"]);
  await assignCustomerTier(scope, customerId, tier, signal);
  await saveOverride(scope, customerId, productId, "0", signal);
  await removeOverride(scope, customerId, productId, signal);
  expect(sent).toEqual([{ discount_pct: "5.00" }, { tier_id: tier.id }, { product_id: productId, price: "0.00" }, null]);
});

test("directory and quote cache schemas discard unknown fields and wrong targets fail closed", async () => {
  const scope = pricingScope(owner, useAuth.getState().sessionVersion)!;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  api.defaults.adapter = async (config) => response(config, config.url === "/customers"
    ? { items: [{ id: customerId, name: "Customer", code: "C", price_tier: null, is_active: true, unknown_secret: "private-marker" }], page: 1, page_size: 50, total: 1 }
    : { customer_id: customerId, product_id: productId, price: "41.80", unknown_secret: "private-marker" });
  const choices = await client.fetchQuery(choicesQuery(scope, "customers", 1, ""));
  const quote = await client.fetchQuery(quoteQuery(scope, customerId, productId));
  expect(JSON.stringify([choices, quote])).not.toContain("private-marker");
  api.defaults.adapter = async (config) => response(config, { customer_id: otherOwner.id, product_id: productId, price: "0.00" });
  await expect(client.fetchQuery(quoteQuery(scope, customerId, tier.id))).rejects.toThrow();
  client.clear();
});
