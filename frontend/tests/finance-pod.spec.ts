import { test as base, expect, type Page } from "@playwright/test";
import type { Payment, OrderFinance } from "../src/lib/finance";
import type { Delivery } from "../src/features/deliveries/workflow";

interface Call {
  path: string; method: string; query: string; body: unknown;
  key: string | null; contentType?: string; cookie?: string;
}
interface Snapshot {
  calls: Call[]; payments: Payment[]; orders: OrderFinance[]; deliveries: Delivery[]; proofCount: number;
}
interface Fixture {
  id: string; customerId: string; secondCustomerId: string; cashOrderId: string;
  creditOrderId: string; deliveryId: string; warehouseId: string; productId: string; png: string;
}

const test = base.extend<{ createApp: (config?: Record<string, unknown>) => Promise<Fixture> }>({
  createApp: async ({ page }, provideFixture) => {
    const ids: string[] = [];
    await page.route("**/*", (route) => {
      const host = new URL(route.request().url()).hostname;
      return host === "127.0.0.1" || host === "localhost" ? route.continue() : route.abort();
    });
    await provideFixture(async (config = {}) => {
      const response = await page.context().request.post("http://127.0.0.1:3801/__fixtures", { data: config });
      expect(response.status()).toBe(201);
      const fixture = await response.json() as Fixture;
      ids.push(fixture.id);
      return fixture;
    });
    for (const id of ids) await page.context().request.delete(`http://127.0.0.1:3801/__fixtures/${id}`);
  },
});

async function inspect(page: Page, fixture: Fixture): Promise<Snapshot> {
  return (await page.context().request.get(`http://127.0.0.1:3801/__fixtures/${fixture.id}`)).json();
}
async function configure(page: Page, fixture: Fixture, data: Record<string, unknown>) {
  await page.context().request.patch(`http://127.0.0.1:3801/__fixtures/${fixture.id}`, { data });
}
async function openPayment(page: Page, fixture: Fixture) {
  await page.getByTestId("pay-new").click();
  await page.getByTestId("pay-customer").selectOption(fixture.customerId);
}
async function fillOrder(page: Page, fixture: Fixture) {
  await page.getByTestId("orders-new").click();
  await page.getByTestId("order-customer").selectOption(fixture.customerId);
  await page.getByTestId("order-warehouse").selectOption(fixture.warehouseId);
  await page.getByTestId("order-line-0").locator("select").selectOption(fixture.productId);
}
async function openDelivery(page: Page, fixture: Fixture) {
  await page.goto(`/deliveries?delivery_id=${fixture.deliveryId}`);
  await expect(page.getByTestId("delivery-detail")).toBeVisible();
  await expect(page.getByTestId("order-balance")).toBeVisible();
}
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

test("accountant allocates a payment using the selected customer's exact server remainder", async ({ page, createApp }) => {
  const fixture = await createApp({ role: "accountant", amountDue: "17.43" });
  await page.goto("/finance");
  await openPayment(page, fixture);
  await expect(page.getByTestId("customer-balance")).toContainText("788.25");
  await expect(page.getByTestId("customer-balance")).toContainText("180.00");
  await expect(page.getByTestId("customer-advance")).toContainText("25.00");
  await expect(page.getByTestId("pay-order").locator("option").filter({ hasText: "ORD-OTHER" })).toHaveCount(0);
  await page.getByTestId("pay-order").selectOption(fixture.cashOrderId);
  await expect(page.getByTestId("order-amount-due")).toContainText("17.43");
  await page.getByTestId("pay-use-due").click();
  await expect(page.getByTestId("pay-amount")).toHaveValue("17.43");
  await page.getByTestId("pay-mode").selectOption("upi");
  await page.getByTestId("pay-ref").fill("UPI-test-only");
  await page.getByTestId("pay-submit").click();
  await expect(page.getByTestId("pay-modal")).toHaveCount(0);
  await expect(page.getByTestId("pay-table")).toContainText("order payment");
  const state = await inspect(page, fixture);
  const call = state.calls.find((item) => item.path === "/payments" && item.method === "POST")!;
  expect(call.body).toEqual({ customer_id: fixture.customerId, order_id: fixture.cashOrderId, amount: "17.43", mode: "upi", reference: "UPI-test-only", note: null });
  expect(call.key).toMatch(uuid);
  expect(state.calls.some((item) => item.path === "/orders" && item.query.includes(`customer_id=${fixture.customerId}`))).toBe(true);
  await expect(page.getByTestId("nav-orders")).toHaveCount(0);
});

