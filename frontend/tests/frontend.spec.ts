import { test, expect, type Page } from "@playwright/test";
import type { AuthUser, Role } from "../src/lib/auth";

const user: AuthUser = {
  id: "staff-a", tenant_id: "tenant-a", email: "staff-a@example.test",
  full_name: "Staff A", role: "super_admin", is_active: true,
};
const otherUser: AuthUser = {
  ...user, id: "staff-b", tenant_id: "tenant-b", email: "staff-b@example.test", full_name: "Staff B",
};
const products = {
  "staff-a": [{ id: "product-a", sku: "A", name: "Product A", unit: "kg", base_price: "10.00" }],
  "staff-b": [{ id: "product-b", sku: "B", name: "Product B", unit: "kg", base_price: "20.00" }],
};

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}

async function mockApi(page: Page, initialUser: AuthUser | null = user) {
  const state = {
    user: initialUser,
    loginUser: initialUser || user,
    accessValid: true,
    meStatus: 200,
    refreshStatus: initialUser ? 200 : 401,
    setupComplete: true,
    setupStatus: 200,
    setupGate: null as Promise<void> | null,
    productsGate: null as Promise<void> | null,
    inventoryGate: null as Promise<void> | null,
    aiCapabilities: { free_only_mode: true, can_request_summary: false, summary_status: "held_free_only" },
    summaryResponseStatus: "" as string,
    summaryRequests: [] as boolean[],
    calls: [] as { path: string; method: string; body: unknown }[],
  };
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname !== "127.0.0.1" && url.hostname !== "localhost") await route.abort();
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
    switch (path) {
      case "/auth/me":
        status = state.meStatus !== 200 ? state.meStatus : (!state.user || !state.accessValid ? 401 : 200);
        data = status === 200 ? state.user : { detail: "Session unavailable." };
        break;
      case "/auth/refresh":
        status = state.refreshStatus;
        if (status === 200) state.accessValid = true;
        data = status === 200 ? {} : { detail: "Refresh unavailable." };
        break;
      case "/auth/login":
        state.user = (body as { email: string }).email === otherUser.email ?
          { ...otherUser, role: state.loginUser.role } : state.loginUser;
        state.accessValid = true;
        data = { user: state.user };
        break;
      case "/auth/logout":
        state.user = null;
        break;
      case "/setup/status":
        await state.setupGate;
        status = state.setupStatus;
        data = status === 200 ? { is_setup_complete: state.setupComplete } : { detail: "Setup unavailable." };
        break;
      case "/settings":
        data = {
          tenant_id: state.user?.tenant_id, company_name: state.user?.id === "staff-b" ? "Company B" : "Company A",
          currency_code: "INR", currency_symbol: "INR", locale: "en-IN", values: {},
        };
        break;
      case "/products": {
        await state.productsGate;
        const items = products[state.user?.id === "staff-b" ? "staff-b" : "staff-a"];
        data = { items, total: items.length, page: 1, page_size: 200 };
        break;
      }
      case "/warehouses":
        data = [{ id: "warehouse-a", name: "Warehouse A", code: "WH-A" }];
        break;
      case "/customers":
        data = { items: [{ id: "customer-a", name: "Customer A", code: "CUS-A", customer_type: "cash", is_active: true,
          credit_limit: "0.00", outstanding: "0.00", credit_held: "0.00", cash_funded_pending: "0.00",
          credit_exposure: "0.00", available_credit: "0.00", advance_balance: "0.00" }] };
        break;
      case "/inventory": {
        await state.inventoryGate;
        if (!state.accessValid) { status = 401; data = { detail: "Access expired." }; break; }
        const product = products[state.user?.id === "staff-b" ? "staff-b" : "staff-a"][0];
        data = [{
          id: `inventory-${state.user?.id}`, product_id: product.id, product_sku: product.sku,
          product_name: product.name, warehouse_id: "warehouse-a", warehouse_name: "Warehouse A",
          quantity: "20", reserved_qty: "0", available_qty: "20", damaged_qty: "0", low_stock: false,
        }];
        break;
      }
      case "/inventory/stats":
        data = { total_products: 1, low_stock: 0, out_of_stock: 0, total_inventory_value: "200.00", total_reserved: "0" };
        break;
      case "/orders/stats":
        data = { total_orders: 0, pending: 0, confirmed: 0, reserved: 0, out_for_delivery: 0, delivered_today: 0, revenue_today: "0.00" };
        break;
      case "/orders":
        data = method === "POST" ? { id: "order-a", status: "pending" } : { items: [] };
        break;
      case "/payments":
      case "/deliveries":
      case "/ai/alerts":
        data = [];
        break;
      case "/ai/capabilities":
        data = state.aiCapabilities;
        break;
      case "/ai/analyze": {
        const requested = new URL(request.url()).searchParams.get("include_summary") === "true";
        state.summaryRequests.push(requested);
        const summaryStatus = state.summaryResponseStatus || (requested
          ? state.aiCapabilities.can_request_summary ? "queued" : "held_free_only" : "not_requested");
        data = { counts: { low_stock: 1, credit_risk: 1 }, summary_status: summaryStatus };
        if (summaryStatus === "held_free_only") {
          state.aiCapabilities = { free_only_mode: true, can_request_summary: false, summary_status: "held_free_only" };
        }
        break;
      }
      default:
        status = 404;
        data = { detail: "Unexpected frontend test route." };
    }
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
  });
  return state;
}

