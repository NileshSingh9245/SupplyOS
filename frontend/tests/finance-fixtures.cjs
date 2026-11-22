const { randomUUID } = require("node:crypto");
const { deflateSync } = require("node:zlib");

// Explicit protocol fixtures only. Neither the app nor the user preview imports this module.
const fixtures = new Map();
const timestamp = "2026-11-09T12:00:00.000Z";

function pngChunk(type, data) {
  const content = Buffer.concat([Buffer.from(type), data]);
  let crc = 0xffffffff;
  for (const byte of content) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = crc & 1 ? 0xedb88320 ^ (crc >>> 1) : crc >>> 1;
  }
  const size = Buffer.alloc(4); size.writeUInt32BE(data.length);
  const checksum = Buffer.alloc(4); checksum.writeUInt32BE((crc ^ 0xffffffff) >>> 0);
  return Buffer.concat([size, content, checksum]);
}

function testPng() {
  const header = Buffer.alloc(13); header.writeUInt32BE(2, 0); header.writeUInt32BE(1, 4);
  header[8] = 8; header[9] = 6;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), pngChunk("IHDR", header),
    pngChunk("IDAT", deflateSync(Buffer.from([0, 255, 255, 255, 255, 0, 0, 0, 255]))),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

function createFixture(config) {
  const id = randomUUID();
  const customerId = randomUUID();
  const secondCustomerId = randomUUID();
  const productId = randomUUID();
  const warehouseId = randomUUID();
  const cashOrderId = randomUUID();
  const creditOrderId = randomUUID();
  const deliveryId = randomUUID();
  const customer = {
    id: customerId, code: "CUS-TEST", name: "Fixture customer", customer_type: "credit", is_active: !config.inactiveCustomer,
    business_name: null, phone: null, gstin: null, price_tier: null,
    credit_limit: "1000.00", outstanding: "-25.00", credit_held: "180.00", cash_funded_pending: "56.75",
    credit_exposure: "211.75", available_credit: "788.25", advance_balance: "25.00",
  };
  const base = {
    customer_id: customerId, warehouse_id: warehouseId, status: "out_for_delivery", channel: "manual",
    subtotal: "95.24", tax_total: "4.76", grand_total: "100.00", created_at: timestamp, delivered_at: null,
    items: [{ id: randomUUID(), product_id: productId, product_sku: "FIXTURE", product_name: "Fixture product",
      quantity: "1", unit_price: "95.24", line_subtotal: "95.24", line_tax: "4.76", line_total: "100.00" }],
  };
  const orders = [
    { ...base, id: cashOrderId, order_number: "ORD-CASH", payment_mode: "cash", payment_status: "partial", amount_paid: "62.75", amount_due: config.amountDue || "37.25", credit_hold_amount: "0.00" },
    { ...base, id: creditOrderId, order_number: "ORD-CREDIT", payment_mode: "credit", payment_status: "unpaid", amount_paid: "0.00", amount_due: "100.00", credit_hold_amount: "100.00" },
    { ...base, id: randomUUID(), customer_id: secondCustomerId, order_number: "ORD-OTHER", payment_mode: "cash", payment_status: "unpaid", amount_paid: "0.00", amount_due: "100.00", credit_hold_amount: "0.00" },
  ];
  const proofMap = new Map();
  const delivery = {
    id: deliveryId, order_id: config.creditDelivery ? creditOrderId : cashOrderId, partner_id: null,
    scheduled_date: "2026-11-09", priority: 5, otp_verified: !!config.verified,
    signature_url: null, proof_photo_url: null, cash_collected: "0.00", upi_collected: "0.00",
    started_at: null, completed_at: null, created_at: timestamp,
  };
  if (config.withProofs) {
    for (const kind of ["signature", "photo"]) {
      const proofId = randomUUID();
      proofMap.set(proofId, { kind, bytes: testPng(), mime: "image/png" });
      delivery[kind === "signature" ? "signature_url" : "proof_photo_url"] = `/api/v1/delivery-proofs/${proofId}`;
    }
  }
  if (config.externalProof) delivery.signature_url = "https://not-a-proof.example.test/image.png";
  return {
    id, config, user: { id: randomUUID(), tenant_id: randomUUID(), email: "staff@example.test", full_name: "Fixture staff", role: config.role || "super_admin", is_active: true },
    customers: [customer, { ...customer, id: secondCustomerId, code: "CUS-OTHER", name: "Other customer", customer_type: "cash" }],
    orders, deliveries: [delivery], payments: [], calls: [], replay: new Map(), proofs: proofMap,
    productId, warehouseId, cashOrderId, creditOrderId, customerId, secondCustomerId, deliveryId,
  };
}

function json(response, status, data, headers = {}) {
  response.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store", ...headers });
  response.end(JSON.stringify(data));
}