test("identical unallocated payments remain distinct intents even for inactive customer settlements", async ({ page, createApp }) => {
  const fixture = await createApp({ inactiveCustomer: true });
  await page.goto("/finance");
  for (let index = 0; index < 2; index++) {
    await openPayment(page, fixture);
    await expect(page.getByTestId("pay-unallocated")).toContainText("not payment of an order");
    await page.getByTestId("pay-amount").fill("10");
    await page.getByTestId("pay-submit").click();
    await expect(page.getByTestId("pay-modal")).toHaveCount(0);
  }
  const state = await inspect(page, fixture);
  const calls = state.calls.filter((item) => item.path === "/payments" && item.method === "POST");
  expect(calls).toHaveLength(2);
  expect(calls[0].body).toEqual(calls[1].body);
  expect(calls[0].key).not.toBe(calls[1].key);
  expect(state.payments).toHaveLength(2);
  expect(state.payments.every((item) => item.order_id === null && item.allocation_kind === "unallocated_advance")).toBe(true);
});

test("credit notes cannot stay linked to an order", async ({ page, createApp }) => {
  const fixture = await createApp();
  await page.goto("/finance");
  await openPayment(page, fixture);
  await page.getByTestId("pay-order").selectOption(fixture.creditOrderId);
  await page.getByTestId("pay-mode").selectOption("credit");
  await expect(page.getByTestId("pay-order")).toBeDisabled();
  await expect(page.getByTestId("pay-order")).toHaveValue("");
  await page.getByTestId("pay-amount").fill("5.00");
  await page.getByTestId("pay-submit").click();
  await expect(page.getByTestId("pay-modal")).toHaveCount(0);
  expect((await inspect(page, fixture)).payments[0]).toMatchObject({ mode: "credit", order_id: null, allocation_kind: "credit_note" });
});

test("a network-failed payment retains its key and draft when the dialog is reopened", async ({ page, createApp }) => {
  const fixture = await createApp();
  let failedKey: string | undefined;
  let fail = true;
  await page.route("**/api/v1/payments", async (route) => {
    if (route.request().method() === "POST" && fail) {
      fail = false; failedKey = route.request().headers()["x-idempotency-key"];
      await route.abort("failed");
    } else await route.continue();
  });
  await page.goto("/finance");
  await openPayment(page, fixture);
  await page.getByTestId("pay-amount").fill("10.00");
  await page.getByTestId("pay-submit").click();
  await expect(page.getByTestId("pay-unconfirmed")).toBeVisible();
  await page.getByTestId("pay-close").click();
  await page.getByTestId("pay-new").click();
  await expect(page.getByTestId("pay-amount")).toHaveValue("10.00");
  await page.getByTestId("pay-submit").click();
  await expect(page.getByTestId("pay-modal")).toHaveCount(0);
  const state = await inspect(page, fixture);
  expect(state.calls.find((item) => item.path === "/payments" && item.method === "POST")?.key).toBe(failedKey);
  expect(state.payments).toHaveLength(1);
});

test("a lost payment response replays one receipt through the real Next proxy", async ({ page, createApp }) => {
  const fixture = await createApp({ paymentFailures: ["after-commit-503"] });
  await page.goto("/finance");
  await openPayment(page, fixture);
  await page.getByTestId("pay-amount").fill("10.00");
  await page.getByTestId("pay-submit").click();
  await expect(page.getByTestId("pay-unconfirmed")).toBeVisible();
  await page.getByTestId("pay-submit").click();
  await expect(page.getByTestId("pay-modal")).toHaveCount(0);
  const state = await inspect(page, fixture);
  const calls = state.calls.filter((item) => item.path === "/payments" && item.method === "POST");
  expect(calls).toHaveLength(2);
  expect(calls[0].key).toBe(calls[1].key);
  expect(calls[0].body).toEqual(calls[1].body);
  expect(state.payments).toHaveLength(1);
});

test("automatic session refresh reuses the payment key instead of creating another intent", async ({ page, createApp }) => {
  const fixture = await createApp({ refreshOnMutation: true });
  await page.goto("/finance");
  await openPayment(page, fixture);
  await page.getByTestId("pay-amount").fill("10.00");
  await page.getByTestId("pay-submit").click();
  await expect(page.getByTestId("pay-modal")).toHaveCount(0);
  const state = await inspect(page, fixture);
  const calls = state.calls.filter((item) => item.path === "/payments" && item.method === "POST");
  expect(calls).toHaveLength(2); expect(calls[0].key).toBe(calls[1].key);
  expect(state.calls.filter((item) => item.path === "/auth/refresh")).toHaveLength(1);
  expect(state.payments).toHaveLength(1);
});

