"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Search } from "lucide-react";
import { api, apiError } from "@/lib/api";
import { productsQuery } from "@/lib/products";
import { customersQuery, refreshFinancialQueries, type OrderFinance } from "@/lib/finance";
import { useIntentPost } from "@/lib/intent";
import { Modal } from "@/components/modal";
import { CustomerBalance, OrderBalance } from "@/components/financial-summary";
import { formatDateTime, formatINR, formatQty } from "@/lib/utils";

interface OrderItem {
  id: string;
  product_id: string;
  product_sku: string;
  product_name: string;
  quantity: string;
  unit_price: string;
  line_subtotal: string;
  line_tax: string;
  line_total: string;
}
interface Order extends OrderFinance {
  warehouse_id: string;
  channel: string;
  subtotal: string;
  tax_total: string;
  created_at: string;
  delivered_at: string | null;
  items: OrderItem[];
}
interface Warehouse {
  id: string;
  name: string;
  code: string;
}
const STATUS_COLORS: Record<string, string> = {
  pending: "chip-muted",
  confirmed: "chip-info",
  reserved: "chip-volt",
  picked: "chip-info",
  packed: "chip-info",
  out_for_delivery: "chip-warning",
  delivered: "chip-success",
  paid: "chip-success",
  completed: "chip-success",
  cancelled: "chip-alert",
};