async function signIn(page: Page, email = user.email) {
  await page.getByTestId("login-email").fill(email);
  await page.getByTestId("login-password").fill("test-password");
  await page.getByTestId("login-submit").click();
}

test("free mode visibly holds summaries without blocking genuine rule checks", async ({ page }) => {
  const state = await mockApi(page);
  await page.goto("/ai-supervisor");
  await expect(page.getByTestId("ai-summary-status")).toContainText("On hold");
  await expect(page.getByTestId("ai-run-summary")).toBeDisabled();
  await page.getByTestId("ai-run-rules").click();
  await expect(page.getByText("Analysis complete. 2 rule alerts refreshed.", { exact: true })).toBeVisible();
  expect(state.summaryRequests).toEqual([false]);
  await expect(page.getByText("Generative summary queued.", { exact: false })).toHaveCount(0);
});

test("a stale summary capability cannot produce a false queued claim", async ({ page }) => {
  const state = await mockApi(page);
  state.aiCapabilities = { free_only_mode: false, can_request_summary: true, summary_status: "configured" };
  state.summaryResponseStatus = "held_free_only";
  await page.goto("/ai-supervisor");
  await expect(page.getByTestId("ai-run-summary")).toBeEnabled();
  await page.getByTestId("ai-run-summary").click();
  await expect(page.getByText("Generative summaries are on hold; rule checks completed.", { exact: true })).toBeVisible();
  await expect(page.getByTestId("ai-summary-status")).toContainText("On hold");
  await expect(page.getByTestId("ai-run-summary")).toBeDisabled();
  expect(state.summaryRequests).toEqual([true]);
  await expect(page.getByText("Generative summary queued.", { exact: false })).toHaveCount(0);
});

for (const start of ["inventory", "orders"]) {
  test(`product selectors survive cached ${start}-first navigation`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const state = await mockApi(page);
    await page.goto(`/${start}`);
    await expect(page.getByTestId("admin-shell")).toBeVisible();
    if (start === "inventory") {
      await page.getByTestId("inv-adjust-open").click();
      await expect(page.getByTestId("adjust-product").locator("option[value='product-a']")).toHaveCount(1);
      await page.getByTestId("adjust-cancel").click();
      await page.getByTestId("nav-orders").click();
      await page.getByTestId("orders-new").click();
      await expect(page.getByTestId("order-line-0").locator("option[value='product-a']")).toHaveCount(1);
    } else {
      await page.getByTestId("orders-new").click();
      await expect(page.getByTestId("order-line-0").locator("option[value='product-a']")).toHaveCount(1);
      await page.getByTestId("order-cancel").click();
      await page.getByTestId("nav-inventory").click();
      await page.getByTestId("inv-adjust-open").click();
      await expect(page.getByTestId("adjust-product").locator("option[value='product-a']")).toHaveCount(1);
    }
    expect(state.calls.filter((call) => call.path === "/products")).toHaveLength(1);
    expect(errors).toEqual([]);
  });
}

test("an adjustment opened before products arrive has a usable controlled selection", async ({ page }) => {
  const state = await mockApi(page);
  const gate = deferred();
  state.productsGate = gate.promise;
  await page.goto("/inventory");
  await page.getByTestId("inv-adjust-open").click();
  await expect(page.getByTestId("adjust-product")).toHaveValue("");
  gate.resolve();
  await page.getByTestId("adjust-product").selectOption("product-a");
  await page.getByTestId("adjust-warehouse").selectOption("warehouse-a");
  await expect(page.getByTestId("adjust-submit")).toBeEnabled();
});