test("bank receipts allocate to an order without a credit-note shortcut", async ({ page, createApp }) => {
  const fixture = await createApp();
  await page.goto("/finance");
  await openPayment(page, fixture);
  await page.getByTestId("pay-order").selectOption(fixture.cashOrderId);
  await page.getByTestId("pay-use-due").click();
  await page.getByTestId("pay-mode").selectOption("bank_transfer");
  await page.getByTestId("pay-submit").click();
  await expect(page.getByTestId("pay-modal")).toHaveCount(0);
  expect((await inspect(page, fixture)).payments[0]).toMatchObject({ mode: "bank_transfer", order_id: fixture.cashOrderId, allocation_kind: "order_payment", amount: "37.25" });
});

test("payment validation rejects nonfinite, negative, zero and overprecision input before submitting", async ({ page, createApp }) => {
  const fixture = await createApp();
  await page.goto("/finance");
  await openPayment(page, fixture);
  for (const amount of ["NaN", "Infinity", "-1", "0", "1e3", "1.001", "1,000"]) {
    await page.getByTestId("pay-amount").fill(amount);
    await expect(page.getByTestId("pay-submit")).toBeDisabled();
  }
  expect((await inspect(page, fixture)).calls.some((item) => item.path === "/payments" && item.method === "POST")).toBe(false);
});

test("customer directory shows signed balances, server holds/available credit and positive advances", async ({ page, createApp }) => {
  const fixture = await createApp();
  await page.goto("/customers");
  const row = page.getByTestId(`cust-row-${fixture.customerId}`);
  await expect(row.locator("td[data-label='Credit held']")).toContainText("180.00");
  await expect(row.locator("td[data-label='Available credit']")).toContainText("788.25");
  await expect(row.locator("td[data-label='Account balance']")).toContainText("-25.00");
  await expect(row.locator("td[data-label='Advance balance']")).toContainText("25.00");
  await expect(row.locator("td[data-label='Utilization']")).toHaveCount(0);
});

test("definitive rejection and payload changes create new payment keys", async ({ page, createApp }) => {
  const fixture = await createApp({ paymentFailures: [409, 503] });
  await page.goto("/finance");
  await openPayment(page, fixture);
  await page.getByTestId("pay-amount").fill("10.00");
  await page.getByTestId("pay-submit").click();
  await expect(page.getByTestId("pay-error")).toContainText("rejected by server");
  await expect(page.getByTestId("pay-unconfirmed")).toHaveCount(0);
  await page.getByTestId("pay-submit").click();
  await expect(page.getByTestId("pay-unconfirmed")).toBeVisible();
  await page.getByTestId("pay-amount").fill("11.00");
  await page.getByTestId("pay-submit").click();
  await expect(page.getByTestId("pay-modal")).toHaveCount(0);
  const calls = (await inspect(page, fixture)).calls.filter((item) => item.path === "/payments" && item.method === "POST");
  expect(new Set(calls.map((item) => item.key)).size).toBe(3);
});

test("double submit cannot create two requests while one user intent is active", async ({ page, createApp }) => {
  const fixture = await createApp();
  await page.goto("/finance");
  await openPayment(page, fixture);
  await page.getByTestId("pay-amount").fill("10.00");
  await expect(page.getByTestId("pay-submit")).toBeEnabled();
  await page.getByTestId("pay-submit").evaluate((element: HTMLButtonElement) => { element.click(); element.click(); });
  await expect(page.getByTestId("pay-modal")).toHaveCount(0);
  expect((await inspect(page, fixture)).calls.filter((item) => item.path === "/payments" && item.method === "POST")).toHaveLength(1);
});

test("failed order selectors recover without leaking a previous customer's allocation", async ({ page, createApp }) => {
  const fixture = await createApp({ ordersReadStatus: 503 });
  await page.goto("/finance");
  await openPayment(page, fixture);
  await expect(page.getByRole("alert").filter({ hasText: "Orders unavailable." })).toBeVisible();
  await configure(page, fixture, { ordersReadStatus: 0 });
  await page.getByRole("button", { name: "Retry orders", exact: true }).click();
  await page.getByTestId("pay-order").selectOption(fixture.cashOrderId);
  await page.getByTestId("pay-use-due").click();
  await page.getByTestId("pay-customer").selectOption(fixture.secondCustomerId);
  await expect(page.getByTestId("pay-order")).toHaveValue("");
  await expect(page.getByTestId("pay-amount")).toHaveValue("");
  await expect(page.getByTestId("pay-submit")).toBeDisabled();
  await expect(page.getByTestId("pay-order").locator(`option[value='${fixture.cashOrderId}']`)).toHaveCount(0);
});