export default function OrdersPage() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [show, setShow] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["orders", q, statusFilter],
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams();
      params.set("page_size", "100");
      if (q) params.set("q", q);
      if (statusFilter) params.set("status", statusFilter);
      return (await api.get<{ items: Order[] }>(`/orders?${params}`, { signal })).data;
    },
  });

  return (
    <div className="page-shell">
      <header className="page-header">
        <div>
          <p className="data-label">Fulfilment</p>
          <h1 className="page-title">Orders</h1>
        </div>
        <div className="flex gap-2 items-center flex-wrap w-full sm:w-auto">
          <select
            className="input"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            data-testid="orders-status-filter"
          >
            <option value="">All statuses</option>
            {Object.keys(STATUS_COLORS).map((s) => (
              <option key={s} value={s}>
                {s.replace("_", " ")}
              </option>
            ))}
          </select>
          <div className="relative w-full sm:w-auto">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary"
            />
            <input
              className="input pl-8 w-full sm:w-64"
              placeholder="Order # search…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              data-testid="orders-search"
            />
          </div>
          <button
            className="btn-volt inline-flex items-center gap-2"
            onClick={() => setShow(true)}
            data-testid="orders-new"
          >
            <Plus size={14} /> New order
          </button>
        </div>
      </header>

      <div className="page-body">
        {isPending && <p role="status">Loading orders...</p>}
        {error && <p role="alert">{apiError(error)} <button className="btn-ghost" onClick={() => void refetch()}>Retry orders</button></p>}
        <div className="pane overflow-x-auto mobile-cards">
          <table className="grid" data-testid="orders-table">
            <thead>
              <tr>
                <th>Order #</th>
                <th>Status</th>
                <th>Payment</th>
                <th>Channel</th>
                <th>Placed</th>
                <th className="text-right">Subtotal</th>
                <th className="text-right">GST</th>
                <th className="text-right">Total</th>
                <th className="text-right">Paid</th>
                <th className="text-right">Due</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data && !data.items.length && (
                <tr>
                  <td colSpan={11} className="text-text-secondary">
                    No orders yet.
                  </td>
                </tr>
              )}
              {data?.items?.map((o) => (
                <tr
                  key={o.id}
                  data-testid={`order-row-${o.id}`}
                  className="cursor-pointer"
                  onClick={() => setOpenId(o.id)}
                >
                  <td data-label="Order #">{o.order_number}</td>
                  <td data-label="Status">
                    <span
                      className={`chip ${STATUS_COLORS[o.status] || "chip-muted"}`}
                    >
                      {o.status.replace("_", " ")}
                    </span>
                  </td>
                  <td data-label="Payment"><span className="chip chip-info">{o.payment_mode} / {o.payment_status}</span></td>
                  <td data-label="Channel">{o.channel}</td>
                  <td data-label="Placed">{formatDateTime(o.created_at)}</td>
                  <td data-label="Subtotal" className="text-right">
                    {formatINR(o.subtotal)}
                  </td>
                  <td data-label="GST" className="text-right">
                    {formatINR(o.tax_total)}
                  </td>
                  <td data-label="Total" className="text-right font-bold">
                    {formatINR(o.grand_total)}
                  </td>
                  <td data-label="Paid" className="text-right">
                    {formatINR(o.amount_paid)}
                  </td>
                  <td data-label="Due" className="text-right">{formatINR(o.amount_due)}</td>
                  <td data-label="" className="no-label">
                    <button className="btn-ghost text-xs" aria-label={`Open order ${o.order_number}`} onClick={(event) => { event.stopPropagation(); setOpenId(o.id); }}>Open</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <NewOrderModal
        open={show}
        onClose={() => setShow(false)}
        onDone={() => void refreshFinancialQueries(qc)}
      />
      {openId && (
        <OrderDetail
          id={openId}
          onClose={() => setOpenId(null)}
          onChanged={() => void refreshFinancialQueries(qc)}
        />
      )}
    </div>
  );
}

function NewOrderModal({
  open,
  onClose,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const customerQuery = useQuery({ ...customersQuery, enabled: open });
  const customers = customerQuery.data;
  const warehouseQuery = useQuery({
    queryKey: ["warehouses"],
    enabled: open,
    queryFn: async ({ signal }) => (await api.get<Warehouse[]>("/warehouses", { signal })).data,
  });
  const warehouses = warehouseQuery.data;
  const productQuery = useQuery({ ...productsQuery, enabled: open });
  const products = productQuery.data;

  const [customerId, setCustomerId] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [paymentMode, setPaymentMode] = useState<"" | "cash" | "credit">("");
  const [items, setItems] = useState<
    { product_id: string; quantity: string }[]
  >([{ product_id: "", quantity: "1" }]);
  const mutation = useIntentPost();
  const customer = customers?.find((item) => item.id === customerId);

  const canSubmit =
    customerId &&
    warehouseId &&
    items.length > 0 &&
    items.every((i) => i.product_id && /^\d{1,13}(?:\.\d{1,3})?$/.test(i.quantity) && /[1-9]/.test(i.quantity));

  async function submit() {
    if (!canSubmit) return;
    const result = await mutation.post<Order>("/orders", {
      customer_id: customerId,
      warehouse_id: warehouseId,
      ...(paymentMode ? { payment_mode: paymentMode } : {}),
      items: items.map((item) => ({ product_id: item.product_id, quantity: item.quantity })),
    });
    if (!result) return;
    toast.success("Order created.");
    setCustomerId("");
    setWarehouseId("");
    setPaymentMode("");
    setItems([{ product_id: "", quantity: "1" }]);
    onDone();
    onClose();
  }

  return (
    <Modal open={open} busy={mutation.busy} onClose={onClose} labelledBy="new-order-title" testId="order-modal">
        <p className="data-label">Create order</p>
        <h3 id="new-order-title" className="font-display text-2xl font-bold mt-1 mb-4">New order</h3>
        {[customerQuery, warehouseQuery, productQuery].some((query) => query.isPending) && <p role="status">Loading order choices...</p>}
        {[customerQuery, warehouseQuery, productQuery].map((query, index) => query.error ? <p key={index} role="alert">{apiError(query.error)} <button className="btn-ghost" onClick={() => void query.refetch()}>Retry choices</button></p> : null)}
        <fieldset disabled={mutation.busy}>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="data-label">Customer *</label>
            <select
              className="input mt-1"
              value={customerId}
              onChange={(e) => { mutation.payloadChanged(); setCustomerId(e.target.value); }}
              data-testid="order-customer"
            >
              <option value="">Select…</option>
              {customers?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code} — {c.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="data-label">Warehouse *</label>
            <select
              className="input mt-1"
              value={warehouseId}
              onChange={(e) => { mutation.payloadChanged(); setWarehouseId(e.target.value); }}
              data-testid="order-warehouse"
            >
              <option value="">Select…</option>
              {warehouses?.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.code} — {w.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="mt-3 space-y-3">
          <label className="data-label" htmlFor="order-payment-mode">Payment mode</label>
          <select id="order-payment-mode" className="input" value={paymentMode} onChange={(event) => {
            mutation.payloadChanged(); setPaymentMode(event.target.value as "" | "cash" | "credit");
          }} data-testid="order-payment-mode">
            <option value="">Customer default (server decides)</option>
            <option value="cash">Cash / fully allocated receipts required for delivery</option>
            <option value="credit">Credit / server validates and holds credit</option>
          </select>
          <p className="text-xs text-text-secondary">Default follows the customer type on the server. Choosing cash does not bypass payment requirements.</p>
          {customer && <CustomerBalance customer={customer} />}
        </div>

        <p className="data-label mt-4 mb-2">Line items</p>
        {items.map((it, i) => (
          <div
            key={i}
            className="grid grid-cols-1 sm:grid-cols-6 gap-2 mb-2"
            data-testid={`order-line-${i}`}
          >
            <select
              className="input sm:col-span-4"
              value={it.product_id}
              onChange={(e) => {
                mutation.payloadChanged();
                setItems(items.map((item, index) => index === i ? { ...item, product_id: e.target.value } : item));
              }}
              aria-label={`Product for line ${i + 1}`}
            >
              <option value="">Select product…</option>
              {products?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.sku} — {p.name}
                </option>
              ))}
            </select>
            <input
              className="input"
              value={it.quantity}
              inputMode="decimal"
              onChange={(e) => {
                mutation.payloadChanged();
                setItems(items.map((item, index) => index === i ? { ...item, quantity: e.target.value } : item));
              }}
              aria-label={`Quantity for line ${i + 1}`}
            />
            <button
              className="btn-ghost"
              onClick={() => { mutation.payloadChanged(); setItems(items.filter((_, ix) => ix !== i)); }}
              aria-label={`Remove line ${i + 1}`}
            >
              ×
            </button>
          </div>
        ))}
        <button
          className="btn-ghost text-xs"
          data-testid="order-add-line"
          onClick={() => { mutation.payloadChanged(); setItems([...items, { product_id: "", quantity: "1" }]); }}
        >
          + Add line
        </button>
        </fieldset>
        {mutation.error && <p role="alert" className="mt-3" data-testid="order-error">{mutation.error}</p>}
        {mutation.unconfirmed && <p role="status" className="text-sm mt-2" data-testid="order-unconfirmed">Result unconfirmed. Retry unchanged with the same request key. Changing fields starts a new order intent.</p>}

        <div className="flex justify-end gap-2 mt-5">
          <button
            className="btn-ghost"
            onClick={onClose}
            disabled={mutation.busy}
            data-testid="order-cancel"
          >
            Cancel
          </button>
          <button
            className="btn-volt"
            onClick={submit}
            disabled={mutation.busy || !canSubmit}
            data-testid="order-submit"
          >
            {mutation.busy ? "Saving..." : mutation.unconfirmed ? "Retry order" : "Create order"}
          </button>
        </div>
    </Modal>
  );
}

function OrderDetail({
  id,
  onClose,
  onChanged,
}: {
  id: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { data: order, error, isPending, refetch } = useQuery({
    queryKey: ["order", id],
    queryFn: async ({ signal }) => (await api.get<Order>(`/orders/${id}`, { signal })).data,
  });
  const [busy, setBusy] = useState(false);

  async function action(path: string, body?: unknown) {
    if (busy) return;
    setBusy(true);
    try {
      await api.post(`/orders/${id}/${path}`, body ?? {});
      toast.success(`Order → ${path}`);
      await refetch();
      onChanged();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setBusy(false);
    }
  }

  const status = order?.status;
  const nextActions: { key: string; label: string; body?: unknown }[] = [];
  if (status === "pending")
    nextActions.push({ key: "confirm", label: "Confirm →" });
  if (status === "confirmed")
    nextActions.push({ key: "reserve", label: "Reserve stock →" });
  if (status === "reserved") nextActions.push({ key: "pick", label: "Pick →" });
  if (status === "picked") nextActions.push({ key: "pack", label: "Pack →" });
  if (status === "packed")
    nextActions.push({ key: "dispatch", label: "Dispatch →" });
  if (status && ["pending", "confirmed", "reserved", "picked", "packed", "out_for_delivery"].includes(status)) {
    nextActions.push({
      key: "cancel",
      label: "Cancel order",
      body: { note: "cancelled from admin" },
    });
  }

  return (
    <Modal open busy={busy} onClose={onClose} labelledBy="order-detail-title" testId="order-detail">
        <div className="flex items-start justify-between mb-4">
          <div>
            <p className="data-label">Order</p>
            <h3 id="order-detail-title" className="font-display text-3xl font-black tracking-tightest">
              {order?.order_number || "…"}
            </h3>
            <p className="text-text-secondary text-sm mt-1">
              {order && formatDateTime(order.created_at)} · via {order?.channel}
            </p>
          </div>
          <span
            className={`chip ${order ? STATUS_COLORS[order.status] || "chip-muted" : ""}`}
          >
            {order?.status?.replace("_", " ")}
          </span>
        </div>
        {isPending && <p role="status">Loading order...</p>}
        {error && <p role="alert">{apiError(error)} <button className="btn-ghost" onClick={() => void refetch()}>Retry order</button></p>}

        {order && (
          <>
            <OrderBalance order={order} />
            <div className="mobile-cards">
              <table className="grid w-full mb-4">
                <thead>
                  <tr>
                    <th>SKU</th>
                    <th>Product</th>
                    <th className="text-right">Qty</th>
                    <th className="text-right">Unit ₹</th>
                    <th className="text-right">Line ₹</th>
                  </tr>
                </thead>
                <tbody>
                  {order.items.map((it) => (
                    <tr key={it.id}>
                      <td data-label="SKU">{it.product_sku}</td>
                      <td data-label="Product">{it.product_name}</td>
                      <td data-label="Qty" className="text-right">
                        {formatQty(it.quantity)}
                      </td>
                      <td data-label="Unit ₹" className="text-right">
                        {formatINR(it.unit_price)}
                      </td>
                      <td data-label="Line ₹" className="text-right">
                        {formatINR(it.line_total)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pane p-4 flex flex-wrap justify-end gap-4 sm:gap-8 font-mono text-sm">
              <div>
                <span className="data-label mr-2">Sub</span>
                {formatINR(order.subtotal)}
              </div>
              <div>
                <span className="data-label mr-2">GST</span>
                {formatINR(order.tax_total)}
              </div>
              <div>
                <span className="data-label mr-2">Total</span>
                <span className="text-volt text-lg font-bold">
                  {formatINR(order.grand_total)}
                </span>
              </div>
            </div>
          </>
        )}

        <div className="flex flex-wrap gap-2 mt-6">
          {order && ["out_for_delivery", "delivered", "paid", "completed"].includes(order.status) && <Link className="btn-volt" data-testid="order-delivery-workflow" href={`/deliveries?order_id=${encodeURIComponent(order.id)}`}>Open delivery / OTP and proof</Link>}
          {nextActions.map((a) => (
            <button
              key={a.key}
              className={
                a.key === "cancel" ? "btn-ghost text-status-alert" : "btn-volt"
              }
              data-testid={`order-action-${a.key}`}
              onClick={() => action(a.key, a.body)}
              disabled={busy}
            >
              {a.label}
            </button>
          ))}
          <button
            className="btn-ghost ml-auto"
            onClick={onClose}
            disabled={busy}
            data-testid="order-close"
          >
            Close
          </button>
        </div>
    </Modal>
  );
}