async function bytes(request) {
  const chunks = []; for await (const chunk of request) chunks.push(chunk);
  return Buffer.concat(chunks);
}

function snapshot(state) {
  return {
    customerId: state.customerId, secondCustomerId: state.secondCustomerId, cashOrderId: state.cashOrderId,
    creditOrderId: state.creditOrderId, deliveryId: state.deliveryId, productId: state.productId,
    warehouseId: state.warehouseId, calls: state.calls, payments: state.payments,
    orders: state.orders, deliveries: state.deliveries, proofCount: state.proofs.size,
  };
}

async function handleFinanceFixture(request, response) {
  const url = new URL(request.url, "http://127.0.0.1:3801");
  if (url.pathname === "/__fixtures" && request.method === "POST") {
    const config = JSON.parse((await bytes(request)).toString() || "{}");
    const state = createFixture(config); fixtures.set(state.id, state);
    json(response, 201, { id: state.id, ...snapshot(state), png: testPng().toString("base64") }, {
      "Set-Cookie": `supplyos_fixture=${state.id}; Path=/; HttpOnly; SameSite=Lax`,
    });
    return true;
  }
  const management = /^\/__fixtures\/([^/]+)$/.exec(url.pathname);
  if (management) {
    const state = fixtures.get(management[1]);
    if (!state) { json(response, 404, { detail: "Fixture not found." }); return true; }
    if (request.method === "DELETE") { fixtures.delete(state.id); json(response, 200, {}); }
    else if (request.method === "PATCH") { Object.assign(state.config, JSON.parse((await bytes(request)).toString())); json(response, 200, {}); }
    else json(response, 200, snapshot(state));
    return true;
  }
  if (!url.pathname.startsWith("/api/v1/")) return false;
  const cookie = /(?:^|;\s*)supplyos_fixture=([^;]+)/.exec(request.headers.cookie || "");
  const state = cookie && fixtures.get(cookie[1]);
  if (!state) return false;
  const path = url.pathname.slice("/api/v1".length);
  const raw = await bytes(request);
  const multipart = (request.headers["content-type"] || "").startsWith("multipart/form-data;");
  const body = raw.length && !multipart ? JSON.parse(raw.toString()) : null;
  const call = { path, method: request.method, query: url.search, body, cookie: request.headers.cookie,
    contentType: request.headers["content-type"], key: request.headers["x-idempotency-key"] || null };
  state.calls.push(call);
  if (path === "/auth/me") { json(response, state.config.loggedOut ? 401 : 200, state.config.loggedOut ? { detail: "Logged out." } : state.user); return true; }
  if (path === "/auth/logout") { state.config.loggedOut = true; json(response, 200, {}); return true; }
  if (path === "/auth/refresh") { json(response, state.config.allowRefresh ? 200 : 401, state.config.allowRefresh ? {} : { detail: "Test session expired." }); return true; }
  if (path === "/settings") { json(response, 200, { tenant_id: state.user.tenant_id, company_name: "Fixture SupplyOS", currency_code: "INR", currency_symbol: "INR", locale: "en-IN", values: {} }); return true; }
  if (path === "/customers") { json(response, 200, { items: state.customers, total: 2 }); return true; }
  if (path === "/products") { json(response, 200, { items: [{ id: state.productId, sku: "FIXTURE", name: "Fixture product", unit: "kg", base_price: "10.00" }], total: 1 }); return true; }
  if (path === "/warehouses") { json(response, 200, [{ id: state.warehouseId, code: "WH-TEST", name: "Fixture warehouse" }]); return true; }
  if (path === "/deliveries" && request.method === "GET") { json(response, 200, state.deliveries); return true; }
  if (path === "/payments" && request.method === "GET") {
    if (state.config.paymentsReadStatus) { json(response, state.config.paymentsReadStatus, { detail: "Receipts unavailable." }); return true; }
    const customerId = url.searchParams.get("customer_id");
    json(response, 200, state.payments.filter((item) => !customerId || item.customer_id === customerId)); return true;
  }
  if (path === "/orders" && request.method === "GET") {
    if (state.config.ordersReadStatus) { json(response, state.config.ordersReadStatus, { detail: "Orders unavailable." }); return true; }
    const customerId = url.searchParams.get("customer_id");
    json(response, 200, { items: state.orders.filter((item) => !customerId || item.customer_id === customerId), total: state.orders.filter((item) => !customerId || item.customer_id === customerId).length }); return true;
  }
  const orderId = /^\/orders\/([^/]+)$/.exec(path);
  if (orderId && request.method === "GET") { json(response, 200, state.orders.find((item) => item.id === orderId[1])); return true; }
  const proofId = /^\/delivery-proofs\/([^/]+)$/.exec(path);
  if (proofId) {
    if (state.config.loggedOut || state.config.proofReadStatus) { json(response, state.config.proofReadStatus || 401, { detail: "Proof unavailable." }); return true; }
    const proof = state.proofs.get(proofId[1]);
    if (!proof) { json(response, 404, { detail: "Proof not in this fixture session." }); return true; }
    response.writeHead(200, { "Content-Type": proof.mime, "Cache-Control": "private, no-store" }).end(proof.bytes); return true;
  }
  const deliveryAction = /^\/deliveries\/([^/]+)\/(start|verify-otp|proofs|complete)$/.exec(path);
  if (deliveryAction && deliveryAction[2] === "proofs") {
    if (!multipart) { json(response, 422, { detail: "Multipart boundary missing." }); return true; }
    const data = await new Response(raw, { headers: { "Content-Type": request.headers["content-type"] } }).formData();
    const kind = data.get("kind"); const file = data.get("file");
    const image = Buffer.from(await file.arrayBuffer());
    call.body = { kind, filename: file.name, mime: file.type, size: image.length,
      pngWidth: image.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])) ? image.readUInt32BE(16) : null,
      pngHeight: image.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])) ? image.readUInt32BE(20) : null };
    if (state.config.proofUploadStatus) { json(response, state.config.proofUploadStatus, { detail: "Image rejected by server validation." }); return true; }
    const id = randomUUID(); state.proofs.set(id, { bytes: image, mime: file.type, kind });
    json(response, 201, { id, delivery_id: state.config.wrongProofDelivery ? randomUUID() : state.deliveryId, kind, mime: file.type, size: image.length, url: `/api/v1/delivery-proofs/${id}` }); return true;
  }
  if (deliveryAction && ["start", "verify-otp"].includes(deliveryAction[2])) {
    const delivery = state.deliveries[0];
    if (deliveryAction[2] === "start") delivery.started_at = timestamp;
    else if (body.otp_code !== "123456") { json(response, 409, { detail: "Invalid OTP" }); return true; }
    else delivery.otp_verified = true;
    json(response, 200, delivery); return true;
  }
  if (request.method === "POST" && (["/payments", "/orders"].includes(path) || deliveryAction?.[2] === "complete")) {
    if (state.config.refreshOnMutation) { state.config.refreshOnMutation = false; state.config.allowRefresh = true; json(response, 401, { detail: "Test access expired." }); return true; }
    const key = request.headers["x-idempotency-key"];
    if (!key || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(key)) { json(response, 422, { detail: "UUID idempotency key required by test contract." }); return true; }
    const scope = `${path}:${key}`; const serialized = JSON.stringify(body); const replay = state.replay.get(scope);
    if (replay) { json(response, replay.payload === serialized ? replay.status : 409, replay.payload === serialized ? replay.data : { detail: "Idempotency payload changed." }); return true; }
    const failureName = path === "/payments" ? "paymentFailures" : path === "/orders" ? "orderFailures" : "completeFailures";
    const failure = state.config[failureName]?.shift();
    if (typeof failure === "number") { json(response, failure, { detail: failure === 409 ? "Funding or allocation rejected by server." : "Temporary server failure." }); return true; }
    let result;
    const status = path === "/orders" || path === "/payments" ? 201 : 200;
    if (path === "/payments") {
      result = { id: randomUUID(), ...body, order_id: body.order_id || null, allocation_kind: body.order_id ? "order_payment" : body.mode === "credit" ? "credit_note" : "unallocated_advance", created_at: timestamp };
      state.payments.push(result);
    } else if (path === "/orders") {
      result = { ...state.orders[0], ...body, id: randomUUID(), status: "pending", order_number: `ORD-NEW-${state.orders.length}`, payment_mode: body.payment_mode || "credit" };
      state.orders.push(result);
    } else {
      const delivery = state.deliveries[0];
      if (!delivery.otp_verified || !body.signature_url || !body.proof_photo_url) { json(response, 409, { detail: "OTP and stored proof required." }); return true; }
      Object.assign(delivery, { completed_at: timestamp, signature_url: body.signature_url, proof_photo_url: body.proof_photo_url, cash_collected: body.cash_amount, upi_collected: body.upi_amount });
      const order = state.orders.find((item) => item.id === delivery.order_id);
      Object.assign(order, state.config.creditDelivery ? { status: "delivered", delivered_at: timestamp } : { status: "paid", payment_status: "paid", amount_paid: "100.00", amount_due: "0.00", delivered_at: timestamp });
      result = { ...delivery };
    }
    state.replay.set(scope, { payload: serialized, status, data: result });
    if (failure === "after-commit-503") json(response, 503, { detail: "Response interrupted after test commit." });
    else json(response, status, result);
    return true;
  }
  json(response, 404, { detail: "Unexpected finance/POD fixture route." });
  return true;
}

module.exports = { handleFinanceFixture };