test("receipt load errors are not displayed as an empty successful ledger", async ({ page, createApp }) => {
  const fixture = await createApp({ paymentsReadStatus: 503 });
  await page.goto("/finance");
  await expect(page.getByRole("alert").filter({ hasText: "Receipts unavailable." })).toBeVisible();
  await expect(page.getByText("No payments yet.", { exact: true })).toHaveCount(0);
  await configure(page, fixture, { paymentsReadStatus: 0 });
  await page.getByTestId("finance-refresh").click();
  await expect(page.getByText("No payments yet.", { exact: true })).toBeVisible();
});

for (const mode of ["", "cash", "credit"] as const) {
  test(`order creation sends ${mode || "server default"} mode without legacy false-credit bypass`, async ({ page, createApp }) => {
    const fixture = await createApp();
    await page.goto("/orders");
    await fillOrder(page, fixture);
    await page.getByTestId("order-payment-mode").selectOption(mode);
    await page.getByTestId("order-submit").click();
    await expect(page.getByTestId("order-modal")).toHaveCount(0);
    const call = (await inspect(page, fixture)).calls.find((item) => item.path === "/orders" && item.method === "POST")!;
    expect(call.key).toMatch(uuid);
    expect(call.body).toEqual({ customer_id: fixture.customerId, warehouse_id: fixture.warehouseId, ...(mode ? { payment_mode: mode } : {}), items: [{ product_id: fixture.productId, quantity: "1" }] });
  });
}

test("an interrupted order creation keeps its intent key across close and retry", async ({ page, createApp }) => {
  const fixture = await createApp({ orderFailures: ["after-commit-503"] });
  await page.goto("/orders");
  await fillOrder(page, fixture);
  await page.getByTestId("order-submit").click();
  await expect(page.getByTestId("order-unconfirmed")).toBeVisible();
  await page.getByTestId("order-cancel").click();
  await page.getByTestId("orders-new").click();
  await page.getByTestId("order-submit").click();
  await expect(page.getByTestId("order-modal")).toHaveCount(0);
  const state = await inspect(page, fixture);
  const calls = state.calls.filter((item) => item.path === "/orders" && item.method === "POST");
  expect(calls[0].key).toBe(calls[1].key);
  expect(state.orders.filter((item) => item.order_number.startsWith("ORD-NEW"))).toHaveLength(1);
});

test("order detail sends staff into the unified delivery workflow, never direct mark delivered", async ({ page, createApp }) => {
  const fixture = await createApp({ role: "warehouse_manager" });
  await page.goto("/orders");
  await page.getByTestId(`order-row-${fixture.cashOrderId}`).click();
  await expect(page.getByTestId("order-balance")).toContainText("37.25");
  await expect(page.getByTestId("order-action-deliver")).toHaveCount(0);
  await page.getByTestId("order-delivery-workflow").click();
  await expect(page.getByTestId("delivery-detail")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`order_id=${fixture.cashOrderId}`));
  expect((await inspect(page, fixture)).calls.some((item) => item.path.endsWith("/deliver"))).toBe(false);
});

