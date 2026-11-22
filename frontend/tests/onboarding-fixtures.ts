import type { Page } from "@playwright/test";
import type { AuthUser } from "../src/lib/auth";
import type { StaffMember } from "../src/lib/staff";

export const owner: AuthUser = {
  id: "11111111-1111-4111-8111-111111111111", tenant_id: "22222222-2222-4222-8222-222222222222",
  email: "owner@fixture.test", full_name: "Fixture Owner", role: "super_admin", is_active: true,
};
export const otherOwner: AuthUser = {
  ...owner, id: "33333333-3333-4333-8333-333333333333", tenant_id: "44444444-4444-4444-8444-444444444444",
  email: "other-owner@fixture.test", full_name: "Other Fixture Owner",
};
export const staffMember: StaffMember = {
  id: "55555555-5555-4555-8555-555555555555", email: "staff@fixture.test", full_name: "Fixture Staff",
  phone: null, role: "warehouse_manager", is_active: true, created_at: "2026-11-12T08:00:00Z",
};
export const otherStaff: StaffMember = {
  ...staffMember, id: "66666666-6666-4666-8666-666666666666", email: "other-staff@fixture.test", full_name: "Other Fixture Staff",
};
export const fixturePassword = "holder-chosen-fixture-password";
export const fixtureAuthorization = "isolated-operator-setup-authorization-A19_b7";

export function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}

function customer(id: string, name: string) {
  return { id, code: "CUS-FIXTURE", name, business_name: null, phone: null, gstin: null, price_tier: null,
    customer_type: "cash", is_active: true, credit_limit: "0.00", outstanding: "0.00", credit_held: "0.00",
    cash_funded_pending: "0.00", credit_exposure: "0.00", available_credit: "0.00", advance_balance: "0.00" };
}

export interface FixtureCall {
  path: string; method: string; query: string; body: Record<string, unknown> | null;
  hasSetupAuthorization: boolean; authorizationMatches: boolean; passwordMatches: boolean;
}