test("new order sends server-owned pricing input and cannot submit zero lines", async ({ page }) => {
  const state = await mockApi(page);
  await page.goto("/orders");
  await page.getByTestId("orders-new").click();
  await page.getByTestId("order-customer").selectOption("customer-a");
  await page.getByTestId("order-warehouse").selectOption("warehouse-a");
  await page.getByTestId("order-line-0").locator("select").selectOption("product-a");
  await page.getByTestId("order-line-0").locator("input").fill("2");
  await page.getByTestId("order-submit").click();
  await expect(page.getByTestId("order-modal")).toHaveCount(0);
  expect(state.calls.find((call) => call.path === "/orders" && call.method === "POST")?.body).toEqual({
    customer_id: "customer-a", warehouse_id: "warehouse-a",
    items: [{ product_id: "product-a", quantity: "2" }],
  });
  await page.getByTestId("orders-new").click();
  await page.getByTestId("order-customer").selectOption("customer-a");
  await page.getByTestId("order-warehouse").selectOption("warehouse-a");
  await page.getByTestId("order-line-0").locator("button").click();
  await expect(page.getByTestId("order-submit")).toBeDisabled();
});

test("expired access bootstraps through refresh without dropping the authenticated shell", async ({ page }) => {
  const state = await mockApi(page);
  state.accessValid = false;
  await page.goto("/inventory");
  await expect(page.getByTestId("admin-shell")).toBeVisible();
  expect(state.calls.filter((call) => call.path === "/auth/me")).toHaveLength(2);
  expect(state.calls.filter((call) => call.path === "/auth/refresh")).toHaveLength(1);
});

test("expired refresh removes the shell and cached company data", async ({ page }) => {
  const state = await mockApi(page);
  await page.goto("/inventory");
  await expect(page.getByText("Company A", { exact: true })).toBeVisible();
  state.accessValid = false;
  state.refreshStatus = 401;
  await page.getByTestId("inv-refresh").click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByTestId("admin-shell")).toHaveCount(0);
  await expect(page.getByText("Company A", { exact: true })).toHaveCount(0);
  expect(state.calls.filter((call) => call.path === "/auth/refresh")).toHaveLength(1);
});

test("bootstrap network failure is visible and retryable instead of a silent anonymous session", async ({ page }) => {
  const state = await mockApi(page);
  state.meStatus = 503;
  await page.goto("/inventory");
  await expect(page.getByRole("alert").filter({ hasText: "Session unavailable." })).toBeVisible();
  state.meStatus = 200;
  await page.getByTestId("auth-retry").click();
  await expect(page.getByTestId("admin-shell")).toBeVisible();
});

test("logout and another tenant login cannot reuse inventory, products or settings", async ({ page }) => {
  const state = await mockApi(page, { ...user, role: "warehouse_manager" });
  await page.goto("/inventory");
  await expect(page.getByTestId("inv-row-inventory-staff-a")).toBeVisible();
  await page.getByTestId("inv-adjust-open").click();
  await expect(page.getByTestId("adjust-product").locator("option[value='product-a']")).toHaveCount(1);
  await page.getByTestId("adjust-cancel").click();
  await page.getByTestId("logout-button").click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByText("Company A", { exact: true })).toHaveCount(0);
  const gate = deferred();
  state.inventoryGate = gate.promise;
  await signIn(page, otherUser.email);
  await expect(page).toHaveURL(/\/inventory$/);
  await expect(page.getByTestId("inv-row-inventory-staff-a")).toHaveCount(0);
  gate.resolve();
  await expect(page.getByTestId("inv-row-inventory-staff-b")).toBeVisible();
  await expect(page.getByText("Company B", { exact: true })).toBeVisible();
  await page.getByTestId("inv-adjust-open").click();
  await expect(page.getByTestId("adjust-product").locator("option[value='product-b']")).toHaveCount(1);
  await expect(page.getByTestId("adjust-product").locator("option[value='product-a']")).toHaveCount(0);
  expect(state.calls.filter((call) => call.path === "/products")).toHaveLength(2);
});

for (const [role, home, links] of [
  ["super_admin", "dashboard", ["inventory", "finance", "settings"]],
  ["warehouse_manager", "inventory", ["inventory", "warehouses", "products", "orders", "deliveries"]],
  ["accountant", "finance", ["customers", "finance"]],
] as const) {
  test(`${role} login lands on its staff home with scoped navigation`, async ({ page }) => {
    const state = await mockApi(page, null);
    state.loginUser = { ...user, role };
    await page.goto("/login");
    await signIn(page);
    await expect(page).toHaveURL(new RegExp(`/${home}$`));
    for (const link of links) await expect(page.getByTestId(`nav-${link}`)).toBeVisible();
    if (role !== "super_admin") {
      await expect(page.getByTestId("nav-settings")).toHaveCount(0);
      await expect(page.getByTestId("nav-ai-supervisor")).toHaveCount(0);
      await expect(page.getByTestId("nav-audit")).toHaveCount(0);
    }
  });
  test(`${role} root bootstrap redirects to its staff home`, async ({ page }) => {
    await mockApi(page, { ...user, role });
    await page.goto("/");
    await expect(page).toHaveURL(new RegExp(`/${home}$`));
    await expect(page.getByTestId("admin-shell")).toBeVisible();
  });
}