test("manager starts, verifies, draws/uploads a real PNG, previews privately and completes with captured refs", async ({ page, createApp }) => {
  const fixture = await createApp({ role: "warehouse_manager" });
  await openDelivery(page, fixture);
  await expect(page.getByTestId("delivery-complete")).toBeDisabled();
  await page.getByTestId("delivery-start").click();
  await expect(page.getByTestId("delivery-start")).toHaveCount(0);
  await page.getByTestId("delivery-otp").fill("abcdef");
  await expect(page.getByTestId("delivery-verify")).toBeDisabled();
  await page.getByTestId("delivery-otp").fill("123456");
  await page.getByTestId("delivery-verify").click();
  await expect(page.getByTestId("delivery-otp-verified")).toBeVisible();
  const canvas = page.getByTestId("signature-canvas");
  await canvas.scrollIntoViewIfNeeded();
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + 20, box.y + 20); await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 12 }); await page.mouse.up();
  await page.getByTestId("signature-upload").click();
  await expect(page.getByRole("img", { name: "Signature proof of delivery" })).toBeVisible();
  await page.getByTestId("delivery-photo-file").setInputFiles({ name: "delivery.png", mimeType: "image/png", buffer: Buffer.from(fixture.png, "base64") });
  await expect(page.getByRole("img", { name: "Photo proof of delivery" })).toBeVisible();
  await page.getByTestId("delivery-cash").fill("37.25");
  await page.getByTestId("delivery-complete").click();
  await expect(page.getByTestId("delivery-receipt")).toContainText("37.25");
  await expect(page.getByTestId("delivery-photo-file")).toHaveCount(0);
  const state = await inspect(page, fixture);
  const uploads = state.calls.filter((item) => item.path.endsWith("/proofs"));
  expect(uploads).toHaveLength(2);
  expect(uploads[0].body).toMatchObject({ kind: "signature", filename: "signature.png", mime: "image/png", pngWidth: 960, pngHeight: 320 });
  expect(uploads.every((item) => item.contentType?.includes("multipart/form-data; boundary=") && item.cookie?.includes("supplyos_fixture="))).toBe(true);
  const completion = state.calls.find((item) => item.path.endsWith("/complete"))!;
  expect(completion.key).toMatch(uuid);
  expect(completion.body).toEqual({ cash_amount: "37.25", upi_amount: "0.00", signature_url: state.deliveries[0].signature_url, proof_photo_url: state.deliveries[0].proof_photo_url });
  expect(state.calls.filter((item) => item.path.startsWith("/delivery-proofs/")).every((item) => item.method === "GET" && item.cookie?.includes("supplyos_fixture="))).toBe(true);
  expect(state.calls.some((item) => item.path === "/payments")).toBe(false);
  expect(state.orders.find((item) => item.id === fixture.cashOrderId)?.status).toBe("paid");
});

test("file validation, backend rejection and wrong-bound receipts cannot become usable POD", async ({ page, createApp }) => {
  const fixture = await createApp({ verified: true, proofUploadStatus: 422 });
  await openDelivery(page, fixture);
  await page.getByTestId("delivery-photo-file").setInputFiles({ name: "not-photo.csv", mimeType: "text/csv", buffer: Buffer.from("not an image") });
  await expect(page.getByTestId("delivery-action-error")).toContainText("PNG or JPEG");
  await page.getByTestId("delivery-photo-file").setInputFiles({ name: "too-big.png", mimeType: "image/png", buffer: Buffer.alloc(5 * 1024 * 1024 + 1) });
  await expect(page.getByTestId("delivery-action-error")).toContainText("5 MiB");
  expect((await inspect(page, fixture)).calls.filter((item) => item.path.endsWith("/proofs"))).toHaveLength(0);
  const file = { name: "photo.png", mimeType: "image/png", buffer: Buffer.from(fixture.png, "base64") };
  await page.getByTestId("delivery-photo-file").setInputFiles(file);
  await expect(page.getByTestId("delivery-action-error")).toContainText("rejected by server");
  await configure(page, fixture, { proofUploadStatus: 0, wrongProofDelivery: true });
  await page.getByTestId("delivery-signature-file").setInputFiles(file);
  await expect(page.getByTestId("delivery-action-error")).toContainText("did not match this delivery");
  await expect(page.getByTestId("delivery-complete")).toBeDisabled();
  expect((await inspect(page, fixture)).calls.some((item) => item.path.startsWith("/delivery-proofs/"))).toBe(false);
});

test("cash funding is rejected by the server without optimistic completion, then corrected", async ({ page, createApp }) => {
  const fixture = await createApp({ verified: true, withProofs: true, completeFailures: [409] });
  await openDelivery(page, fixture);
  await page.getByTestId("delivery-complete").click();
  await expect(page.getByTestId("delivery-complete-error")).toContainText("rejected by server");
  await expect(page.getByTestId("delivery-receipt")).toHaveCount(0);
  await page.getByTestId("delivery-cash").fill("37.25");
  await page.getByTestId("delivery-complete").click();
  await expect(page.getByTestId("delivery-receipt")).toBeVisible();
  const calls = (await inspect(page, fixture)).calls.filter((item) => item.path.endsWith("/complete"));
  expect(calls[0].key).not.toBe(calls[1].key);
});