export async function mockOnboarding(page: Page, initialUser: AuthUser | null = owner) {
  const state = {
    user: initialUser, loginUser: owner, meStatus: 200,
    meGate: null as Promise<void> | null, statusGate: null as Promise<void> | null,
    staffGate: null as Promise<void> | null, customersGate: null as Promise<void> | null,
    mutationGate: null as Promise<void> | null,
    setup: { is_setup_complete: false, is_initialized: false, authorization_configured: true },
    setupStatus: 200, setupResponse: null as unknown,
    initializeStatus: 201, initializeResponse: null as unknown,
    staffStatus: 200, mutationStatus: 0, customersStatus: 200, customersResponse: null as unknown,
    abortMutation: false, errorDetail: "Untrusted upstream error",
    expectedPassword: fixturePassword, expectedAuthorization: fixtureAuthorization,
    totalStaff: 1,
    staff: { [owner.id]: [staffMember], [otherOwner.id]: [otherStaff] } as Record<string, StaffMember[]>,
    customers: { [owner.id]: [customer("77777777-7777-4777-8777-777777777777", "Fixture Customer")],
      [otherOwner.id]: [customer("88888888-8888-4888-8888-888888888888", "Other Fixture Customer")] },
    calls: [] as FixtureCall[],
  };
  await page.route("**/*", async (route) => {
    const host = new URL(route.request().url()).hostname;
    if (!["localhost", "127.0.0.1"].includes(host)) await route.abort();
    else await route.continue();
  });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/v1", "");
    const method = request.method();
    const body = request.postData() ? request.postDataJSON() as Record<string, unknown> : null;
    const authorization = await request.headerValue("x-setup-authorization");
    const redacted = body ? { ...body } : null;
    for (const field of ["password", "admin_password", "setup_authorization"]) {
      if (redacted && field in redacted) redacted[field] = "[redacted]";
    }
    state.calls.push({ path, method, query: url.search, body: redacted,
      hasSetupAuthorization: authorization !== null, authorizationMatches: authorization === state.expectedAuthorization,
      passwordMatches: body?.password === state.expectedPassword || body?.admin_password === state.expectedPassword });
    let status = 200;
    let data: unknown = {};
    const userSnapshot = state.user;
    const identity = userSnapshot?.id === otherOwner.id ? otherOwner.id : owner.id;
    const staffSnapshot = [...(state.staff[identity] || [])];
    const customerSnapshot = [...state.customers[identity]];
    if (path === "/auth/me") {
      await state.meGate;
      status = state.meStatus !== 200 ? state.meStatus : userSnapshot ? 200 : 401;
      data = status === 200 ? userSnapshot : { detail: "Fixture session unavailable" };
    } else if (path === "/auth/refresh") {
      status = 401; data = { detail: "Fixture refresh unavailable" };
    } else if (path === "/auth/login") {
      state.user = body?.email === otherOwner.email ? otherOwner : state.loginUser;
      data = { user: state.user };
    } else if (path === "/auth/logout") {
      state.user = null;
    } else if (path === "/setup/status") {
      await state.statusGate;
      status = state.setupStatus;
      data = status === 200 ? state.setupResponse || { ...state.setup, tenant_id: null, company_name: null } : { detail: state.errorDetail };
    } else if (path === "/setup/initialize") {
      await state.mutationGate;
      if (state.abortMutation) { await route.abort("failed"); return; }
      status = state.initializeStatus;
      if (status === 201) state.setup = { is_setup_complete: true, is_initialized: true, authorization_configured: true };
      data = status < 400 ? state.initializeResponse || { ...state.setup, tenant_id: owner.tenant_id, company_name: "Fixture company" } : { detail: state.errorDetail };
    } else if (path === "/settings") {
      data = { tenant_id: userSnapshot?.tenant_id, company_name: identity === owner.id ? "Fixture Company" : "Other Fixture Company",
        currency_code: "INR", currency_symbol: "INR", locale: "en-IN", values: {} };
    } else if (path === "/staff" && method === "GET") {
      await state.staffGate;
      status = state.staffStatus;
      const number = Number(url.searchParams.get("page") || "1");
      data = status === 200 ? { items: number === 1 ? staffSnapshot : [otherStaff], total: state.totalStaff, page: number, page_size: 50 } : { detail: state.errorDetail };
    } else if (path === "/customers" && method === "GET") {
      await state.customersGate;
      status = state.customersStatus;
      data = status === 200 ? state.customersResponse || { items: customerSnapshot, total: customerSnapshot.length, page: 1, page_size: 200 } : { detail: state.errorDetail };
    } else if (method !== "GET" && (path === "/staff" || path.startsWith("/staff/") || path === "/customers" || path === "/auth/register-customer")) {
      await state.mutationGate;
      if (state.abortMutation) { await route.abort("failed"); return; }
      status = state.mutationStatus || (method === "POST" && !path.endsWith("/revoke-sessions") ? 201 : 200);
      if (status >= 400) data = { detail: [{ loc: ["body", state.errorDetail], msg: state.errorDetail, input: state.expectedPassword }] };
      else if (path === "/staff") {
        const created = { id: "99999999-9999-4999-8999-999999999999", email: String(body?.email), full_name: String(body?.full_name),
          phone: body?.phone as string | null, role: body?.role as StaffMember["role"], is_active: true, created_at: staffMember.created_at };
        state.staff[identity].push(created); state.totalStaff += 1; data = created;
      } else if (path.endsWith("/revoke-sessions")) data = { message: "Staff sessions revoked" };
      else if (path.startsWith("/staff/")) {
        const id = path.split("/")[2];
        state.staff[identity] = state.staff[identity].map((member) => member.id === id ? { ...member, ...body } as StaffMember : member);
        data = state.staff[identity].find((member) => member.id === id);
      } else if (path === "/auth/register-customer") {
        state.customers[identity].push(customer("99999999-9999-4999-8999-999999999999", String(body?.full_name)));
        data = { id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", tenant_id: userSnapshot?.tenant_id, email: body?.email,
          full_name: body?.full_name, phone: body?.phone, role: "customer", is_active: true };
      } else {
        const created = { ...customer("99999999-9999-4999-8999-999999999999", String(body?.name)), ...body };
        state.customers[identity].push(created as typeof customerSnapshot[number]); data = created;
      }
    } else if (path === "/inventory/stats") data = { total_products: 0, low_stock: 0, out_of_stock: 0, total_inventory_value: "0.00", total_reserved: "0" };
    else if (path === "/orders/stats") data = { total_orders: 0, pending: 0, confirmed: 0, reserved: 0, out_for_delivery: 0, delivered_today: 0, revenue_today: "0.00" };
    else if (["/products", "/orders"].includes(path)) data = { items: [], total: 0, page: 1, page_size: 200 };
    else if (["/inventory", "/payments", "/deliveries", "/warehouses", "/ai/alerts"].includes(path)) data = [];
    else { status = 404; data = { detail: "Unexpected onboarding fixture route" }; }
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
  });
  return state;
}

export async function fillSetupOwner(page: Page, password = fixturePassword, authorization = fixtureAuthorization) {
  await page.getByTestId("setup-company-name").fill(" Fixture Company ");
  await page.getByTestId("setup-next-1").click();
  await page.getByTestId("setup-admin-name").fill(" Fixture Owner ");
  await page.getByTestId("setup-admin-email").fill("owner@fixture.test");
  await page.getByTestId("setup-admin-password").fill(password);
  await page.getByTestId("setup-authorization").fill(authorization);
}

export async function fillStaff(page: Page, password = fixturePassword) {
  await page.getByTestId("staff-name").fill(" New Fixture Staff ");
  await page.getByTestId("staff-email").fill("NEW-STAFF@fixture.test");
  await page.getByTestId("staff-role").selectOption("accountant");
  await page.getByTestId("staff-password").fill(password);
  await page.getByTestId("staff-confirmed").check();
}

export async function noStoredSecrets(page: Page, secrets = [fixturePassword, fixtureAuthorization]) {
  return page.evaluate((values) => {
    const storage = JSON.stringify({ ...localStorage, ...sessionStorage });
    const address = `${window.location.href} ${document.cookie}`;
    return values.every((value) => !storage.includes(value) && !address.includes(value));
  }, secrets);
}