test("first-launch bootstrap still reaches setup without a staff session", async ({ page }) => {
  const state = await mockApi(page, null);
  state.setupComplete = false;
  await page.goto("/");
  await expect(page).toHaveURL(/\/setup$/);
  await expect(page.getByTestId("setup-wizard")).toBeVisible();
});

test("slow public setup status still completes after anonymous bootstrap expires", async ({ page }) => {
  const state = await mockApi(page, null);
  const gate = deferred();
  state.setupGate = gate.promise;
  state.setupComplete = false;
  const refresh = page.waitForResponse((response) => response.url().endsWith("/auth/refresh"));
  await page.goto("/");
  await refresh;
  await expect(page.getByTestId("root-loading")).toContainText("Initializing SupplyOS...");
  gate.resolve();
  await expect(page).toHaveURL(/\/setup$/);
  await expect(page.getByTestId("setup-wizard")).toBeVisible();
});

test("setup API failure is visible and retryable rather than leaving a blank root page", async ({ page }) => {
  const state = await mockApi(page, null);
  state.setupStatus = 503;
  await page.goto("/");
  await expect(page.getByRole("alert").filter({ hasText: "Setup unavailable." })).toBeVisible();
  state.setupStatus = 200;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
});

for (const [role, denied, home, forbiddenApi] of [
  ["warehouse_manager", "finance", "inventory", "/payments"],
  ["accountant", "inventory", "finance", "/inventory"],
] as const) {
  test(`${role} direct restricted route never mounts its data-fetching page`, async ({ page }) => {
    const state = await mockApi(page, { ...user, role });
    await page.goto(`/${denied}`);
    await expect(page).toHaveURL(new RegExp(`/${home}$`));
    await expect(page.getByTestId("admin-shell")).toBeVisible();
    expect(state.calls.some((call) => call.path === forbiddenApi)).toBe(false);
    await expect(page.getByTestId(`nav-${denied}`)).toHaveCount(0);
  });
}

for (const role of ["customer", "delivery_partner"] as Role[]) {
  test(`${role} never mounts the staff shell or loads tenant settings`, async ({ page }) => {
    const state = await mockApi(page, { ...user, role });
    await page.goto("/inventory");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByTestId("staff-access-denied")).toBeVisible();
    await expect(page.getByTestId("admin-shell")).toHaveCount(0);
    expect(state.calls.some((call) => ["/inventory", "/settings"].includes(call.path))).toBe(false);
    await page.getByTestId("staff-sign-out").click();
    await expect(page.getByTestId("login-form")).toBeVisible();
  });
}

test("mobile manager navigation retains light/dark controls and only permitted links", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ colorScheme: "light" });
  await mockApi(page, { ...user, role: "warehouse_manager" });
  await page.goto("/inventory");
  await expect(page.getByTestId("mobile-menu-open")).toBeVisible();
  await page.getByTestId("mobile-menu-open").click();
  const drawer = page.getByTestId("mobile-drawer");
  await expect(drawer).toBeVisible();
  await expect(drawer.getByTestId("nav-orders")).toBeVisible();
  await expect(drawer.getByTestId("nav-finance")).toHaveCount(0);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await drawer.getByTestId("theme-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await drawer.getByTestId("drawer-close").click();
  await expect(drawer).toHaveCount(0);
});

for (const path of ["/api/v1/__proxy-test", "/api/__proxy-test"]) {
  test(`same-origin proxy forwards ${path}, query, body, auth and response cookies`, async ({ request }) => {
    const response = await request.post(`${path}?page=2&q=stock`, {
      headers: { Cookie: "session=test-only", Authorization: "Bearer test-only", "X-Request-Id": "regression-test" },
      data: { note: "test-only" },
    });
    expect(response.status()).toBe(200);
    expect(await response.json()).toEqual({
      url: `${path}?page=2&q=stock`, method: "POST", cookie: "session=test-only",
      authorization: "Bearer test-only", requestId: "regression-test", body: JSON.stringify({ note: "test-only" }),
    });
    expect(response.headers()["set-cookie"]).toContain("proxy_test=ok");
  });
}