test("completion replay retains its proof refs and key and never collects twice", async ({ page, createApp }) => {
  const fixture = await createApp({ verified: true, withProofs: true, completeFailures: ["after-commit-503"] });
  await openDelivery(page, fixture);
  await page.getByTestId("delivery-upi").fill("37.25");
  await page.getByTestId("delivery-complete").click();
  await expect(page.getByTestId("delivery-unconfirmed")).toBeVisible();
  await page.getByTestId("delivery-close").click();
  await page.getByTestId(`delivery-open-${fixture.deliveryId}`).click();
  await expect(page.getByTestId("delivery-upi")).toHaveValue("37.25");
  await page.getByTestId("delivery-complete").click();
  await expect(page.getByTestId("delivery-receipt")).toContainText("37.25");
  const state = await inspect(page, fixture);
  const calls = state.calls.filter((item) => item.path.endsWith("/complete"));
  expect(calls).toHaveLength(2); expect(calls[0].key).toBe(calls[1].key); expect(calls[0].body).toEqual(calls[1].body);
  expect(state.deliveries[0].upi_collected).toBe("37.25");
});

test("unpaid credit delivery remains delivered rather than being labelled paid by the UI", async ({ page, createApp }) => {
  const fixture = await createApp({ verified: true, withProofs: true, creditDelivery: true });
  await openDelivery(page, fixture);
  await page.getByTestId("delivery-complete").click();
  await expect(page.getByTestId("delivery-receipt")).toBeVisible();
  await expect(page.getByTestId("order-balance")).toContainText("Payment unpaid");
  expect((await inspect(page, fixture)).orders.find((item) => item.id === fixture.creditOrderId)?.status).toBe("delivered");
});

test("private previews revoke object URLs on dialog close and never follow public proof URLs", async ({ page, createApp }) => {
  await page.addInitScript(() => {
    const records = { created: [] as string[], revoked: [] as string[] };
    Object.assign(window, { proofUrls: records });
    const create = URL.createObjectURL.bind(URL); const revoke = URL.revokeObjectURL.bind(URL);
    URL.createObjectURL = (blob) => { const url = create(blob); records.created.push(url); return url; };
    URL.revokeObjectURL = (url) => { records.revoked.push(url); revoke(url); };
  });
  const fixture = await createApp({ verified: true, withProofs: true, externalProof: true });
  const external: string[] = [];
  page.on("request", (request) => { if (request.url().includes("not-a-proof.example.test")) external.push(request.url()); });
  await openDelivery(page, fixture);
  await expect(page.getByRole("alert").filter({ hasText: "Only private uploaded proof" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Photo proof of delivery" })).toHaveAttribute("src", /^blob:/);
  await expect(page.getByTestId("delivery-complete")).toBeDisabled();
  await page.getByTestId("delivery-close").click();
  await expect(page.getByTestId("delivery-detail")).toHaveCount(0);
  const urls = await page.evaluate(() => (window as unknown as { proofUrls: { created: string[]; revoked: string[] } }).proofUrls);
  expect(urls.created.length).toBeGreaterThan(0);
  expect(urls.created.every((url) => urls.revoked.includes(url))).toBe(true);
  expect(external).toEqual([]);
});

for (const role of ["customer", "delivery_partner"]) {
  test(`${role} cannot mount the staff POD workflow or load private staff resources`, async ({ page, createApp }) => {
    const fixture = await createApp({ role });
    await page.goto(`/deliveries?delivery_id=${fixture.deliveryId}`);
    await expect(page.getByTestId("staff-access-denied")).toBeVisible();
    await expect(page.getByTestId("delivery-detail")).toHaveCount(0);
    expect((await inspect(page, fixture)).calls.some((item) => ["/settings", "/deliveries", "/payments"].includes(item.path) || item.path.startsWith("/delivery-proofs/"))).toBe(false);
  });
}

test("mobile/light finance and POD dialogs retain focus, tap targets and no horizontal overflow", async ({ page, createApp }) => {
  const fixture = await createApp({ verified: true, withProofs: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/finance");
  await openPayment(page, fixture);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByTestId("pay-note").focus();
  await page.getByTestId("pay-close").focus();
  await page.keyboard.press("Shift+Tab");
  expect(await page.getByTestId("pay-modal").evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("pay-modal")).toHaveCount(0);
  await openDelivery(page, fixture);
  const overflow = await page.getByTestId("delivery-detail").evaluate((element) => element.scrollWidth > element.clientWidth);
  expect(overflow).toBe(false);
  expect((await page.getByTestId("delivery-complete").boundingBox())!.height).toBeGreaterThanOrEqual(40);
});
